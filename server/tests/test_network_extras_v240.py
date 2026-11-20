"""2.4: the weekly leaderboard, the public phone status page and "Report a problem"."""
import json
import time

from sqlalchemy import insert

from conftest import H, register_verified
from moth_server.db import evolution_experiments as EX, training_jobs as TJ, workers as W


def _worker(c, wid, uid, kind="personal"):
    c.execute(insert(W).values(id=wid, user_id=uid, name=f"w{wid}", token_hash=f"t{wid}", status="online",
                               hardware=json.dumps({"worker_kind": kind}), limits="{}", enrolled_at=time.time(),
                               last_heartbeat_at=time.time()))


def test_leaderboard_ranks_people_and_leaves_out_moth_cloud(client, owner, settings):
    bob = register_verified(client, settings, username="bob")
    ctx = client.app.state.ctx
    bob_id = client.get("/v1/me", headers=H(bob["token"])).json()["id"]
    t = time.time()
    with ctx.db.tx() as c:
        _worker(c, 301, 1)
        _worker(c, 302, bob_id)
        _worker(c, 303, 1, kind="cloud")
        for i, (wid, n) in enumerate([(301, 1), (302, 3), (303, 9)]):
            for k in range(n):
                c.execute(insert(TJ).values(kind="dist_shard", status="completed", spec="{}", worker_id=wid,
                                            created_at=t, updated_at=t))
        c.execute(insert(EX).values(id=990, cycle_id=1, status="completed", config="{}", config_hash="h", dataset_id=1,
                                    base_version=1, base_sha256="x", worker_id=302, compute_seconds=7200.0,
                                    created_at=t, updated_at=t, finished_at=t))
    r = client.get("/v1/intelligence/leaderboard", headers=H(owner["token"])).json()
    assert [(x["username"], x["jobs"]) for x in r["top"]] == [("bob", 3), ("LK5T", 1)]  # cloud's 9 jobs not counted
    assert r["top"][0]["hours"] == 2.0 and r["you"]["username"] == "LK5T" and r["you"]["rank"] == 2


def test_status_page_is_public_plain_and_refreshes(client):
    r = client.get("/status")
    assert r.status_code == 200 and "MOTH status" in r.text and r.headers["refresh"] == "30"
    assert "Computers helping" in r.text and "script" not in r.text.lower()


def test_problem_reports_reach_only_the_owner(client, owner, settings):
    bob = register_verified(client, settings, username="bob")
    r = client.post("/v1/problem-reports", headers=H(bob["token"]), json={"message": "chat froze", "app_version": "2.4.0",
                                                                        "details": {"logs": ["line 1", "line 2"]}})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get("/v1/admin/problem-reports", headers=H(bob["token"])).status_code == 403
    lst = client.get("/v1/admin/problem-reports", headers=H(owner["token"])).json()
    assert lst[0]["message"] == "chat froze" and lst[0]["username"] == "bob"
    full = client.get(f"/v1/admin/problem-reports/{rid}", headers=H(owner["token"])).json()
    assert full["details"]["logs"] == ["line 1", "line 2"]
    assert client.get("/v1/admin/problem-reports/..%2F..%2Fx", headers=H(owner["token"])).status_code == 404
    big = client.post("/v1/problem-reports", headers=H(bob["token"]), json={"message": "x", "details": {"logs": "a" * 500_000}})
    assert big.status_code == 413
