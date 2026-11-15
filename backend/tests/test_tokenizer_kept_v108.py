"""1.0.8: prepared data keeps working after model retention removes the model folder its tokenizer was in."""
import json

from moth.training.data import dataset_meta


def test_missing_recorded_tokenizer_falls_back_to_the_copy_kept_with_the_data(tmp_path):
    d = tmp_path / "mix"
    d.mkdir()
    (d / "mixture.json").write_text(json.dumps({"tokenizer_path": str(tmp_path / "models/v00134/tokenizer.json"),
                                                "tokenizer_fingerprint": "f", "domains": {}}))
    assert dataset_meta(d)["tokenizer_path"].endswith("v00134/tokenizer.json")  # nothing better to offer
    (d / "tokenizer.json").write_text("{}")
    assert dataset_meta(d)["tokenizer_path"] == str(d / "tokenizer.json")
