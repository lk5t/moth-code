"""0.9.0: MOTH quizzes itself on new, automatically checked problems and learns from the results."""
from moth_server.evolution import memory as MEM
from moth_server.intelligence import self_training as ST
from test_serving_v053 import _two_releases


def test_answer_checks():
    assert ST.correct("It is 4230", "94 × 45 = 4230. The answer is 4230.")
    assert not ST.correct("It is 4231", "94 × 45 = 4230. The answer is 4230.")
    assert ST.correct("The youngest is Ben.", "Putting them in order: Ada, Cleo, Ben. The youngest is Ben.")
    assert not ST.correct("The youngest is Ada.", "Putting them in order: Ada, Cleo, Ben. The youngest is Ben.")
    assert ST.correct("lantern, moth, orbit, river, window", "lantern, moth, orbit, river, window")
    assert not ST.correct("", "orbit orbit orbit")


def test_a_self_quiz_keeps_verified_answers_and_corrections(client, owner, tmp_path, monkeypatch):
    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    answers = iter(["The answer is 4230."] + ["no idea"] * 1000)
    monkeypatch.setattr(ST, "_ask", lambda engine, q, t: next(answers))
    from moth.datafactory import synthetic

    monkeypatch.setitem(synthetic.GENERATORS, "arithmetic", lambda rng: ("94 × 45 = ?", "94 × 45 = 4230. The answer is 4230."))
    r = ST.run_round(ctx, per_kind=3, samples=1, seed=7)
    assert r["kinds"]["arithmetic"] == {"tried": 3, "correct": 1, "rate": 0.333}
    assert r["verified"] == 1 and r["corrections"] == 11
    recs = ST.records(ctx)
    assert len(recs) == 12
    good = next(x for x in recs if x["source"] == "self-verified")
    assert good["messages"][1]["content"] == "The answer is 4230."  # MOTH's own (checked) words
    fix = next(x for x in recs if x["source"] == "self-corrections")
    assert fix["messages"][1]["content"] != "no idea"  # the generator's checked answer, never the mistake
    assert ST.weakness_scores(ctx)["math"] == 0.667
    assert any(e["kind"] == "self.quiz" for e in MEM.events(ctx, 5))
    from moth_server.intelligence import weakness

    rows = {r["capability"]: r for r in weakness.analyse(ctx, None)["capabilities"]}
    assert rows["math"]["source"] == "self-quiz" and rows["math"]["weakness"] == 0.667


def test_no_model_no_quiz(client, owner):
    ctx = client.app.state.ctx
    ctx.extras.pop("inference_engine", None)
    assert ST.run_round(ctx) is None and not ST.maybe_run(ctx)
