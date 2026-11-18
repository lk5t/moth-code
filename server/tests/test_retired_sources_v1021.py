"""1.0.21: general-reading sources are retired: removed from the approved set and not offered any more."""
from moth.datafactory.catalog import RETIRED
from moth_server.intelligence import discovery


def test_retired_sources_leave_the_approved_set_and_the_list(client, owner):
    ctx = client.app.state.ctx
    ctx.db.set_config(discovery.KEY, {**discovery.DEFAULTS, "approved_sources": ["mbpp", "tinystories", "fineweb-edu"]})
    assert discovery.policy(ctx)["approved_sources"] == ["mbpp"]
    assert ctx.db.get_config(discovery.KEY)["approved_sources"] == ["mbpp"]  # stored, not just hidden
    p = discovery.update(ctx, {"approved_sources": ["mbpp", "simple-wikipedia"]})
    assert p["approved_sources"] == ["mbpp"]
    listed = {s["id"] for s in discovery.status(ctx)["discovered"]}
    assert not (listed & RETIRED) and {"cve-cwe", "github-code-clean", "oasst2"} <= listed
