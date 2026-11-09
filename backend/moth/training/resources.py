"""Effective CPU/RAM capacity, including container quotas; native hosts fall back normally."""
import os
from pathlib import Path


def cpu_count() -> int:
    count = os.cpu_count() or 1
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            count = min(count, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return max(1, count)


def memory_budget(total: int, available: int) -> tuple[int, int]:
    try:
        cap = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if cap != 'max':
            total = min(total, int(cap))
            used = int(Path('/sys/fs/cgroup/memory.current').read_text())
            available = min(available, max(0, int(cap) - used))
    except (OSError, ValueError):
        pass
    return total, min(total, available)


def pressure() -> dict:
    """Optional OS sensors. Missing sensors stay unknown, never synthetic utilization."""
    out = {'temperature_c': None, 'on_battery': None, 'battery_percent': None}
    temperatures = []
    for path in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
        try:
            value = float(path.read_text()) / 1000
            if 0 < value < 150:
                temperatures.append(value)
        except (OSError, ValueError):
            pass
    if temperatures:
        out['temperature_c'] = max(temperatures)
    for battery in Path('/sys/class/power_supply').glob('*'):
        try:
            if (battery / 'type').read_text().strip() == 'Battery':
                out['on_battery'] = (battery / 'status').read_text().strip() == 'Discharging'
                out['battery_percent'] = float((battery / 'capacity').read_text())
                break
        except (OSError, ValueError):
            pass
    if os.name == 'nt':
        try:
            import ctypes
            class PowerStatus(ctypes.Structure):
                _fields_ = [('ac', ctypes.c_byte), ('flag', ctypes.c_byte), ('percent', ctypes.c_ubyte),
                            ('reserved', ctypes.c_byte), ('life', ctypes.c_uint32), ('full', ctypes.c_uint32)]
            status = PowerStatus()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                out['on_battery'] = status.ac == 0 if status.ac in (0, 1) else None
                out['battery_percent'] = status.percent if status.percent <= 100 else None
        except (OSError, AttributeError):
            pass
    return out


def pressure_reason(measured: dict) -> str | None:
    if (measured.get('temperature_c') or 0) >= 85:
        return 'Training paused: measured temperature is at least 85°C'
    if measured.get('on_battery') and (measured.get('battery_percent') is not None and measured['battery_percent'] <= 20):
        return 'Training paused: battery is at or below 20%'
    return None
