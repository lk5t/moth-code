"""1.0 usage page: daily token totals."""
from conftest import H


def test_usage_daily_lists_every_day(client, owner):
    r = client.get("/v1/billing/usage-daily?days=7", headers=H(owner["token"]))
    assert r.status_code == 200
    days = r.json()
    assert len(days) == 7 and all(d["tokens"] == 0 for d in days) and days[-1]["day"] > days[0]["day"]
