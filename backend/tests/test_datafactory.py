"""Data Factory: verified downloads, cleaning, dedupe, decontamination, reproducibility, curriculum, mixtures."""

import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from moth.datafactory import build, catalog, clean, fetch
from moth.datafactory.curriculum import plan_mixture
from moth.model.tokenizer import train_bpe
from moth.training.data import MixtureDataset
from moth.training.trainer import Trainer, TrainConfig

STORY = ("Once upon a time there was a little cat named Tom. Tom liked to play in the garden with his red ball. "
         "One day the ball rolled under a big tree and Tom was sad. His friend the bird helped him find it. ")


class FakeHTTP:
    """Serves bytes for URLs; can cut a download short once to exercise resume."""

    def __init__(self, files: dict[str, bytes], cut_once: int | None = None):
        self.files, self.cut_once, self.calls = files, cut_once, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append((url, req.get_header("Range")))
        data = self.files[url]
        start = 0
        rng = req.get_header("Range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
        body = data[start:]
        if self.cut_once:
            body, self.cut_once = body[: self.cut_once], None
        r = io.BytesIO(body)
        r.status = 206 if start else 200
        r.__enter__ = lambda *a: r
        r.__exit__ = lambda *a: None
        return _Ctx(r)


class _Ctx:
    def __init__(self, r):
        self.r, self.status = r, r.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.r.read(n)


def _src(files):
    return {"id": "t", "repo": "test/repo", "revision": "a" * 40, "format": "stories", "license": "MIT",
            "license_url": "", "attribution": "", "name": "T", "domain": "language", "description": "",
            "files": files}


def test_download_once_resume_and_reject_tampering(tmp_path):
    data = b"hello world\n" * 5000
    f = {"path": "x.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "role": "train"}
    src = _src([f])
    http = FakeHTTP({catalog.file_url(src, f): data}, cut_once=1000)
    p = fetch.fetch_file(tmp_path, src, f, opener=http)
    assert p.read_bytes() == data
    assert any(r for _, r in http.calls)  # the cut download resumed with a Range request
    n = len(http.calls)
    fetch.fetch_file(tmp_path, src, f, opener=http)
    assert len(http.calls) == n  # verified before: reused, never downloaded again
    # a file whose bytes do not match the pinned SHA-256 is deleted, never used
    bad = {**f, "path": "y.txt", "sha256": "0" * 64}
    http.files[catalog.file_url(src, bad)] = data
    with pytest.raises(fetch.FetchError, match="SHA-256"):
        fetch.fetch_file(tmp_path, src, bad, opener=http)
    assert not fetch.local_path(tmp_path, src, bad).exists()


def test_oversized_response_cannot_exceed_download_budget(tmp_path):
    http = FakeHTTP({'https://example.test/data': b'x' * 100000})
    target = tmp_path / 'download'
    with pytest.raises(fetch.FetchError, match='exceeds its pinned size'):
        fetch._download('https://example.test/data', target, 64, opener=http)
    assert target.with_name('download.part').stat().st_size == 65
    assert not target.exists()


def test_cleaning_quality_and_pii():
    code, count = build._clean_record({"domain": "code", "text": 'token = "ghp_' + 'A' * 32 + '"\n# email a@example.com'})
    assert count == 2 and 'ghp_' not in code['text'] and 'a@example.com' not in code['text']
    text, n = clean.scrub("Mail me at jane.doe@example.com or call 555-123-4567. Key sk-abcdefghijklmnop1234")
    assert "[email]" in text and "[phone]" in text and "[secret]" in text and n == 3
    assert clean.normalize("a\x00b  \n\n\n\nc\r\n") == "ab\n\nc"
    good, why = clean.quality({"domain": "language", "text": STORY})
    assert why is None and good > 0.6
    assert clean.quality({"domain": "language", "text": "buy now " * 80})[1] == "repetitive"
    assert clean.quality({"domain": "code", "text": "x=1;" * 200 + "\n" * 3 + "y"})[1] == "minified"
    assert clean.quality({"domain": "conversation", "messages": [{"role": "user", "content": "Capital of France?"},
                                                                  {"role": "assistant", "content": "Paris."}]})[1] is None


def test_dedupe_and_decontamination():
    d = clean.Deduper()
    long = STORY + " ".join(f"Then Tom walked to place number {i} and counted {i * 3} leaves." for i in range(30))
    assert d.check(long) is None
    assert d.check(long.upper()) == "exact"  # normalised text matches
    near = long.replace("red ball", "blue ball")  # one changed word in ~400: a near duplicate
    assert d.check(near) == "near"
    assert d.check("A completely different text about rockets, planets and the long journey to Mars. " * 3) is None
    q = "Janet has three ducks that lay sixteen eggs per day and she eats three of them for breakfast every morning"
    decon = clean.Decontaminator([q])
    assert decon.contaminated("Problem: " + q + " How many are left?")
    assert not decon.contaminated(STORY)


def _tiny_catalog(tmp_path, monkeypatch):
    stories = "".join(f"{STORY} Story number {i} ends with word{i} and a smile.\n<|endoftext|>\n" for i in range(120))
    data = stories.encode()
    f = {"path": "s.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "role": "train"}
    src = _src([f])
    monkeypatch.setattr(catalog, "SOURCES", [src])
    return src, FakeHTTP({catalog.file_url(src, f): data})


def test_build_is_reproducible_and_records_provenance(tmp_path, monkeypatch):
    src, http = _tiny_catalog(tmp_path, monkeypatch)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", http)
    cfg = {"sources": ["t"], "holdout_fraction": 0.1, "holdout_overrides": {}}
    m1 = build.build(tmp_path / "cache", tmp_path / "b1", cfg, log=lambda m: None)
    m2 = build.build(tmp_path / "cache", tmp_path / "b2", cfg, log=lambda m: None)
    assert m1["content_sha256"] == m2["content_sha256"]  # same pins + config → identical corpus
    st = m1["sources"][0]["stats"]
    assert st["read"] == 120 and st["kept"] + st["holdout"] + st.get("near_duplicate", 0) + st.get("duplicate", 0) == 120
    assert m1["sources"][0]["files"][0]["sha256"] == src["files"][0]["sha256"]
    assert "MIT" in (tmp_path / "b1" / "ATTRIBUTION.md").read_text()
    # holdout records never appear in training data
    held = {json.loads(l)["uid"] for l in (tmp_path / "b1" / "eval" / "holdout_language.jsonl").open()}
    train = {json.loads(l)["uid"] for l in (tmp_path / "b1" / "domains" / "language.jsonl").open()}
    assert held and train and not held & train


def test_curriculum_caps_epochs_and_follows_weakness():
    toks = {"language": 10_000_000, "reasoning": 100_000, "code": 20_000_000, "math": 1_000_000}
    p = plan_mixture(toks, 20_000_000, "foundation", max_epochs=4)
    assert abs(sum(p["weights"].values()) - 1) < 1e-3
    assert p["expected_epochs"]["reasoning"] <= 4.01  # small domain not memorised
    w = plan_mixture(toks, 20_000_000, "balanced", weakness={"code": 1.0})
    base = plan_mixture(toks, 20_000_000, "balanced")
    assert w["weights"]["code"] > base["weights"]["code"]


def test_mixture_training_reports_capability_losses(tmp_path, monkeypatch):
    src, http = _tiny_catalog(tmp_path, monkeypatch)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", http)
    b = tmp_path / "b"
    build.build(tmp_path / "cache", b, {"sources": ["t"], "holdout_fraction": 0.1, "holdout_overrides": {}},
                log=lambda m: None)
    tok = train_bpe(build.iter_texts(b), 400)
    tok.save(tmp_path / "tok.json")
    mix = build.tokenize_build(b, tok, tmp_path / "tok.json", log=lambda m: None)
    assert mix["domains"]["language"]["tokens"]["train"] > 1000
    ds = MixtureDataset(b / "tokens", "train", 32, {"language": 1.0})
    assert ds.weights == {"language": 1.0}
    events = []
    cfg = TrainConfig(dataset=str(b / "tokens"), out_dir=str(tmp_path / "run"), preset="moth-tiny", seq_len=32,
                      batch_size=2, grad_accum=1, max_steps=4, warmup_steps=1, eval_interval=2, eval_iters=2,
                      checkpoint_interval=2, device="cpu", mixture={"language": 1.0})
    Trainer(cfg, on_event=events.append).run()
    vals = [e for e in events if e["kind"] == "metrics" and e.get("split") == "val"]
    assert vals and "language" in vals[-1]["domains"]
