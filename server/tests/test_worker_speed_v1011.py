"""1.0.11: a worker is never starved by one stalled job's near-zero speed reading."""
from moth_server.evolution import compute as C
from test_network_v063 import _enroll


def test_near_zero_reading_is_dropped_and_the_worker_is_placed_again(client, owner):
    ctx = client.app.state.ctx
    w = _enroll(client, owner, gflops=50)
    C.record_throughput(ctx, "local:cpu", 30_000, 1)
    C.record_throughput(ctx, f"worker:{w['worker_id']}", 1, 600)  # a take-back before any progress
    assert f"worker:{w['worker_id']}" not in C.throughput(ctx)
    me = next(x for x in C.worker_speeds(ctx) if x["id"] == w["worker_id"])
    assert me["ratio"] > 0 and not me["basis"].startswith("measured")
