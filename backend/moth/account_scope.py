"""Local cache identity derived from verified Cloud identity, never caller-supplied user claims."""
from __future__ import annotations
from contextvars import ContextVar
import hashlib
import threading
import time
import httpx


class AccountScope:
    def __init__(self, account, db, http_factory=None):
        self._account, self.db = account, db
        self.snapshot = ContextVar("project_account", default=None)
        self.http_factory = http_factory or (lambda base: httpx.Client(base_url=base, timeout=5))
        self.lock = threading.RLock()

    def account(self):
        pinned = self.snapshot.get()
        return self._account() if pinned is None else pinned

    def fingerprint(self):
        account = self.account() or {}
        if not account.get('token') or not account.get('server_url'):return 'device-local'
        return hashlib.sha256(((account['server_url'].rstrip('/'))+'\0'+account['token']).encode()).hexdigest()

    def resolve(self, retry=False):
        account = self.account() or {}
        server, token = (account.get('server_url') or '').rstrip('/'), account.get('token')
        if not server or not token:
            return 'device-local', None
        fingerprint = hashlib.sha256((server+'\0'+token).encode()).hexdigest()
        with self.lock:
            bindings = self.db.get_setting('project_identity_bindings') or {}
            binding = bindings.get(fingerprint)
            if not binding or (not binding.get('uid') and (retry or time.time()-binding['at'] > 60)):
                uid = None
                try:
                    with self.http_factory(server) as http:
                        response = http.get('/v1/me', headers={'Authorization':f'Bearer {token}'})
                        if response.status_code == 200:
                            user = response.json(); value = (user.get('user') or user).get('id')
                            if type(value) in (int,str) and str(value).strip() and len(str(value)) <= 128:
                                uid = str(value)
                except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                    pass
                binding = {'uid':uid,'at':time.time()}; bindings[fingerprint] = binding
                bindings = dict(sorted(bindings.items(),key=lambda pair:pair[1]['at'],reverse=True)[:32])
                self.db.set_setting('project_identity_bindings',bindings)
            if binding.get('uid'):
                return hashlib.sha256((server+'\0'+binding['uid']).encode()).hexdigest(), None
            return 'session-'+fingerprint, 'Account verification unavailable; using an isolated local session cache.'

    def consented(self, project_id):
        if project_id is None or not (self.account() or {}).get('token'):
            return False
        scope,_ = self.resolve()
        return project_id in (self.db.get_setting('scoped_workspace_consent') or {}).get(scope,[])

    def consent(self, project_id, granted):
        scope,_ = self.resolve()
        scopes = self.db.get_setting('scoped_workspace_consent') or {}
        projects = set(scopes.get(scope,[]))
        if granted: projects.add(project_id)
        else: projects.discard(project_id)
        scopes[scope] = sorted(projects)
        self.db.set_setting('scoped_workspace_consent',scopes)
