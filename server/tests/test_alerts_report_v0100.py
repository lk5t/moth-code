"""0.10.0: desktop alerts feed and the morning report."""
from conftest import H
from moth_server.evolution import memory as MEM


def test_alerts_feed_only_returns_news_after_the_first_look(client, owner):
    ctx = client.app.state.ctx
    MEM.event(ctx, "deploy.done", "an old promotion")
    first = client.get("/v1/admin/evolution/alerts?after=0", headers=H(owner["token"])).json()
    assert first["alerts"] == [] and first["latest"] > 0 and first["status"]  # a fresh app replays nothing
    MEM.event(ctx, "deploy.done", "MOTH 0.0.5 is live")
    MEM.event(ctx, "experiment.planned", "not news")
    MEM.event(ctx, "supervisor.attention", "the pipeline stopped three times")
    r = client.get(f"/v1/admin/evolution/alerts?after={first['latest']}", headers=H(owner["token"])).json()
    assert [(a["tone"], a["message"]) for a in r["alerts"]] == [("promoted", "MOTH 0.0.5 is live"),
                                                                ("problem", "the pipeline stopped three times")]


def test_morning_report_summarises_the_night(client, owner):
    ctx = client.app.state.ctx
    MEM.event(ctx, "deploy.done", "promoted")
    MEM.event(ctx, "supervisor.repaired", "restarted the pipeline")
    r = client.get("/v1/admin/evolution/morning-report", headers=H(owner["token"])).json()
    assert r["promotions"] == 1 and any("new brain" in h for h in r["highlights"])
    assert any("Fixed 1 problem" in h for h in r["highlights"])
    assert client.get("/v1/admin/evolution/morning-report").status_code in (401, 403)
