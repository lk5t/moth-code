"""0.10.0: successors are sized by measured speed, read a longer context, are compared fairly across
tokenizers, are not rejected merely for being bigger, and are trained by MOTH Cloud and the workers
together."""
import json
import time

import pytest
from sqlalchemy import select

from conftest import H
from moth_server import models as M
from moth_server.db import training_jobs
from moth_server.evolution import compute as C, engine as EN, evaluation as EV, memory as MEM
from test_evolution import drive
from test_network_v063 import _enroll, _world


def test_per_byte_scores_compare_tokenizers_fairly():
    scores = {"capability:holdout:conversation": {"ok": True, "value": 2.0, "bits_per_byte": 1.1},
              "capability:holdout:code": {"ok": True, "value": 1.5},  # scored before 0.10.0
              "capability:math:gsm": {"ok": True, "value": 0.2, "higher_is_better": True}}
    out = EV.per_byte(scores)
    assert out["capability:holdout:conversation"]["value"] == 1.1
    assert not out["capability:holdout:code"]["ok"]           # never compared in the wrong unit
    assert out["capability:math:gsm"] == scores["capability:math:gsm"]  # accuracy is already text-level
    assert EV._memory_limit() > 0


def test_holdout_suite_measures_bits_per_byte(tmp_path):
    from moth.model.capabilities import holdout_suite
    from moth.model.config import MothConfig
    from moth.model.tokenizer import Tokenizer
    from moth.model.transformer import MothModel

    tok = Tokenizer([])
    model = MothModel(MothConfig.from_dict({"vocab_size": 512, "d_model": 32, "n_layers": 1, "n_heads": 2,
                                            "n_kv_heads": 2, "ffn_hidden": 64, "max_seq_len": 128})).eval()
    p = tmp_path / "h.jsonl"
    p.write_text("\n".join(json.dumps({"text": "the quick brown fox jumps over the lazy dog " * 2}) for _ in range(5)))
    r = holdout_suite(model, tok, str(p))
    # one byte per token: bits per byte is the token loss in bits
    assert r["bytes"] > 0 and abs(r["bits_per_byte"] - r["value"] / 0.6931471805599453) < 1e-6


def test_speed_probe_measures_a_shape():
    from moth.training.speed_probe import measure

    tps = measure({"vocab_size": 512, "d_model": 32, "n_layers": 1, "n_heads": 2, "n_kv_heads": 2,
                   "ffn_hidden": 64, "max_seq_len": 256}, 128)
    assert tps > 0


@pytest.mark.timeout(1500)
def test_successor_is_trained_by_the_workers_together(client, owner, tmp_path, monkeypatch):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    from moth_server.evolution import v2 as V2
    from test_evolution import FAST

    monkeypatch.setattr(V2, "REBIRTH_MAX_HOURS", 1e-6)
    monkeypatch.setattr(V2, "REBIRTH_MIN_STEPS", 8)
    ctx = _world(client, owner, tmp_path, monkeypatch, training={**FAST["training"], "steps": 8},
                 backends={"local_cpu": False, "local_gpu": False, "workers": True},
                 distributed={"min_participants": 2, "rounds": 1}, budget={"max_cycle_hours": 2.0},
                 growth={"enabled": True})
    ws = [_enroll(client, owner), _enroll(client, owner)]
    C.record_throughput(ctx, "local:cpu", 50_000, 1)
    cyc = drive(ctx, lambda c: any((e["config"] or {}).get("rebirth") and e["backend"] == "distributed"
                                   for e in MEM.experiments(ctx, c["id"])) or c["status"] in MEM.TERMINAL_CYCLE,
                timeout=200)
    exp = next(e for e in MEM.experiments(ctx, cyc["id"]) if (e["config"] or {}).get("rebirth"))
    assert exp["backend"] == "distributed", exp["error"]
    st = exp["resources"]["distributed"]
    assert st["started_from"] == "successor_init"
    phases = [p["phase"] for p in exp["config"]["mixture_schedule"]]
    if exp["config"]["rebirth"]["grows_exactly"]:
        # 2.5: grown from the current model (it already chats): the normal run schedule, continued-training rate
        assert phases == ["curriculum", "chat finish"]
        from moth_server.evolution import settings as S
        assert exp["config"]["lr"] == float(S.get(ctx)["training"]["lr"]) and not exp["config"].get("short_context")
    else:  # 0.10.1: a fresh successor gets a chat warm-up first, chat-heavy finish last
        assert phases == ["chat warm-up", "curriculum", "chat finish"]
    arch = exp["config"]["rebirth"]["architecture"]
    jobs = ctx.db.all(select(training_jobs).where(training_jobs.c.kind == "dist_shard"))
    assert len(jobs) == 2 and all(json.loads(j["spec"])["model_config"]["d_model"] == arch["d_model"] for j in jobs)
    runners = [(w, WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / f"w{i}",
                                allow_cpu=True, log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None))
               for i, w in enumerate(ws)]
    deadline = time.time() + 900
    while time.time() < deadline:  # the workers take every job of the cycle, as they would online
        EN.tick(ctx)
        for w, r in runners:
            r.beat()
            resp = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"]))
            job = resp.json() if resp.status_code == 200 else None
            if job and job.get("kind"):
                r.run_job(job)
        if MEM.cycles(ctx, 1)[0]["status"] in MEM.TERMINAL_CYCLE:
            break
        time.sleep(0.3)
    exp = MEM.experiment(ctx, exp["id"])
    assert exp["candidate_version"], exp["error"]
    cand = M.release(ctx, exp["candidate_version"])
    cfg = cand["info"].get("config") or {}
    assert cfg["d_model"] == arch["d_model"] and cfg["max_seq_len"] == 2048
    assert cand["info"]["params"] == exp["config"]["rebirth"]["params_after"]
    gates = {g["gate"]: g for g in (exp["metrics"] or {}).get("gates", [])}
    if "speed" in gates:  # a bigger model is held to an absolute speed, not "as fast as the tiny one"
        assert "bigger model" in gates["speed"]["detail"]


@pytest.mark.timeout(1500)
def test_successor_with_its_own_tokenizer_is_judged_per_byte(client, owner, tmp_path, monkeypatch):
    """A byte-level lineage's successor trains on data prepared with a new BPE tokenizer and is compared
    with the current model in bits per byte of the same held-out text."""
    from moth_server.evolution import capacity as _CAP
    monkeypatch.setattr(_CAP, "BPE_MIN_PARAMS", 0)  # 2.1: tiny test models switch to BPE at once
    monkeypatch.setattr(_CAP, "GROWTH_STEP", 1000.0)
    from moth_server.evolution import settings as S, v2 as V2
    from moth_server.intelligence import library
    from test_evolution_v053 import _world as world053

    ctx, base_v = world053(client, owner, tmp_path, monkeypatch)
    monkeypatch.setattr(V2, "REBIRTH_MAX_HOURS", 1e-6)
    monkeypatch.setattr(V2, "REBIRTH_MIN_STEPS", 30)
    S.update(ctx, {"training": {"steps": 20}, "budget": {"max_cycle_hours": 2.0}, "max_experiments_per_cycle": 1})
    monkeypatch.setattr(library, "byte_level", lambda release: True)  # treat the test lineage as byte-level
    ctx.db.set_config("library_last_config", {"sources": ["tiny"], "holdout_fraction": 0.05, "holdout_overrides": {},
                                              "near_dedupe": False, "automatic": True})  # the last automatic build's
    assert library.ensure_successor_tokenizer(ctx) is not None or library.successor_tokenizer(ctx)
    deadline = time.time() + 300
    while library.successor_tokenizer(ctx) is None and time.time() < deadline:
        time.sleep(0.5)
    tok = library.successor_tokenizer(ctx)
    assert tok and tok["fingerprint"] != M.release(ctx, base_v)["info"]["tokenizer_fingerprint"]
    C.record_throughput(ctx, "local:cpu", 50_000, 1)
    from moth_server.evolution import capacity as CAP

    base = M.release(ctx, base_v)
    rs = CAP.right_size(ctx, base, S.get(ctx))
    assert rs and rs["tokenizer"]["fingerprint"] == tok["fingerprint"] and rs["architecture"]["vocab_size"] >= tok["vocab_size"]
    # a cycle planned before the tokenizer was ready has no successor; the next one does
    cyc = drive(ctx, lambda c: any((e["config"] or {}).get("rebirth") for e in MEM.experiments(ctx, c["id"])), timeout=600)
    succ = next(e for e in MEM.experiments(ctx, cyc["id"]) if (e["config"] or {}).get("rebirth"))
    assert succ["config"]["rebirth"]["tokenizer"]["fingerprint"] == tok["fingerprint"]
    assert succ["config"]["mixture"]["build_id"] == tok["build_id"]  # trained on its own tokenizer's data
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=900)
    succ = MEM.experiment(ctx, succ["id"])
    assert succ["candidate_version"], succ["error"]
    cand = M.release(ctx, succ["candidate_version"])
    assert cand["info"]["tokenizer_fingerprint"] == tok["fingerprint"]
    gates = {g["gate"]: g for g in (succ["metrics"] or {}).get("gates", [])}
    assert gates["same_text_comparison"]["passed"]
    holdout = [g for k, g in gates.items() if k.startswith("capability:holdout:") and g.get("change") is not None]
    assert holdout  # measured for both models, in bits per byte
