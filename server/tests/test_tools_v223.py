"""2.2.3: MOTH Cloud installs Node.js (for the JavaScript exam) into its data directory, checksum-verified."""
import hashlib
import io
import os
import tarfile

import pytest

from moth_server import tools


def _archive(name: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        data = b"#!/bin/sh\necho v22\n"
        info = tarfile.TarInfo(f"{name}/bin/node")
        info.size, info.mode = len(data), 0o755
        tf.addfile(info, io.BytesIO(data))
        js = tarfile.TarInfo(f"{name}/lib/node_modules/corepack/dist/corepack.js")
        js.size = 2
        tf.addfile(js, io.BytesIO(b"//"))
        link = tarfile.TarInfo(f"{name}/bin/corepack")  # 2.5: Node's own relative link (refused in production)
        link.type, link.linkname = tarfile.SYMTYPE, "../lib/node_modules/corepack/dist/corepack.js"
        tf.addfile(link)
    return buf.getvalue()


@pytest.fixture
def ctx(client, monkeypatch):
    c = client.app.state.ctx
    monkeypatch.setattr(tools, "_arch", lambda: "x64")
    monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tools.shutil, "which", lambda name, path=None: next(
        (os.path.join(d, name) for d in os.environ["PATH"].split(os.pathsep) if os.path.isfile(os.path.join(d, name))), None))
    monkeypatch.setenv("PATH", "/nonexistent")
    return c


def test_installs_a_verified_node_and_puts_it_on_path(ctx):
    name = tools.node_home(ctx).name
    blob = _archive(name)
    sums = f"{hashlib.sha256(blob).hexdigest()}  {name}.tar.xz\nabc  other.tar.xz\n".encode()
    urls = []

    def get(url):
        urls.append(url)
        return sums if url.endswith("SHASUMS256.txt") else blob

    r = tools.ensure_node(ctx, http_get=get)
    assert r["status"] == "installed" and r["node"].endswith("/bin/node")
    assert all(u.startswith("https://nodejs.org/dist/") for u in urls)
    assert str(tools.node_home(ctx) / "bin") in os.environ["PATH"]
    assert tools.ensure_node(ctx, http_get=get)["status"] == "present"  # no second download
    assert (tools.node_home(ctx) / "bin" / "corepack").read_text() == "//"


@pytest.mark.parametrize("name,link", [("n/bin/x", "../../../etc/passwd"), ("n/bin/x", "/etc/passwd"), ("../x", None),
                                       ("/abs", None)])
def test_archives_escaping_their_folder_are_refused(name, link):
    m = tarfile.TarInfo(name)
    if link:
        m.type, m.linkname = tarfile.SYMTYPE, link
    with pytest.raises(RuntimeError):
        tools.check_members([m])


def test_a_tampered_download_is_refused(ctx):
    name = tools.node_home(ctx).name
    sums = f"{'0' * 64}  {name}.tar.xz\n".encode()
    r = tools.ensure_node(ctx, http_get=lambda url: sums if url.endswith(".txt") else _archive(name))
    assert r["status"] == "failed" and "checksum mismatch" in r["reason"]
    assert not (tools.node_home(ctx) / "bin" / "node").exists()


def test_tests_and_background_off_never_download(ctx):
    assert tools.ensure_node(ctx)["status"] == "skipped"
