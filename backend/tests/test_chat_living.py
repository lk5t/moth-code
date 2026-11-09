"""Real CPU inference, persisted turns and backward-compatible history API; no quality claim."""
import json
import shutil
import time
from fastapi.testclient import TestClient
from moth.server.app import create_app


def test_real_cpu_regeneration_keeps_prior_answers_and_one_user_turn(paths, tiny_model):
    app=create_app(paths,token='test')
    svc=app.state.services
    ondevice=svc.extras['ondevice']
    shutil.copytree(tiny_model['dir'],ondevice.root/'fx-model')
    (ondevice.root/'current.json').write_text(json.dumps({'dir':'fx-model','display_name':'Tiny CPU test model'}))
    svc.db.set_setting('ondevice',{'answer_on_device':True})
    headers={'Authorization':'Bearer test'}
    def answers(cid,count):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            rows=svc.db.query("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'",(cid,))
            if len(rows)>=count:return rows
            time.sleep(.02)
        raise AssertionError('Real CPU reply did not complete')
    with TestClient(app) as client:
        first=client.post('/api/chat',headers=headers,json={'message':'Explain addition','params':{'max_new_tokens':4,'temperature':0}})
        assert first.status_code == 200,first.text
        cid=first.json()['conversation_id']
        answers(cid,1)
        second=client.post('/api/chat',headers=headers,json={'conversation_id':cid,'regenerate':True,
            'message':'This must not replace the original prompt','params':{'max_new_tokens':4,'temperature':0}})
        assert second.status_code == 200,second.text
        replies=answers(cid,2)
        assert svc.db.one("SELECT count(*) AS n FROM messages WHERE conversation_id=? AND role='user'",(cid,))['n'] == 1
        meta=json.loads(replies[-1]['meta'])
        assert meta['regenerated'] and meta['prompt'] == 'Explain addition'
        assert meta['via'] == 'computer' and meta['tokens'] > 0
        assert len(client.get(f'/api/conversations/{cid}/messages',headers=headers).json()) == 3
        assert client.get('/api/conversations',params={'scope':'general','q':'addition'},headers=headers).json()[0]['id'] == cid


def test_history_pages_preserve_all_records_without_overlap(paths):
    app=create_app(paths,token='test');svc=app.state.services
    cid=svc.db.execute('INSERT INTO conversations(project_id,title,created_at) VALUES (NULL,?,?)',('Long conversation',1)).lastrowid
    for index in range(250):
        svc.db.execute('INSERT INTO messages(conversation_id,role,content,meta,ts) VALUES (?,?,?,?,?)',(cid,'user' if index%2 == 0 else 'assistant',f'Message {index}',None,index))
    with TestClient(app) as client:
        h={'Authorization':'Bearer test'}
        latest=client.get(f'/api/conversations/{cid}/messages?limit=100',headers=h).json()
        older=client.get(f'/api/conversations/{cid}/messages?limit=100&before_id={latest[0]["id"]}',headers=h).json()
        assert len(latest) == len(older) == 100
        assert not {m['id'] for m in latest} & {m['id'] for m in older}
        assert latest[-1]['content'] == 'Message 249'
        assert len(client.get(f'/api/conversations/{cid}/messages',headers=h).json()) == 250
        assert client.get('/api/conversations?q=Message%20249',headers=h).json()[0]['id'] == cid
