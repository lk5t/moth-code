"""Hardware detection (NVIDIA GPUs via nvidia-smi and PyTorch, CPU, RAM, disk)."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _nvidia_smi() -> tuple[list[dict[str, Any]], str | None]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return [], None
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20)
        header = subprocess.run([exe], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [], None
    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            gpus.append({"name": parts[0], "memory_gb": round(float(parts[1]) / 1024, 1),
                         "memory_used_gb": round(float(parts[2]) / 1024, 1),
                         "utilization": float(parts[3]) if parts[3].replace(".", "").isdigit() else None,
                         "driver": parts[4]})
    m = re.search(r"CUDA Version:\s*([\d.]+)", header)
    return gpus, m.group(1) if m else None


def detect() -> dict[str, Any]:
    gpus, cuda = _nvidia_smi()
    torch_version = None
    torch_cuda = False
    try:
        import torch

        torch_version = torch.__version__
        torch_cuda = torch.cuda.is_available()
        if torch_cuda and not gpus:
            for i in range(torch.cuda.device_count()):
                p = torch.cuda.get_device_properties(i)
                gpus.append({"name": p.name, "memory_gb": round(p.total_memory / 2**30, 1), "driver": None})
    except Exception:  # noqa: BLE001 - torch missing or broken driver
        pass
    ram_gb = None
    try:
        ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        pass
    disk = shutil.disk_usage(Path.home())
    return {"gpus": gpus, "cuda": cuda, "torch": torch_version, "torch_cuda": torch_cuda,
            "cpu_count": os.cpu_count(), "ram_gb": ram_gb, "disk_free_gb": round(disk.free / 2**30, 1),
            "os": f"{platform.system()} {platform.release()}"}


def requirement_problem(hw: dict[str, Any], min_vram_gb: float = 8.0, allow_cpu: bool = False) -> str | None:
    if allow_cpu:
        return None
    if not hw["gpus"]:
        return "No NVIDIA GPU detected (nvidia-smi not found or no devices). MOTH Worker needs an NVIDIA GPU."
    best = max(g["memory_gb"] for g in hw["gpus"])
    if best < min_vram_gb:
        return f"The largest GPU has {best} GB of memory; at least {min_vram_gb} GB is required."
    if not hw["torch_cuda"]:
        return "PyTorch cannot use the GPU (CUDA build of PyTorch missing or driver too old)."
    return None
