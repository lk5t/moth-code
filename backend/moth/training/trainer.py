"""The MOTH training loop: real forward passes, backpropagation and AdamW updates.

Features: cosine LR with warmup, gradient accumulation, gradient clipping,
mixed precision on CUDA (bf16, or fp16 with loss scaling), CPU fallback,
periodic validation, atomic checkpoints, exact resume (model, optimizer,
scaler, RNG and data-sampler state), graceful stop via event or ``STOP`` file,
and optional GPU usage limits (memory fraction and duty-cycle throttling).
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch

from moth.model.config import MothConfig, preset
from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel
from moth.training.checkpoint import (RunLock, latest_checkpoint, load_checkpoint, load_latest_verified,
                                     save_checkpoint)
from moth.training.data import MixtureDataset, dataset_meta, open_dataset


@dataclass
class TrainConfig:
    run_name: str = "moth-run"
    dataset: str = ""  # prepared dataset directory
    out_dir: str = ""  # run directory (checkpoints, metrics)
    preset: str = "moth-50m"
    model_overrides: dict[str, Any] = field(default_factory=dict)
    seq_len: int = 1024
    batch_size: int = 8
    grad_accum: int = 4
    batch_autotune: bool = False
    max_steps: int = 20000
    lr: float = 6e-4
    min_lr: float = 6e-5
    warmup_steps: int = 500
    weight_decay: float = 0.1
    beta1: float = 0.9
    beta2: float = 0.95
    grad_clip: float = 1.0
    eval_interval: int = 250
    eval_iters: int = 20
    log_interval: int = 10
    checkpoint_interval: int = 500
    keep_checkpoints: int = 3
    keep_every: int = 0  # also keep every N-th step's checkpoint (milestones)
    device: str = "auto"  # auto | cuda | cpu
    precision: str = "auto"  # auto | bf16 | fp16 | fp32
    seed: int = 1337
    gradient_checkpointing: bool = False
    # Resource limits (used by community training and user scheduling)
    gpu_memory_fraction: float | None = None
    duty_cycle: float = 1.0  # fraction of wall time spent computing (1.0 = no throttling)
    init_from: str | None = None  # start from an exported model / checkpoint instead of random init
    init_optimizer: bool = True  # continuing a lineage: also restore the optimizer moments when compatible
    mixture: dict[str, float] | None = None  # Data Factory mixture weights (curriculum)
    threads: int | None = None  # CPU threads (None = all but one)
    lineage: dict[str, Any] = field(default_factory=dict)  # lineage id, parent checkpoint, cumulative counters

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrainConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cpu_has_fast_bf16() -> bool:
    try:
        if hasattr(torch.cpu, "_is_amx_tile_supported") and torch.cpu._is_amx_tile_supported():
            return True
        if hasattr(torch.cpu, "_is_avx512_bf16_supported") and torch.cpu._is_avx512_bf16_supported():
            return True
    except Exception:
        pass
    return False


def pick_device(requested: str = "auto") -> str:
    if requested == "cpu":
        return "cpu"
    if requested.startswith("cuda") or requested == "auto":
        try:
            if torch.cuda.is_available():
                torch.zeros(1, device="cuda")  # probe: broken drivers raise here
                return "cuda" if requested == "auto" else requested
        except Exception:
            pass
        if requested.startswith("cuda"):
            raise RuntimeError("CUDA was requested but no working CUDA device is available")
    return "cpu"


def lr_at(step: int, cfg: TrainConfig) -> float:
    if step < cfg.warmup_steps:
        return cfg.lr * (step + 1) / cfg.warmup_steps
    if step >= cfg.max_steps:
        return cfg.min_lr
    ratio = (step - cfg.warmup_steps) / max(1, cfg.max_steps - cfg.warmup_steps)
    return cfg.min_lr + 0.5 * (1 + math.cos(math.pi * ratio)) * (cfg.lr - cfg.min_lr)


def build_model_config(cfg: TrainConfig, tokenizer_vocab: int) -> MothConfig:
    overrides = dict(cfg.model_overrides)
    vocab = ((tokenizer_vocab + 63) // 64) * 64  # pad for efficient matmuls
    overrides["vocab_size"] = vocab
    mc = preset(cfg.preset, **overrides)
    if cfg.seq_len > mc.max_seq_len:
        raise ValueError(f"seq_len {cfg.seq_len} exceeds the model context window {mc.max_seq_len}")
    return mc


EventFn = Callable[[dict[str, Any]], None]


class Trainer:
    def __init__(self, cfg: TrainConfig, on_event: EventFn | None = None,
                 should_stop: Callable[[], bool] | None = None):
        self.cfg = cfg
        self.on_event = on_event or (lambda e: None)
        self._should_stop = should_stop or (lambda: False)
        self.run_dir = Path(cfg.out_dir)
        (self.run_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        meta = dataset_meta(cfg.dataset)
        self.tokenizer = Tokenizer.load(meta["tokenizer_path"])
        if self.tokenizer.fingerprint() != meta["tokenizer_fingerprint"]:
            raise ValueError("dataset was prepared with a different tokenizer than the one on disk")
        self.dataset_meta = meta
        self.device = pick_device(cfg.device)
        self.model_cfg = build_model_config(cfg, self.tokenizer.vocab_size)
        self.step = 0
        self.best_val = float("inf")
        self.tokens_seen = 0  # this run

    # ---- helpers -----------------------------------------------------------
    def emit(self, kind: str, **data: Any) -> None:
        event = {"kind": kind, "run": self.cfg.run_name, "step": self.step, **data}
        with open(self.run_dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        self.on_event(event)

    def should_stop(self) -> bool:
        return self._should_stop() or (self.run_dir / "STOP").exists()

    def _precision(self) -> tuple[torch.dtype | None, bool]:
        p = self.cfg.precision
        if self.device == "cpu":
            # bf16 autocast is ~2x faster only where the CPU has bf16 matrix units (AMX / AVX512-BF16)
            if p == "bf16" or (p == "auto" and cpu_has_fast_bf16()):
                return torch.bfloat16, False
            return None, False
        if p == "fp32":
            return None, False
        if p == "bf16" or (p == "auto" and torch.cuda.is_bf16_supported()):
            return torch.bfloat16, False
        return torch.float16, True

    @torch.no_grad()
    def evaluate(self, model: MothModel, data, amp_dtype) -> float:
        loss, _ = self.evaluate_domains(model, data, amp_dtype)
        return loss

    @torch.no_grad()
    def evaluate_domains(self, model: MothModel, data, amp_dtype) -> tuple[float, dict[str, float]]:
        """Validation loss overall and, for mixtures, per capability domain (the same batches every time)."""
        model.eval()
        parts = data.domain_batches() if isinstance(data, MixtureDataset) else {"all": data}
        per: dict[str, float] = {}
        iters = max(2, self.cfg.eval_iters // max(1, len(parts))) if len(parts) > 1 else self.cfg.eval_iters
        for name, part in parts.items():
            gen = torch.Generator().manual_seed(1234)
            losses = []
            for _ in range(iters):
                x, y, m = part.batch(self.cfg.batch_size, gen, self.device)
                with torch.autocast(self.device, dtype=amp_dtype, enabled=amp_dtype is not None):
                    _, loss = model(x, y, loss_mask=m)
                losses.append(loss.item())
            per[name] = float(np.mean(losses))
        model.train()
        if isinstance(data, MixtureDataset):
            overall = float(sum(per[d] * w for d, w in data.weights.items() if d in per)
                            / max(1e-9, sum(w for d, w in data.weights.items() if d in per)))
            return overall, per
        return per["all"], {}

    # ---- main loop -----------------------------------------------------------
    def run(self) -> dict[str, Any]:
        with RunLock(self.run_dir, owner=self.cfg.run_name):
            return self._run()

    def _run(self) -> dict[str, Any]:
        cfg = self.cfg
        torch.manual_seed(cfg.seed)
        random.seed(cfg.seed)
        np.random.seed(cfg.seed)
        if self.device == "cuda" and cfg.gpu_memory_fraction:
            torch.cuda.set_per_process_memory_fraction(float(cfg.gpu_memory_fraction))
        if self.device == "cpu":
            from moth.training.resources import cpu_count
            torch.set_num_threads(min(cpu_count(), max(1, int(cfg.threads or max(1, cpu_count() - 1)))))
        if self.device == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True

        model = MothModel(self.model_cfg).to(self.device)
        model.gradient_checkpointing = cfg.gradient_checkpointing
        optimizer = model.configure_optimizer(cfg.lr, cfg.weight_decay, (cfg.beta1, cfg.beta2), self.device)
        amp_dtype, use_scaler = self._precision()
        scaler = torch.amp.GradScaler("cuda", enabled=use_scaler)
        data_gen = torch.Generator().manual_seed(cfg.seed)
        train = open_dataset(cfg.dataset, "train", cfg.seq_len, cfg.mixture)
        val = open_dataset(cfg.dataset, "val", cfg.seq_len, cfg.mixture)

        resumed_from = None
        last_train_loss = None
        last_val_loss = None
        had_progress = any((self.run_dir / "checkpoints").glob("step_*.pt*")) or (self.run_dir / "checkpoints" / "best.pt").exists()
        ckpt_path, ck = load_latest_verified(self.run_dir, self.device, self.emit)
        if ck is None and had_progress:
            raise ValueError("no valid resumable checkpoint remains; refusing to restart existing training from random weights")
        if ck is not None:
            if ck.get("tokenizer_fingerprint") and ck["tokenizer_fingerprint"] != self.tokenizer.fingerprint():
                raise ValueError("existing checkpoint uses a different tokenizer")
            if ck.get("dataset_build") and ck["dataset_build"] != self.dataset_meta.get("build_sha256"):
                raise ValueError("existing checkpoint uses a different dataset build; start a separate continuation run")
            if MothConfig.from_dict(ck["model_config"]).compatibility_key() != self.model_cfg.compatibility_key():
                raise ValueError("existing checkpoint in this run directory has a different architecture")
            model.load_state_dict(ck["model"])
            optimizer.load_state_dict(ck["optimizer"])
            if use_scaler and ck.get("scaler"):
                scaler.load_state_dict(ck["scaler"])
            self.step = ck["step"]
            self.best_val = ck.get("best_val", float("inf"))
            self.tokens_seen = ck.get("tokens_seen", 0)
            last_train_loss = ck.get("train_loss")
            last_val_loss = ck.get("val_loss")
            data_gen.set_state(ck["rng"]["data"].cpu())
            torch.set_rng_state(ck["rng"]["torch"].cpu())
            if self.device == "cuda" and ck["rng"].get("cuda") is not None:
                torch.cuda.set_rng_state_all([s.cpu() for s in ck["rng"]["cuda"]])
            resumed_from = str(ckpt_path)
        elif cfg.init_from:
            src = load_checkpoint(Path(cfg.init_from), self.device)
            src_cfg = src.get("model_config")
            if src_cfg and MothConfig.from_dict(src_cfg).compatibility_key() != self.model_cfg.compatibility_key():
                raise ValueError("init_from has a different architecture; architecture changes are migrations")
            if src.get("tokenizer_fingerprint") and src["tokenizer_fingerprint"] != self.tokenizer.fingerprint():
                raise ValueError("init_from was trained with a different tokenizer")
            model.load_state_dict(src.get("model", src))
            if cfg.init_optimizer and src.get("optimizer"):
                try:  # keep AdamW moments: continuing training should not start "cold"
                    optimizer.load_state_dict(src["optimizer"])
                except (ValueError, KeyError):
                    pass

        tuning = None
        if ck is not None and ck.get("batch_tuning"):
            tuning = ck["batch_tuning"]
            if tuning["effective_batch_size"] != cfg.batch_size * cfg.grad_accum:
                raise ValueError("resuming with a different effective batch size is not supported")
            cfg.batch_size, cfg.grad_accum = tuning["batch_size"], tuning["grad_accum"]
        elif cfg.batch_autotune:
            from moth.training.autotune import tune_batch

            def probe_sample(batch):
                return train.batch(batch, torch.Generator().manual_seed(cfg.seed), self.device)

            tuning = tune_batch(model, cfg.batch_size, cfg.grad_accum, probe_sample, self.device, amp_dtype,
                                seq_len=cfg.seq_len)
            cfg.batch_size, cfg.grad_accum = tuning["batch_size"], tuning["grad_accum"]

        self.emit("start", device=self.device, params=model.num_params(), model_config=self.model_cfg.to_dict(),
                  resumed_from=resumed_from, precision=str(amp_dtype or "fp32"),
                  train_tokens=len(train), val_tokens=len(val), batch_tuning=tuning)
        model.train()
        tokens_per_step = cfg.batch_size * cfg.grad_accum * train.seq_len
        t_last, tokens_since = time.time(), 0
        stop_reason = "completed"

        def checkpoint() -> None:
            save_checkpoint(self.run_dir, self.step, {
                "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "batch_tuning": tuning,
                "train_loss": last_train_loss, "val_loss": last_val_loss,
                "scaler": scaler.state_dict() if use_scaler else None,
                "step": self.step, "best_val": self.best_val, "tokens_seen": self.tokens_seen,
                "lineage": {**cfg.lineage,
                            "total_tokens": int(cfg.lineage.get("base_tokens", 0)) + self.tokens_seen,
                            "total_steps": int(cfg.lineage.get("base_steps", 0)) + self.step},
                "dataset_build": self.dataset_meta.get("build_sha256"),
                "model_config": self.model_cfg.to_dict(), "train_config": cfg.to_dict(),
                "tokenizer_fingerprint": self.tokenizer.fingerprint(),
                "tokenizer_path": self.dataset_meta["tokenizer_path"],
                "rng": {"data": data_gen.get_state(), "torch": torch.get_rng_state(),
                        "cuda": torch.cuda.get_rng_state_all() if self.device == "cuda" else None},
            }, keep=cfg.keep_checkpoints, keep_every=cfg.keep_every)
            self.emit("checkpoint", path=str(latest_checkpoint(self.run_dir)))

        try:
            while self.step < cfg.max_steps:
                if self.should_stop():
                    stop_reason = "stopped"
                    break
                t_step = time.time()
                lr = lr_at(self.step, cfg)
                for g in optimizer.param_groups:
                    g["lr"] = lr
                loss_acc = 0.0
                for _ in range(cfg.grad_accum):
                    x, y, m = train.batch(cfg.batch_size, data_gen, self.device)
                    with torch.autocast(self.device, dtype=amp_dtype, enabled=amp_dtype is not None):
                        _, loss = model(x, y, loss_mask=m)
                        loss = loss / cfg.grad_accum
                    if not torch.isfinite(loss):
                        raise FloatingPointError(f"non-finite loss at step {self.step}")
                    scaler.scale(loss).backward()
                    loss_acc += loss.item()
                scaler.unscale_(optimizer)
                grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip).item()
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                self.step += 1
                last_train_loss = loss_acc
                tokens_since += tokens_per_step
                self.tokens_seen += tokens_per_step

                if self.step % cfg.log_interval == 0 or self.step == 1:
                    dt = time.time() - t_last
                    self.emit("metrics", split="train", loss=loss_acc, lr=lr, grad_norm=grad_norm,
                              tokens_per_sec=tokens_since / dt if dt > 0 else 0.0, max_steps=cfg.max_steps)
                    t_last, tokens_since = time.time(), 0
                if self.step % cfg.eval_interval == 0 or self.step == cfg.max_steps:
                    vl, per_domain = self.evaluate_domains(model, val, amp_dtype)
                    last_val_loss = vl
                    improved = vl < self.best_val
                    self.best_val = min(self.best_val, vl)
                    self.emit("metrics", split="val", loss=vl, perplexity=math.exp(min(vl, 20)), best=improved,
                              domains=per_domain, tokens_seen=self.tokens_seen)
                    if improved:
                        checkpoint()  # the selected weights must keep their own optimizer/RNG state
                        shutil.copyfile(latest_checkpoint(self.run_dir), self.run_dir / "checkpoints" / "best.pt.tmp")
                        (self.run_dir / "checkpoints" / "best.pt.tmp").replace(self.run_dir / "checkpoints" / "best.pt")
                if self.step % cfg.checkpoint_interval == 0:
                    checkpoint()
                if cfg.duty_cycle < 1.0:  # throttle to respect user resource limits
                    busy = time.time() - t_step
                    time.sleep(busy * (1.0 / max(cfg.duty_cycle, 0.05) - 1.0))
        except Exception as e:
            stop_reason = "error"
            if isinstance(e, torch.cuda.OutOfMemoryError):
                msg = f"GPU out of memory: reduce batch_size/seq_len or enable gradient checkpointing ({e})"
            else:
                msg = f"{type(e).__name__}: {e}"
            self.emit("error", message=msg)
            raise
        finally:
            if self.step > 0 and stop_reason != "error":
                checkpoint()
            (self.run_dir / "STOP").unlink(missing_ok=True)
        self.emit("end", reason=stop_reason, best_val=self.best_val if self.best_val < float("inf") else None)
        return {"step": self.step, "reason": stop_reason, "best_val": self.best_val, "batch_tuning": tuning}
