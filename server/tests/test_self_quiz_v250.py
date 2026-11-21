"""2.5: a model that gets almost nothing right quizzes itself less often; a new version is quizzed at once."""
from moth_server.intelligence import self_training as ST


def _last(correct, tried=40):
    return {"kinds": {"arithmetic": {"correct": correct, "tried": tried}, "language": {"correct": 0, "tried": tried}}}


def test_quiz_interval_follows_the_pass_rate():
    assert ST.interval_for(_last(0)) == 6 * ST.INTERVAL      # 0 %
    assert ST.interval_for(_last(12)) == 3 * ST.INTERVAL     # 15 %
    assert ST.interval_for(_last(30)) == ST.INTERVAL         # 37.5 %
    assert ST.interval_for({}) == ST.INTERVAL                # never quizzed
