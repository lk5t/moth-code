"""Hardware detection (NVIDIA GPUs via nvidia-smi and PyTorch, CPU, RAM, disk), a short benchmark,
and a privacy-preserving machine id.

CPU-only machines are fully supported workers (MOTH assigns them jobs that fit their memory); a GPU
is used when one with enough memory is present. The machine id is a salted SHA-256 of the operating
system's machine identifier, so MOTH Cloud can recognise the same computer enrolled twice without
learning anything about it.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
import uuid
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
        ram_gb = _windows_ram_gb()
    disk = shutil.disk_usage(Path.home())
    hw = {"gpus": gpus, "cuda": cuda, "torch": torch_version, "torch_cuda": torch_cuda,
          "cpu_count": os.cpu_count(), "cpu_model": cpu_model(), "ram_gb": ram_gb,
          "disk_free_gb": round(disk.free / 2**30, 1), "os": f"{platform.system()} {platform.release()}",
          "machine_id": machine_id()}
    hw["compute"] = compute_kind(hw)
    return hw


def _windows_ram_gb() -> float | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = MemStatus()
        m.dwLength = ctypes.sizeof(MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
        return round(m.ullTotalPhys / 2**30, 1)
    except Exception:  # noqa: BLE001
        return None


MIN_CPU_CORES = 2
MIN_RAM_GB = 3.0
MIN_DISK_GB = 5.0


def requirement_problem(hw: dict[str, Any], min_vram_gb: float = 8.0, allow_cpu: bool = True) -> str | None:
    """Why this machine cannot be a MOTH worker (None = it can). CPU-only machines are supported;
    ``allow_cpu`` is kept for compatibility with older command lines and no longer needed."""
    if (hw.get("cpu_count") or 0) < MIN_CPU_CORES:
        return f"MOTH Worker needs at least {MIN_CPU_CORES} CPU cores."
    if hw.get("ram_gb") is not None and hw["ram_gb"] < MIN_RAM_GB:
        return f"MOTH Worker needs at least {MIN_RAM_GB:g} GB of memory (this machine has {hw['ram_gb']} GB)."
    if hw.get("disk_free_gb") is not None and hw["disk_free_gb"] < MIN_DISK_GB:
        return f"MOTH Worker needs at least {MIN_DISK_GB:g} GB of free disk space."
    return None


def compute_kind(hw: dict[str, Any], min_vram_gb: float = 8.0) -> str:
    """"gpu" when a CUDA GPU with enough memory is usable, else "cpu"."""
    usable = [g for g in hw.get("gpus") or [] if (g.get("memory_gb") or 0) >= min_vram_gb]
    return "gpu" if usable and hw.get("torch_cuda") else "cpu"


def _raw_machine_id() -> str:
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            v = Path(p).read_text().strip()
            if v:
                return v
        except OSError:
            pass
    if sys.platform == "win32":
        try:
            out = subprocess.run(["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
                                 capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"MachineGuid\s+REG_SZ\s+(\S+)", out)
            if m:
                return m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True,
                                 timeout=10).stdout
            m = re.search(r'"IOPlatformUUID" = "([^"]+)"', out)
            if m:
                return m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return f"node-{uuid.getnode():x}"


def machine_id() -> str:
    """Salted hash of the OS machine id: identifies the computer, reveals nothing about it."""
    # MOTH_WORKER_INSTANCE: several workers on one big machine (e.g. one per GPU) are separate registrations
    inst = os.environ.get("MOTH_WORKER_INSTANCE", "")
    return hashlib.sha256(b"moth-worker-machine:" + _raw_machine_id().encode()
                          + (f":{inst}".encode() if inst else b"")).hexdigest()[:32]


def cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()[:80]
    except OSError:
        pass
    return (platform.processor() or None) and platform.processor()[:80]


def benchmark(device: str = "cpu", seconds: float = 1.5) -> dict[str, Any]:
    """Measured matrix-multiply throughput (GFLOP/s, float32) — what MOTH uses to balance jobs."""
    import torch

    n = 1024 if device == "cpu" else 4096
    a = torch.randn(n, n, device=device)
    b = torch.randn(n, n, device=device)
    (a @ b).sum().item()  # warm up
    runs, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        (a @ b).sum().item()
        runs += 1
    dt = time.perf_counter() - t0
    return {"device": device, "gflops": round(2 * n**3 * runs / dt / 1e9, 1), "threads": torch.get_num_threads(),
            "measured_at": int(time.time())}


def cached_benchmark(home: Path, device: str, max_age_s: float = 7 * 86400) -> dict[str, Any] | None:
    p = Path(home) / "benchmark.json"
    try:
        b = json.loads(p.read_text())
        if b.get("device") == device and time.time() - b.get("measured_at", 0) < max_age_s:
            return b
    except (OSError, ValueError):
        pass
    try:
        b = benchmark(device)
    except Exception:  # noqa: BLE001 — a benchmark failure never blocks the worker
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(b))
    except OSError:
        pass
    return b
