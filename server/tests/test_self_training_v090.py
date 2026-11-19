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
    monkeypatch.setattr(ST, "_ask", lambda engine, q, t, max_new=96: next(answers))
    from moth.datafactory import synthetic

    monkeypatch.setitem(synthetic.GENERATORS, "arithmetic", lambda rng: ("94 × 45 = ?", "94 × 45 = 4230. The answer is 4230."))
    r = ST.run_round(ctx, per_kind=3, samples=1, seed=7)
    assert r["kinds"]["arithmetic"] == {"tried": 3, "correct": 1, "rate": 0.333}
    # 2.1: 3 problems each in 4 checked kinds and 3 code kinds (wrong code answers become corrections too)
    assert r["verified"] == 1 and r["corrections"] == 20
    assert {r["kinds"][k]["tried"] for k in ("python_code", "sql")} == {3}
    recs = ST.records(ctx)
    assert len(recs) == 21
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


def test_code_answers_count_only_when_they_run(client, owner, tmp_path, monkeypatch):
    """2.1: a SQL answer is kept as self-verified only if SQLite returns the right rows."""
    from moth.datafactory import multilang

    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    monkeypatch.setattr(ST, "KINDS", {})
    monkeypatch.setattr(ST, "CODE_KINDS", ("sql",))
    calls = {"n": 0}

    def ask(engine, q, t, max_new=96):
        calls["n"] += 1
        return "```sql\nSELECT 1\n```" if calls["n"] % 2 else "I don't know"
    monkeypatch.setattr(ST, "_ask", ask)
    real = multilang.sql_quiz
    monkeypatch.setitem(multilang.QUIZZES, "sql", lambda rng: (lambda q: (q[0], q[1], lambda a: "SELECT 1" in a))(real(rng)))
    r = ST.run_round(ctx, per_kind=4, samples=1, seed=3)
    assert r["kinds"]["sql"]["tried"] == 4 and r["kinds"]["sql"]["correct"] == 2
    recs = [x for x in ST.records(ctx) if x["kind"] == "sql"]
    assert {x["source"] for x in recs} == {"self-verified", "self-corrections"}
    assert all("```sql" in x["messages"][1]["content"] for x in recs)  # corrections carry the checked query
