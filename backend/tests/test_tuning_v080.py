"""0.8.0: serving performance is measured; a thread setting is kept only when faster with identical output."""
import torch

from moth.inference import tuning as T


class FakeEngine:
    """Speed depends on threads; output depends on threads only when ``unstable``."""

    def __init__(self, fast_threads: int, unstable: bool = False):
        self.fast, self.unstable = fast_threads, unstable

    def complete(self, prompt, params):
        import time

        from moth.model.generation import GenerationStats

        n = torch.get_num_threads()
        time.sleep(0.002 if n == self.fast else 0.02)
        s = GenerationStats()
        s.generated_tokens = params.max_new_tokens
        return ("same" if not self.unstable or n == torch.get_num_threads() and n != self.fast else f"t{n}"), s


def test_faster_setting_with_identical_output_is_kept():
    before = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        r = T.profile(FakeEngine(fast_threads=1), "cpu", tokens=8)
        assert r["tuned"] and r["threads"] == 1 and torch.get_num_threads() == 1 and r["gain"] > 0.1
    finally:
        torch.set_num_threads(before)


def test_setting_that_changes_output_is_never_kept():
    before = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        r = T.profile(FakeEngine(fast_threads=1, unstable=True), "cpu", tokens=8)
        assert not r["tuned"] and torch.get_num_threads() == 2  # restored
        assert "1" in r["tried"]  # it was measured, just not kept
    finally:
        torch.set_num_threads(before)
