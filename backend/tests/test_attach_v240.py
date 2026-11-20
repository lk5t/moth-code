"""2.4: screenshots/photos (kept locally, text read by the OS), GitHub links, editing and branching chats."""
import base64
import io
import subprocess
import sys
import tarfile
import time

import pytest

from test_server import H, client

PNG = base64.b64decode(  # a 1×1 PNG
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_an_image_is_kept_and_served_and_bad_data_is_refused(paths, monkeypatch):
    from moth.workspace import chat_attach as CA
    monkeypatch.setattr(CA, "read_text", lambda p: {"text": "Traceback: KeyError 'value'", "engine": "test", "note": None})
    with client(paths) as c:
        r = c.post("/api/attachments/image", headers=H(), json={"name": "shot.png", "data_base64": "data:image/png;base64," + base64.b64encode(PNG).decode()})
        assert r.status_code == 200, r.text
        img = r.json()
        assert img["text"].startswith("Traceback") and img["id"].endswith(".png") and img["size"] == len(PNG)
        got = c.get(f"/api/attachments/image/{img['id']}", headers=H())
        assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
        assert c.get("/api/attachments/image/..%2F..%2Fmoth.db", headers=H()).status_code == 404
        assert c.post("/api/attachments/image", headers=H(), json={"name": "x.png", "data_base64": base64.b64encode(b"not an image").decode()}).status_code == 422
        assert c.post("/api/attachments/image", headers=H(), json={"name": "x.png", "data_base64": "%%%"}).status_code == 422


def test_text_reading_never_fails_without_an_engine(tmp_path, monkeypatch):
    from moth.workspace import chat_attach as CA
    p = tmp_path / "a.png"
    p.write_bytes(PNG)
    monkeypatch.setattr(CA.sys, "platform", "linux")
    monkeypatch.setattr(CA.shutil, "which", lambda name: None)
    r = CA.read_text(p)
    assert r["text"] == "" and r["engine"] is None and "Tesseract" in r["note"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows text recognition exists only on Windows")
def test_windows_reads_text_in_a_screenshot(tmp_path):
    from moth.workspace import chat_attach as CA
    p = tmp_path / "shot.png"
    draw = ("Add-Type -AssemblyName System.Drawing; $b = New-Object Drawing.Bitmap 900,160; $g = [Drawing.Graphics]::FromImage($b); "
            "$g.Clear([Drawing.Color]::White); $f = New-Object Drawing.Font('Arial', 48); "
            "$g.DrawString('HELLO MOTH 42', $f, [Drawing.Brushes]::Black, 10, 30); "
            f"$b.Save('{p}', [Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", draw], check=True, timeout=60)
    r = CA.read_text(p)
    if r["engine"] == "windows":
        assert "HELLO" in r["text"].upper() and "42" in r["text"]
    else:  # a Windows without a recognition language: an honest reason, never a crash
        assert r["text"] == "" and r["note"]


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(f"repo-abc123/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("repo-abc123/escape")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(link)
    return buf.getvalue()


def test_github_links(monkeypatch):
    from moth.workspace import chat_attach as CA
    assert CA.parse_github("https://github.com/o/r") == {"kind": "tree", "owner": "o", "repo": "r", "ref": "HEAD", "path": ""}
    assert CA.parse_github("https://github.com/o/r.git")["repo"] == "r"
    assert CA.parse_github("https://github.com/o/r/tree/main/src/app")["path"] == "src/app"
    assert CA.parse_github("https://github.com/o/r/blob/main/a/b.py#L3") == {"kind": "file", "owner": "o", "repo": "r", "ref": "main", "path": "a/b.py"}
    assert CA.parse_github("https://raw.githubusercontent.com/o/r/main/x.md")["kind"] == "file"
    with pytest.raises(CA.AttachError):
        CA.parse_github("https://example.com/o/r")
    archive = _tarball({"src/app.py": b"print('hi')\n", "src/.env": b"TOKEN=secret", "src/id_rsa": b"KEY",
                        "node_modules/x.js": b"x", "logo.png": b"\x89PNG\x00\x00", "README.md": b"# r\n"})
    calls = []

    def fake_get(url, token, limit):
        calls.append(url)
        return archive if "codeload" in url else b"def f():\n    return 1\n"
    monkeypatch.setattr(CA, "_get", fake_get)
    whole = CA.fetch_github("https://github.com/o/r")
    assert sorted(f["path"] for f in whole["files"]) == ["r/README.md", "r/src/app.py"]
    assert any("secret" in s["reason"] for s in whole["skipped"])
    assert calls[-1] == "https://codeload.github.com/o/r/tar.gz/HEAD"
    sub = CA.fetch_github("https://github.com/o/r/tree/main/src")
    assert [f["path"] for f in sub["files"]] == ["r/src/app.py"]
    one = CA.fetch_github("https://github.com/o/r/blob/main/lib/f.py")
    assert one["files"][0]["content"].startswith("def f") and calls[-1].startswith("https://raw.githubusercontent.com/o/r/main/lib/f.py")
    assert CA.fetch_github("https://github.com/o/r/blob/main/.env")["skipped"][0]["reason"].startswith("looks like a secret")


def test_edit_and_branch_a_chat(paths):
    with client(paths) as c:
        db = c.app.state.services.db
        cid = db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (NULL,'Sorting',?)", (time.time(),)).lastrowid
        ids = [db.execute("INSERT INTO messages(conversation_id, role, content, ts) VALUES (?,?,?,?)", (cid, role, text, time.time())).lastrowid
               for role, text in [("user", "sort a list"), ("assistant", "use sorted()"), ("user", "in reverse?"), ("assistant", "reverse=True")]]
        b = c.post(f"/api/conversations/{cid}/branch", headers=H(), json={"message_id": ids[1]}).json()
        branched = c.get(f"/api/conversations/{b['conversation_id']}/messages", headers=H()).json()
        assert [m["content"] for m in branched] == ["sort a list", "use sorted()"] and b["title"] == "Branch of Sorting"
        assert len(c.get(f"/api/conversations/{cid}/messages", headers=H()).json()) == 4  # the original is unchanged
        assert c.post(f"/api/conversations/{cid}/truncate", headers=H(), json={"message_id": ids[1]}).status_code == 422  # not yours
        r = c.post(f"/api/conversations/{cid}/truncate", headers=H(), json={"message_id": ids[2]}).json()
        assert r["removed"] == 2
        assert [m["content"] for m in c.get(f"/api/conversations/{cid}/messages", headers=H()).json()] == ["sort a list", "use sorted()"]
        assert c.post(f"/api/conversations/{cid}/branch", headers=H(), json={"message_id": 99999}).status_code == 404


def test_dropped_image_paths(paths, tmp_path, monkeypatch):
    from moth.workspace import chat_attach as CA
    monkeypatch.setattr(CA, "read_text", lambda p: {"text": "", "engine": None, "note": "no engine"})
    (tmp_path / "s.png").write_bytes(PNG)
    with client(paths) as c:
        r = c.post("/api/attachments/image-path", headers=H(), json={"paths": [str(tmp_path / "s.png"), str(tmp_path / "gone.png")]}).json()
    assert [i["name"] for i in r["images"]] == ["s.png"] and r["images"][0]["note"] == "no engine"
    assert r["skipped"][0]["reason"] == "not found"
