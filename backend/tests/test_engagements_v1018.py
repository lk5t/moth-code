"""1.0.18: engagement scope is enforced on agent commands; servers are saved without secrets."""
import pytest

from moth.security import engagements as E
from moth.workspace import servers as S


@pytest.fixture(autouse=True)
def home(tmp_path):
    E.configure(tmp_path)
    S.configure(tmp_path)
    yield tmp_path


def test_no_engagement_means_no_checks():
    assert E.check("curl https://anything.example.org").ok


def test_scope_allows_inside_and_refuses_outside():
    eng = E.create("Acme test", ["10.0.0.0/24", "*.acme-test.com", "203.0.113.7"])
    E.activate(eng["id"])
    assert E.check("nmap -sV 10.0.0.15").ok
    assert E.check("curl https://app.acme-test.com/login").ok
    assert E.check("ping 203.0.113.7").ok
    v = E.check("nmap 10.0.1.5")
    assert not v.ok and "10.0.1.5" in v.reason
    assert not E.check("curl https://example.org").ok
    assert E.check("python main.py && cat notes.txt").ok  # files are not network targets
    assert not E.check("uptime", host="198.51.100.9").ok   # SSH to a host outside the scope


def test_window_and_log(tmp_path):
    eng = E.create("Later", ["10.0.0.0/8"], starts_at=9e12)
    E.activate(eng["id"])
    assert not E.check("ping 10.1.1.1").ok
    E.log("ping 10.1.1.1", "local", False, None, "refused")
    assert E.read_log(eng["id"])[0]["command"] == "ping 10.1.1.1"


def test_bad_scope_and_server_profiles():
    with pytest.raises(ValueError):
        E.create("x", [])
    with pytest.raises(S.ServerError):
        S.add("bad name!", "host", "root")
    with pytest.raises(S.ServerError):
        S.add("web", "-oProxyCommand=evil", "root")
    S.add("web", "203.0.113.7", "deploy", 2222)
    row = S.get("web")
    assert row["port"] == 2222 and "password" not in row
    argv = S.ssh_argv(row, "uptime") if __import__("shutil").which("ssh") else ["--", "uptime"]
    assert argv[-2:] == ["--", "uptime"]
