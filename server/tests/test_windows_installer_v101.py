"""1.0.1: the Windows worker installer must work in Windows PowerShell 5.1 (the default shell)."""
from pathlib import Path

PS1 = Path(__file__).resolve().parents[2] / "worker" / "install.ps1"


def test_installer_is_ascii_so_powershell_51_reads_it_correctly():
    PS1.read_bytes().decode("ascii")  # 5.1 reads BOM-less files as ANSI: "▲" became "â–²"


def test_native_stderr_cannot_abort_the_install():
    text = PS1.read_text()
    assert '$ErrorActionPreference = "Continue"' in text
    assert '$ErrorActionPreference = "Stop"' not in text
    assert '"import torch" 2>$null' not in text  # the probe that aborted 1.0.1 on a fresh machine
    assert "find_spec('torch')" in text


def test_nvidia_gpu_detection_joins_nvidia_smi_lines():
    """1.0.4: '-match' on nvidia-smi's list of lines never set $Matches, so every NVIDIA GPU was missed."""
    text = PS1.read_text()
    assert '(& $e 2>$null) -join' in text and "Win32_VideoController" in text
    assert "torch.version.cuda" in text  # a CPU-only PyTorch from an earlier install is replaced
