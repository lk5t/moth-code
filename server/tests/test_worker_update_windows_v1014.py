"""1.0.14: worker self-updates work where symbolic links are not allowed (Windows without admin rights)."""
import os

from moth_worker import updater


def test_version_switch_uses_pointer_files_without_symlinks(tmp_path, monkeypatch):
    def no_symlinks(*a, **k):
        raise OSError("A required privilege is not held by the client")

    monkeypatch.setattr(os, "symlink", no_symlinks)
    home = tmp_path / "home"
    old, new = home / "versions" / "1.0.13", home / "versions" / "1.0.14"
    for d in (old, new):
        (d / "worker" / "moth_worker").mkdir(parents=True)
    updater._relink(home / "current", old)
    assert updater.code_dirs(home) == old
    updater._relink(home / "previous", updater._target(home / "current"))
    updater._relink(home / "current", new)
    assert updater.code_dirs(home) == new and updater._target(home / "previous") == old
