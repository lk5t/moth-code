"""Community participant: trains on a coordinator-supplied public shard and uploads a weight delta.

Privacy: the only data used is the shard downloaded from the coordinator
(verified by checksum). The upload contains the weight delta and training
statistics — nothing from the user's files.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
import torch

from moth.community.protocol import PROTOCOL, ContributionMeta, JobSpec
from moth.community.resources import ParticipationSettings
from moth.community.validation import serialize_state, tensor_bytes_sha256
from moth.model.config import MothConfig
from moth.model.transformer import MothModel


class ContributionError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_train(model: MothModel, tokens: np.ndarray, spec, device: str, duty_cycle: float,
                should_stop: Callable[[], bool], on_step: Callable[[int, float], None], seed: int = 0) -> tuple[int, int]:
    gen = torch.Generator().manual_seed(seed)
    opt = model.configure_optimizer(spec.lr, spec.weight_decay, device_type=device)
    seq = min(spec.seq_len, model.cfg.max_seq_len, len(tokens) - 2)
    model.train()
    steps = trained_tokens = 0
    for step in range(spec.steps):
        if should_stop():
            break
        t0 = time.time()
        starts = torch.randint(0, len(tokens) - seq - 1, (spec.batch_size,), generator=gen).tolist()
        x = torch.from_numpy(np.stack([tokens[s : s + seq] for s in starts]).astype(np.int64)).to(device)
        y = torch.from_numpy(np.stack([tokens[s + 1 : s + seq + 1] for s in starts]).astype(np.int64)).to(device)
        _, loss = model(x, y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        steps += 1
        trained_tokens += x.numel()
        on_step(step + 1, loss.item())
        if duty_cycle < 1.0:
            time.sleep((time.time() - t0) * (1.0 / duty_cycle - 1.0))
    return steps, trained_tokens


@torch.no_grad()
def batch_loss(model: MothModel, tokens: np.ndarray, device: str, seq: int = 256, n: int = 4) -> float:
    model.eval()
    seq = min(seq, model.cfg.max_seq_len, (len(tokens) - 1) // n)
    x = torch.from_numpy(np.stack([tokens[i * seq : i * seq + seq] for i in range(n)]).astype(np.int64)).to(device)
    y = torch.from_numpy(np.stack([tokens[i * seq + 1 : i * seq + seq + 1] for i in range(n)]).astype(np.int64)).to(device)
    _, loss = model(x, y)
    model.train()
    return float(loss)


class CommunityClient:
    def __init__(self, settings: ParticipationSettings, client_id: str | None = None, http: httpx.Client | None = None):
        if not settings.coordinator_url and http is None:
            raise ContributionError("no coordinator configured")
        self.settings = settings
        self.client_id = client_id or uuid.uuid4().hex
        self.http = http or httpx.Client(base_url=settings.coordinator_url.rstrip("/"), timeout=120)

    def run_round(self, should_stop: Callable[[], bool] = lambda: False,
                  on_event: Callable[[dict[str, Any]], None] = lambda e: None) -> dict[str, Any]:
        from moth.training.trainer import pick_device

        job = JobSpec.from_dict(self._json("GET", f"/v1/jobs/next?client_id={self.client_id}"))
        if job.protocol != PROTOCOL:
            raise ContributionError(f"coordinator speaks {job.protocol}, this client speaks {PROTOCOL}")
        on_event({"kind": "status", "message": f"job {job.job_id}: round {job.round}, shard {job.shard_id}"})
        weights = self._bytes(f"/v1/models/{job.model_version}/weights")
        if _sha256(weights) != job.base_sha256:
            raise ContributionError("downloaded checkpoint failed checksum verification")
        shard = self._bytes(f"/v1/shards/{job.shard_id}")
        if _sha256(shard) != job.shard_sha256:
            raise ContributionError("downloaded data shard failed checksum verification")
        tokens = np.frombuffer(shard, dtype=np.uint32)

        device = pick_device(self.settings.device)
        if device == "cuda":
            torch.cuda.set_per_process_memory_fraction(self.settings.gpu_memory_fraction)
        cfg = MothConfig.from_dict(job.model_config)
        model = MothModel(cfg).to(device)
        import io

        base = torch.load(io.BytesIO(weights), map_location="cpu", weights_only=True)
        model.load_state_dict(base)
        held_out = tokens[-(4 * 257):] if len(tokens) > 4 * 257 * 4 else tokens
        loss_before = batch_loss(model, held_out, device)
        steps, n_tokens = local_train(model, tokens, job.train, device, self.settings.duty_cycle, should_stop,
                                      lambda s, l: on_event({"kind": "progress", "done": s, "total": job.train.steps,
                                                             "loss": l}))
        if steps == 0:
            raise ContributionError("stopped before any training step")
        loss_after = batch_loss(model, held_out, device)
        new = model.state_dict()
        delta = {k: (new[k].detach().cpu().float() - base[k].float()) for k in base}
        payload = serialize_state(delta)
        meta = ContributionMeta(job.job_id, job.round, self.client_id, job.base_sha256, tensor_bytes_sha256(payload),
                                n_tokens, steps, loss_before, loss_after)
        if not (math.isfinite(loss_before) and math.isfinite(loss_after)):
            raise ContributionError("training diverged (non-finite loss); nothing uploaded")
        on_event({"kind": "status", "message": f"uploading update ({len(payload) / 1e6:.1f} MB)"})
        r = self.http.post("/v1/contributions", content=payload,
                           headers={"x-moth-contribution": json.dumps(meta.to_dict()),
                                    "content-type": "application/octet-stream"})
        r.raise_for_status()
        result = r.json()
        return {"job": job.job_id, "round": job.round, "steps": steps, "tokens": n_tokens,
                "loss_before": loss_before, "loss_after": loss_after, **result}

    def info(self) -> dict[str, Any]:
        return self._json("GET", "/v1/info")

    def _json(self, method: str, path: str) -> dict[str, Any]:
        try:
            r = self.http.request(method, path)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise ContributionError(f"coordinator request failed: {e}") from None

    def _bytes(self, path: str) -> bytes:
        try:
            r = self.http.get(path)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ContributionError(f"download failed: {e}") from None
