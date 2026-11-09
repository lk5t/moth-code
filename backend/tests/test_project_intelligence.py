"""Actual filesystem/index integration. Only Cloud identity HTTP is substituted."""
import hashlib
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from moth.account_scope import AccountScope
from moth.agent.project_intelligence import ProjectIntelligence
from moth.db import Database
from moth.security.permissions import Workspace
from moth.server.app import create_app


def test_incremental_graph_memory_and_explicit_deletion(paths, project, tmp_path):
    db=Database(paths.db)
    scope=AccountScope(lambda:None,db)
    graph=ProjectIntelligence(paths.home,scope)
    (project/'package.json').write_text(json.dumps({'dependencies':{'react':'^18','private-lib':'https://token@private.test/pkg'}}))
    (project/'main.ts').write_text("import {add} from './demo/math_utils';\nimport x from './missing';")
    (project/'demo'/'consumer.py').write_text('from .math_utils import add\n')
    outside=tmp_path/'external.py';outside.write_text('PRIVATE_OUTSIDE=1')
    try:(project/'external.py').symlink_to(outside)
    except OSError:
        import os
        if os.name!='nt':raise  # Windows CI may not grant symbolic-link creation privileges.
    ws=Workspace(project)
    first=graph.refresh(1,ws)
    assert 'React' in first['frameworks']
    assert any(e['target']=='demo/math_utils.py' and e['local'] for e in first['imports'])
    assert any(e['path']=='main.ts' and e['line']==2 for e in first['issues'])
    assert 'private.test' not in json.dumps(first)
    assert not graph.index().search(1,'PRIVATE_OUTSIDE SECRET')
    rows=graph.database().query('SELECT id FROM code_chunks ORDER BY id')
    assert graph.refresh(1,ws)['changed']==[]
    assert rows==graph.database().query('SELECT id FROM code_chunks ORDER BY id')
    (project/'demo'/'consumer.py').write_text('from .missing import add\n')
    changed=graph.refresh(1,ws)
    assert changed['changed']==['demo/consumer.py']
    graph.memory().add(1,'architecture','Decision','Use immutable state',True)
    assert len(graph.status(1,ws)['decisions'])==1
    assert graph.search(1,ws,'add')['reference_only']
    graph.delete(1)
    assert graph.status(1,ws)['disabled']
    assert not graph.index().search(1,'add')
    graph.index().update(1,project)
    assert graph.database().one('SELECT COUNT(*) AS n FROM code_chunks')['n']==0
    with pytest.raises(ValueError):graph.search(1,ws,'add')
    graph.refresh(1,ws,force=True)
    assert graph.status(1,ws)['decisions']==[]
    assert graph.index().search(1,'add')
    assert (project/'demo'/'math_utils.py').exists()
    graph.shutdown();db.close()


def test_verified_identity_scopes_memory_and_consent(paths, project):
    db=Database(paths.db);account={'server_url':'https://cloud.test','token':'alice','user':{'id':'forged'}}
    def handler(request):
        token=request.headers['authorization'].split()[-1]
        return httpx.Response(200,json={'id':1 if token.startswith('alice') else 2})
    scope=AccountScope(lambda:account,db,http_factory=lambda base:httpx.Client(base_url=base,transport=httpx.MockTransport(handler)))
    graph=ProjectIntelligence(paths.home,scope);ws=Workspace(project)
    graph.refresh(1,ws);graph.memory().add(1,'architecture','Alice','Alice private',True);scope.consent(1,True)
    alice=scope.resolve()[0];assert scope.consented(1)
    account['token']='bob';assert not scope.consented(1)
    assert graph.status(1,ws)['decisions']==[]
    graph.memory().add(1,'architecture','Bob','Bob private',True)
    graph.delete(1)
    account['token']='alice-rotated'
    assert scope.resolve()[0]==alice and scope.consented(1)
    assert graph.status(1,ws)['decisions'][0]['content']=='Alice private'
    account.clear();assert not scope.consented(1)
    assert graph.status(1,ws)['decisions']==[]
    graph.shutdown();db.close()


def test_routes_auth_project_boundary_and_profile_binding(paths, project):
    app=create_app(paths,token='local-secret');h={'Authorization':'Bearer local-secret','X-Moth-Profile':'device-local'}
    with TestClient(app) as client:
        pid=client.post('/api/projects',headers=h,json={'path':str(project)}).json()['id'];base=f'/api/projects/{pid}/intelligence'
        assert client.get(base).status_code==401
        assert client.get(base,headers={'Authorization':'Bearer local-secret'}).status_code==409
        assert client.get('/api/projects/999/intelligence',headers=h).status_code==404
        assert client.get(base,headers=h).status_code==200
        assert client.post(base+'/decisions',headers=h,json={'text':'Use tests','confirmed':False}).status_code==422
        mid=client.post(base+'/decisions',headers=h,json={'text':'Use tests','confirmed':True}).json()['id']
        assert client.delete(base+f'/decisions/{mid}',headers=h).status_code==200
        assert client.post(base+'/inspected',headers=h,json={'path':'.env'}).status_code==403
        assert client.post(base+'/inspected',headers=h,json={'path':'README.md'}).status_code==200
        assert client.get(base,headers=h).json()['inspected']==['README.md']
        assert client.delete(base,headers=h).status_code==200
        assert client.get(base,headers=h).json()['disabled']
        assert client.get(base+'/search?q=add',headers=h).status_code==409
        assert client.post(base+'/refresh',headers=h).status_code==200
        assert client.get(base+'/search?q=add',headers=h).json()['matches']


def test_account_switch_during_consent_never_sends_context_to_new_account():
    from moth.inference.router import InferenceRouter,InferenceSettings,NotSignedIn
    from moth.model.chat_format import Message
    from moth.model.generation import GenerationParams
    account={'server_url':'https://alice.test','token':'alice'};sent=[]
    def consent(pid):
        account.update(server_url='https://bob.test',token='bob');return True
    router=InferenceRouter(lambda:InferenceSettings(),lambda:account,consent=consent,client_factory=lambda *args:sent.append(args))
    with pytest.raises(NotSignedIn):router.chat([Message('user','Alice private context')],GenerationParams(),lambda _:None,project_id=1,project_data=True)
    assert not sent
