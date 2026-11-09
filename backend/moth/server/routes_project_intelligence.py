"""Authorized, profile-bound project analysis. No remote upload or project writes occur here."""
from __future__ import annotations
import secrets
from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel, Field, StrictBool
from moth.account_scope import AccountScope
from moth.agent.project_intelligence import ProjectIntelligence
from moth.server.services import Services, NotFound

class DecisionIn(BaseModel):
    text:str=Field(min_length=1,max_length=2000)
    confirmed:StrictBool=False
class InspectedIn(BaseModel):
    path:str=Field(min_length=1,max_length=1000)


def register(app:FastAPI,svc:Services,deps):
    scope=AccountScope(lambda:svc.extras.get('account'),svc.db,http_factory=svc.extras.get('project_http_factory'))
    graph=ProjectIntelligence(svc.paths.home,scope)
    svc.extras['account_scope']=scope;svc.extras['project_intelligence']=graph
    def bound(request:Request):
        if not secrets.compare_digest(request.headers.get('x-moth-profile',''),scope.fingerprint()):
            raise HTTPException(409,'The selected account changed. Wait for sign-in to finish and retry.')
    def workspace(pid,request):bound(request);return svc.workspace(pid)
    async def pinned(request:Request):
        token=scope.snapshot.set(dict(scope._account() or {}))
        try:
            bound(request)
            yield
        finally:scope.snapshot.reset(token)
    deps=[*deps,Depends(pinned)]


    @app.get('/api/projects/{pid}/intelligence',dependencies=deps)
    def status(pid:int,request:Request):return graph.status(pid,workspace(pid,request))

    @app.post('/api/projects/{pid}/intelligence/refresh',dependencies=deps)
    def refresh(pid:int,request:Request):return graph.refresh(pid,workspace(pid,request),force=True)

    @app.delete('/api/projects/{pid}/intelligence',dependencies=deps)
    def clear(pid:int,request:Request):
        workspace(pid,request)
        tasks=svc.extras.get('tasks')
        if tasks and any(thread.is_alive() for thread in tasks._threads.values()):
            raise HTTPException(409,'Stop active coding tasks before clearing project memory.')
        graph.delete(pid);svc.db.log_activity('project-index','Cleared project intelligence',pid)
        return {'ok':True,'disabled':True}

    @app.get('/api/projects/{pid}/intelligence/search',dependencies=deps)
    def search(pid:int,q:str,request:Request):
        try:return graph.search(pid,workspace(pid,request),q[:200])
        except ValueError as error:raise HTTPException(409,str(error)) from None

    @app.post('/api/projects/{pid}/intelligence/decisions',dependencies=deps)
    def decision(pid:int,body:DecisionIn,request:Request):
        ws=workspace(pid,request)
        if not body.confirmed:raise HTTPException(422,'Confirm that this is a project decision before saving it.')
        graph.status(pid,ws)
        try:mid=graph.memory().add(pid,'architecture','Confirmed project decision',body.text,verified=True)
        except ValueError as error:raise HTTPException(409,str(error)) from None
        return {'id':mid}

    @app.delete('/api/projects/{pid}/intelligence/decisions/{mid}',dependencies=deps)
    def delete_decision(pid:int,mid:int,request:Request):
        workspace(pid,request);db=graph.database()
        row=db.one('SELECT id FROM memories WHERE id=? AND project_id=?',(mid,pid))
        if not row:raise NotFound('Project decision not found')
        graph.memory().delete(mid);return {'ok':True}

    @app.post('/api/projects/{pid}/intelligence/inspected',dependencies=deps)
    def inspected(pid:int,body:InspectedIn,request:Request):
        try:graph.inspected(pid,workspace(pid,request),body.path)
        except ValueError as error:raise HTTPException(403,str(error)) from None
        return {'ok':True}
