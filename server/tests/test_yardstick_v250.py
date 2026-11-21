"""2.5: the yardstick is frozen the first time and never changes, even when the library's held-out files do."""
import json

from moth_server.evolution import evaluation as EV


def test_yardstick_is_frozen(client, tmp_path):
    ctx = client.app.state.ctx
    d = tmp_path / "eval"
    d.mkdir()
    (d / "holdout_code.jsonl").write_text("\n".join(json.dumps({"text": f"def f{i}(): return {i}"}) for i in range(50)))
    (d / "holdout_conversation.jsonl").write_text(json.dumps({"text": "User: hi\nMOTH: hello"}))
    f = EV.yardstick(ctx, d)
    first = f.read_bytes()
    rows = [json.loads(x) for x in first.decode().splitlines()]
    assert {r["domain"] for r in rows} == {"code", "conversation"}
    (d / "holdout_code.jsonl").write_text(json.dumps({"text": "something else entirely"}))  # the library is rebuilt
    assert EV.yardstick(ctx, d).read_bytes() == first          # the yardstick is not
    assert ctx.db.get_config("yardstick")["rows"] == len(rows)
    assert EV.yardstick(ctx, None) == f                        # and survives a missing library


def test_no_yardstick_without_held_out_text(client, tmp_path):
    assert EV.yardstick(client.app.state.ctx, tmp_path) is None
