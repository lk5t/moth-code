"""0.6.2 conversation management: rename, delete one, delete selected, clear all, retention."""
import time

from test_server import H, client


def _seed(c, n=3):
    db = c.app.state.services.db
    ids = []
    for i in range(n):
        cid = db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (NULL,?,?)", (f"chat {i}", time.time())).lastrowid
        db.execute("INSERT INTO messages(conversation_id, role, content, ts) VALUES (?,?,?,?)", (cid, "user", f"hello {i}", time.time()))
        ids.append(int(cid))
    return db, ids


def test_rename_and_delete_one(paths):
    with client(paths) as c:
        db, ids = _seed(c, 2)
        r = c.patch(f"/api/conversations/{ids[0]}", headers=H(), json={"title": "  Refactor   plan "})
        assert r.status_code == 200 and r.json()["title"] == "Refactor plan"
        assert c.patch(f"/api/conversations/{ids[0]}", headers=H(), json={"title": "   "}).status_code == 422
        assert c.patch("/api/conversations/99999", headers=H(), json={"title": "x"}).status_code == 404
        assert c.delete(f"/api/conversations/{ids[0]}", headers=H()).json()["deleted"] == [ids[0]]
        assert not db.query("SELECT * FROM messages WHERE conversation_id=?", (ids[0],))  # messages removed too
        assert c.delete(f"/api/conversations/{ids[0]}", headers=H()).status_code == 404
        assert [x["id"] for x in c.get("/api/conversations", headers=H()).json()] == [ids[1]]


def test_delete_selected_reports_missing(paths):
    with client(paths) as c:
        db, ids = _seed(c, 3)
        r = c.post("/api/conversations/delete", headers=H(), json={"ids": [ids[0], ids[2], 4242]}).json()
        assert sorted(r["deleted"]) == sorted([ids[0], ids[2]]) and r["missing"] == [4242] and r["failed"] == []
        assert [x["id"] for x in c.get("/api/conversations", headers=H()).json()] == [ids[1]]
        assert c.post("/api/conversations/delete", headers=H(), json={"ids": []}).status_code == 422


def test_clear_all_needs_confirmation_and_persists(paths):
    with client(paths) as c:
        db, ids = _seed(c, 3)
        assert c.post("/api/conversations/delete", headers=H(), json={"all": True}).status_code == 422
        assert len(c.get("/api/conversations", headers=H()).json()) == 3  # nothing deleted without the phrase
        r = c.post("/api/conversations/delete", headers=H(), json={"all": True, "confirm": "DELETE ALL"}).json()
        assert sorted(r["deleted"]) == sorted(ids)
    with client(paths) as c:  # after a restart
        assert c.get("/api/conversations", headers=H()).json() == []
        assert not c.app.state.services.db.query("SELECT * FROM messages")


def test_retention_is_off_by_default_and_keeps_recent(paths):
    with client(paths) as c:
        db, ids = _seed(c, 2)
        old = time.time() - 40 * 86400
        db.execute("UPDATE conversations SET created_at=? WHERE id=?", (old, ids[0]))
        db.execute("UPDATE messages SET ts=? WHERE conversation_id=?", (old, ids[0]))
        assert c.post("/api/conversations/retention/apply", headers=H()).json()["deleted"] == 0
        assert c.put("/api/settings", headers=H(), json={"chat_retention_days": -1}).status_code == 422
        c.put("/api/settings", headers=H(), json={"chat_retention_days": 30})
        assert c.post("/api/conversations/retention/apply", headers=H()).json()["deleted"] == 1
        assert [x["id"] for x in c.get("/api/conversations", headers=H()).json()] == [ids[1]]
