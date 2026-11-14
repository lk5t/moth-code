"""1.0 GitHub connection: the token never lands in git config or output."""
import subprocess

import pytest

from moth.workspace import github as GH


def test_token_is_sent_as_a_one_off_header_and_never_stored(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        class P:
            returncode = 1
            stdout = ""
            stderr = "fatal: could not read from https://github.com with secret-token-123"
        return P()
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GH.GitHubError) as e:
        GH.clone("secret-token-123", "owner/repo", tmp_path)
    assert "secret-token-123" not in str(e.value) and "***" in str(e.value)
    assert any(a.startswith("http.https://github.com/.extraHeader=Authorization: Basic ") for a in seen["args"])
    assert "https://github.com/owner/repo.git" in seen["args"]  # clean URL: no token in the remote


def test_rejects_bad_repo_names_and_missing_token(tmp_path):
    with pytest.raises(GH.GitHubError):
        GH.clone("t", "../etc/passwd", tmp_path)
    with pytest.raises(GH.GitHubError, match="Connect GitHub"):
        GH.user("")
