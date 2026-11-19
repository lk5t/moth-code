"""2.0: chat search with snippets, and files/folders dropped into chat."""
import time

from test_server import H, client


def test_message_search_returns_snippets_and_titles(paths):
    with client(paths) as c:
        db = c.app.state.services.db
        a = db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (NULL,'Docker help',?)", (time.time(),)).lastrowid
        b = db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (NULL,'Other',?)", (time.time(),)).lastrowid
        db.execute("INSERT INTO messages(conversation_id, role, content, ts) VALUES (?,?,?,?)",
                   (b, "assistant", "x " * 80 + "use a parameterised query to stop SQL injection " + "y " * 80, time.time()))
        hits = c.get("/api/search/messages?q=sql%20injection", headers=H()).json()
        assert [h["conversation_id"] for h in hits] == [b]
        assert "SQL injection" in hits[0]["snippet"] and hits[0]["snippet"].startswith("…") and len(hits[0]["snippet"]) < 200
        assert c.get("/api/search/messages?q=docker", headers=H()).json()[0]["conversation_id"] == a
        assert c.get("/api/search/messages?q=x", headers=H()).json() == []  # too short


def test_dropped_files_and_folders_skip_secrets_and_binaries(paths, tmp_path):
    d = tmp_path / "proj"
    (d / "src").mkdir(parents=True)
    (d / "src" / "app.py").write_text("print('hi')\n")
    (d / ".env").write_text("TOKEN=secret\n")
    (d / "id_rsa").write_text("-----BEGIN KEY-----\n")
    (d / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (d / "node_modules").mkdir()
    (d / "node_modules" / "dep.js").write_text("x")
    single = tmp_path / "notes.md"
    single.write_text("# notes\n")
    with client(paths) as c:
        r = c.post("/api/attachments/read", headers=H(), json={"paths": [str(d), str(single), str(tmp_path / "nope")]}).json()
    names = sorted(f["path"].replace("\\", "/") for f in r["files"])
    assert names == ["notes.md", "proj/src/app.py"]
    reasons = {s["path"].replace("\\", "/"): s["reason"] for s in r["skipped"]}
    assert "secret" in reasons["proj/id_rsa"] and "text" in reasons["proj/logo.png"] and "not found" in next(v for k, v in reasons.items() if k.endswith("nope"))
    assert not any("TOKEN=secret" in f["content"] for f in r["files"])  # .env is a hidden file: never walked or read
    assert not any("dep.js" in f["path"] for f in r["files"])


def test_dropped_folder_has_limits(paths, tmp_path):
    from moth.workspace import attachments as A
    d = tmp_path / "many"
    d.mkdir()
    for i in range(A.MAX_FILES + 5):
        (d / f"f{i:03}.txt").write_text("a" * 100)
    big = tmp_path / "big.txt"
    big.write_text("b" * (A.MAX_FILE_BYTES + 500))
    r = A.read([str(big), str(d)])
    assert len(r["files"]) == A.MAX_FILES and r["files"][0]["truncated"] and len(r["files"][0]["content"]) == A.MAX_FILE_BYTES
    assert any(s["reason"] == "limit reached" for s in r["skipped"])
