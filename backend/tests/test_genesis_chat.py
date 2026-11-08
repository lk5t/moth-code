"""Real local HTTP endpoints; simulated inference transport, not a training/quality claim."""
import threading
from types import SimpleNamespace
from fastapi.testclient import TestClient
from moth.server.app import create_app


def test_project_context_requires_consent_and_general_history_stays_separate(paths, project, monkeypatch):
    app = create_app(paths, token='secret')
    h = {'Authorization': 'Bearer secret'}
    captured = []
    done = threading.Event()
    router = app.state.services.extras['inference_router']
    monkeypatch.setattr(router, 'describe', lambda: 'simulated test transport')
    def chat(messages, params, on_text, cancel, **kw):
        captured.append((messages, kw))
        on_text('test response')
        done.set()
        return SimpleNamespace(extra={}, generated_tokens=1, tokens_per_sec=1, stop_reason='eos')
    monkeypatch.setattr(router, 'chat', chat)
    with TestClient(app) as c:
        pid = c.post('/api/projects', headers=h, json={'path': str(project)}).json()['id']
        c.put('/api/account/session', headers=h, json={'server_url': 'https://example.test', 'token': 'test-session'})
        denied = c.post('/api/chat', headers=h, json={'message': 'Explain add', 'context_project_id': pid})
        assert denied.status_code == 412 and not captured
        c.put(f'/api/projects/{pid}/cloud-consent', headers=h, json={'granted': True})
        result = c.post('/api/chat', headers=h, json={'message': 'Explain add', 'context_project_id': pid})
        assert result.status_code == 200, result.text
        assert done.wait(2)
        msgs, opts = captured[-1]
        assert opts == {'project_id': pid, 'project_data': True}
        assert 'def add' in msgs[-1].content and 'SECRET=1' not in msgs[-1].content
        svc = app.state.services
        project_cid = svc.db.execute('INSERT INTO conversations(project_id,title,created_at) VALUES (?,?,?)', (pid, 'Code history', 1)).lastrowid
        general = c.get('/api/conversations?scope=general', headers=h).json()
        assert result.json()['conversation_id'] in [r['id'] for r in general]
        assert project_cid not in [r['id'] for r in general]
        assert all(r['project_id'] == pid for r in c.get(f'/api/conversations?project_id={pid}', headers=h).json())
        assert svc.db.one('SELECT content FROM messages WHERE conversation_id=? AND role=?', (result.json()['conversation_id'], 'user'))['content'] == 'Explain add'
