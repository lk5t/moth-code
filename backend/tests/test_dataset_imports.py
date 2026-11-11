import json
import sys
from types import SimpleNamespace
import pytest
from moth.training.sources import SourceSpec, iter_source
from moth.training.data import prepare_dataset, TokenDataset
from moth.training.trainer import Trainer
from test_training import cfg


@pytest.mark.parametrize('form', ['txt', 'pairs', 'messages'])
def test_real_uploaded_conversations_produce_tokens_and_train(tmp_path, tiny_pipeline, form):
    source = tmp_path / 'upload'
    source.mkdir()
    records = []
    for i in range(120):
        prompt = f'Explain the concept number {i} in everyday language.'
        answer = f'Example {i}: ' + 'Clear explanations use concrete examples and careful reasoning. ' * 10
        records.append({'prompt': prompt, 'answer': answer} if form == 'pairs' else
                       {'messages': [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': answer}]})
    if form == 'txt':
        (source / 'conversation.txt').write_text('\n'.join(f'Text example {i}: ' + 'Plain text is valid training input. ' * 20 for i in range(120)), encoding='utf-8')
    else:
        (source / 'conversation.jsonl').write_text('\n'.join(map(json.dumps, records)), encoding='utf-8')
    destination = tmp_path / 'imported'
    meta = prepare_dataset([{'spec': f'dir:{source}', 'license': 'CC0-1.0'}], tiny_pipeline['tokenizer'], tiny_pipeline['tokenizer_path'], destination)
    assert meta['tokens']['train'] > 1000 and meta['tokens']['val'] > 32
    assert meta['tokenizer_fingerprint'] == tiny_pipeline['tokenizer'].fingerprint()
    pipeline = {**tiny_pipeline, 'dataset': destination}
    trainer = Trainer(cfg(pipeline, tmp_path / 'run', max_steps=3, checkpoint_interval=1, eval_interval=3, eval_iters=1))
    trainer.run()
    assert trainer.step == 3 and trainer.tokens_seen > 0
    assert list((tmp_path / 'run').rglob('*.pt'))


def test_large_txt_not_silently_skipped_and_invalid_jsonl_is_actionable(tmp_path):
    (tmp_path / 'large.txt').write_text('valid UTF-8 words ' * 70000)
    assert sum(len(d.text) for d in iter_source(SourceSpec(f'dir:{tmp_path}', license='CC0'))) > 1_000_000
    bad = tmp_path / 'bad.jsonl'
    bad.write_text('{broken JSON')
    with pytest.raises(ValueError, match='bad.jsonl: line 1: malformed JSON'):
        list(iter_source(SourceSpec(f'jsonl:{bad}', license='CC0')))


def test_hub_access_error_names_source_without_leaking_credentials(monkeypatch):
    def denied(*args, **kwargs):
        error = RuntimeError('Bearer secret-value-in-upstream-error')
        error.response = SimpleNamespace(status_code=403)
        raise error
    monkeypatch.setitem(sys.modules, 'datasets', SimpleNamespace(load_dataset=denied))
    with pytest.raises(RuntimeError) as caught:
        list(iter_source(SourceSpec('hf:example/gated', license='MIT')))
    assert 'example/gated' in str(caught.value) and 'Accept the dataset terms' in str(caught.value)
    assert 'secret-value' not in str(caught.value)


def test_gated_catalog_source_reported_as_gated_not_missing(monkeypatch):
    """Reproduced against Hugging Face: an unsigned request for a gated dataset answers "not found",
    which made preparing every catalog source at once fail with a misleading message."""
    class DatasetNotFoundError(Exception):
        pass

    def missing(*args, **kwargs):
        raise DatasetNotFoundError('hidden upstream text')
    monkeypatch.setitem(sys.modules, 'datasets', SimpleNamespace(load_dataset=missing))
    monkeypatch.delenv('HF_TOKEN', raising=False)
    monkeypatch.delenv('HUGGING_FACE_HUB_TOKEN', raising=False)
    monkeypatch.setattr('moth.training.sources._hf_signed_in', lambda: False)
    with pytest.raises(RuntimeError) as caught:
        list(iter_source(SourceSpec('hf:bigcode/the-stack-smol', license='x')))
    text = str(caught.value)
    assert 'bigcode/the-stack-smol' in text and 'gated' in text and 'HF_TOKEN' in text and 'remove this source' in text
    monkeypatch.setattr('moth.training.sources._hf_signed_in', lambda: True)
    with pytest.raises(RuntimeError, match='unavailable; check the selected source'):
        list(iter_source(SourceSpec('hf:example/typo', license='MIT')))
