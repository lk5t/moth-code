"""Validation of exported MOTH model packages (the unit that is published to MOTH Cloud).

A package is a directory with ``manifest.json``, ``config.json``, ``tokenizer.json`` and
``model.pt``. ``inspect_package`` checks everything that can be checked without running the
model — files, metadata, checksum, architecture, tokenizer, tensor shapes — and returns clear
reasons for every problem. It is used by the desktop's *Validate* step before uploading and by
the server before a package is accepted. Running the model is the evaluation step's job
(``moth.model.evaluate``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_FILES = ("manifest.json", "config.json", "tokenizer.json", "model.pt")
ARCHITECTURE = "moth-decoder-v1"
SUPPORTED_FORMATS = (1,)
SUPPORTED_DTYPES = ("float16", "bfloat16", "float32")


def estimate_resources(params: int, file_size: int) -> dict[str, int]:
    """Rough serving requirements: weights are loaded as fp32 on CPU (fp16/bf16 on CUDA)."""
    return {"ram_cpu_bytes": int(params * 4 * 1.3 + 300 * 2**20), "vram_cuda_bytes": int(params * 2 * 1.3 + 200 * 2**20),
            "disk_bytes": int(file_size * 2)}


def inspect_package(model_dir: Path | str, deep: bool = True) -> dict[str, Any]:
    """Return ``{"ok": bool, "problems": [str], "info": {...}}``. ``deep`` also hashes the weights and
    compares tensor shapes with the architecture (reads the weight file once)."""
    d = Path(model_dir)
    problems: list[str] = []
    info: dict[str, Any] = {"path": str(d)}
    missing = [f for f in REQUIRED_FILES if not (d / f).is_file()]
    if missing:
        return {"ok": False, "problems": [f"missing required file(s): {', '.join(missing)} — export the model from a "
                                          "training run (Training → run → Export)"], "info": info}
    try:
        manifest = json.loads((d / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        return {"ok": False, "problems": [f"manifest.json is not valid JSON: {e}"], "info": info}
    info.update({k: manifest.get(k) for k in ("name", "architecture", "params", "dtype", "context_length",
                                              "tokenizer_fingerprint", "format", "sha256")})
    info["size"] = (d / "model.pt").stat().st_size
    info["training"] = manifest.get("training")
    for key in ("format", "architecture", "params", "dtype", "tokenizer_fingerprint", "sha256"):
        if manifest.get(key) in (None, ""):
            problems.append(f"manifest.json is missing '{key}'")
    if manifest.get("architecture") not in (None, ARCHITECTURE):
        problems.append(f"architecture '{manifest.get('architecture')}' is not supported — MOTH Cloud serves only "
                        f"MOTH models ({ARCHITECTURE})")
    if manifest.get("format") not in (None, *SUPPORTED_FORMATS):
        problems.append(f"package format {manifest.get('format')} is not supported by this version")
    if manifest.get("dtype") not in (None, *SUPPORTED_DTYPES):
        problems.append(f"weight dtype '{manifest.get('dtype')}' is not supported")
    try:
        from moth.model.config import MothConfig

        cfg = MothConfig.from_dict(json.loads((d / "config.json").read_text()))
        info["config"] = {"n_layers": cfg.n_layers, "d_model": cfg.d_model, "n_heads": cfg.n_heads,
                          "vocab_size": cfg.vocab_size, "max_seq_len": cfg.max_seq_len}
        if manifest.get("params") and cfg.num_params() != manifest["params"]:
            problems.append(f"config.json describes {cfg.num_params():,} parameters but the manifest says "
                            f"{manifest['params']:,}")
        if manifest.get("context_length") and cfg.max_seq_len != manifest["context_length"]:
            problems.append("config.json context length does not match the manifest")
    except Exception as e:  # noqa: BLE001
        cfg = None
        problems.append(f"config.json is not a valid MOTH model configuration: {e}")
    try:
        from moth.model.tokenizer import Tokenizer

        tok = Tokenizer.load(d / "tokenizer.json")
        info["tokenizer"] = {"vocab_size": tok.vocab_size, "fingerprint": tok.fingerprint()}
        if manifest.get("tokenizer_fingerprint") and tok.fingerprint() != manifest["tokenizer_fingerprint"]:
            problems.append("tokenizer.json does not match the tokenizer the model was trained with "
                            "(fingerprint mismatch)")
        if cfg is not None and tok.vocab_size > cfg.vocab_size:
            problems.append(f"tokenizer has {tok.vocab_size} tokens but the model only has {cfg.vocab_size} embeddings")
    except Exception as e:  # noqa: BLE001
        problems.append(f"tokenizer.json could not be loaded: {e}")
    if deep and not problems:
        from moth.model.registry import sha256_file

        if sha256_file(d / "model.pt") != manifest["sha256"]:
            problems.append("model.pt is corrupted or was modified (SHA-256 does not match the manifest)")
        elif cfg is not None:
            problems += _check_shapes(d / "model.pt", cfg)
    info["resources"] = estimate_resources(int(manifest.get("params") or 0), info["size"])
    return {"ok": not problems, "problems": problems, "info": info}


def _check_shapes(weights: Path, cfg) -> list[str]:
    import torch

    from moth.model.transformer import MothModel

    try:
        state = torch.load(weights, map_location="cpu", weights_only=True)
    except Exception as e:  # noqa: BLE001
        return [f"model.pt could not be read as MOTH weights: {e}"]
    with torch.device("meta"):
        expected = {k: tuple(v.shape) for k, v in MothModel(cfg).state_dict().items()}
    got = {k: tuple(v.shape) for k, v in state.items()}
    problems = []
    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    if missing:
        problems.append(f"weights are missing {len(missing)} tensor(s) of the architecture (e.g. {missing[0]})")
    if extra:
        problems.append(f"weights contain {len(extra)} tensor(s) the architecture does not have (e.g. {extra[0]})")
    wrong = [k for k in set(expected) & set(got) if expected[k] != got[k]]
    if wrong:
        k = sorted(wrong)[0]
        problems.append(f"{len(wrong)} tensor(s) have the wrong shape for this configuration (e.g. {k}: "
                        f"{got[k]} instead of {expected[k]})")
    bad = [k for k, v in state.items() if v.is_floating_point() and not torch.isfinite(v.float()).all()]
    if bad:
        problems.append(f"{len(bad)} weight tensor(s) contain NaN or infinite values (e.g. {bad[0]})")
    return problems
