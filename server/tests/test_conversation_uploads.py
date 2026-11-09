import json
import pytest
from conftest import H
from moth_server import models as M
from moth_server.evolution import datasets as DS
from moth.training.data import TokenDataset


@pytest.mark.parametrize('form', ['txt', 'pairs', 'messages'])
def test_upload_register_approve_with_deployed_tokenizer(client, owner, tiny_model_dir, form):
    ctx = client.app.state.ctx
    model = M._register(ctx, tiny_model_dir, 'import baseline', {'type': 'upload'}, None)
    M._set(ctx, model['version'], 'published')
    M.deploy(ctx, model['version'])
    rows = []
    for n in range(300):
        prompt, answer = f'Question {n}', f'Answer {n}: ' + 'Learning from approved conversation data requires clear answers. ' * 20
        rows.append({'prompt': prompt, 'answer': answer} if form == 'pairs' else
                    {'messages': [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': answer}]})
    raw = ('\n'.join(f'Conversation {n}: ' + 'Plain UTF-8 text can be used for training. ' * 30 for n in range(300))
           if form == 'txt' else '\n'.join(map(json.dumps, rows)))
    name = 'conversations.txt' if form == 'txt' else 'conversations.jsonl'
    response = client.post('/v1/admin/evolution/datasets', headers=H(owner['token']),
        data={'name': form, 'license': 'CC0-1.0', 'contains_user_data': 'true'},
        files={'file': (name, raw.encode(), 'text/plain')})
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset['tokenizer_fingerprint'] == model['info']['tokenizer_fingerprint']
    assert dataset['tokens_train'] > 1000 and dataset['tokens_val'] >= 300
    assert dataset['status'] == 'pending'
    path = f"/v1/admin/evolution/datasets/{dataset['id']}/approve"
    assert client.post(path, headers=H(owner['token']), json={}).status_code != 200
    assert client.post(path, headers=H(owner['token']), json={'user_data_permission': True}).status_code == 200
    prepared = DS.get(ctx, dataset['id'])
    assert len(TokenDataset(prepared['path'], 'train', 32)) > 0
