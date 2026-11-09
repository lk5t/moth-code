"""Deterministic, incremental project understanding. Never imports or executes project code."""
from __future__ import annotations
import ast
from collections import Counter
import hashlib
import json
import posixpath
from pathlib import Path
import re
import threading
import time

from moth.db import Database
from moth.agent.retrieval import CodeIndex, MAX_FILE_BYTES
from moth.agent.memory import MemoryStore
from moth.security.permissions import is_secret_path
from moth.workspace.scanner import iter_files, LANGUAGES, BUILD_MARKERS

FRAMEWORKS={'react':'React','next':'Next.js','vue':'Vue','svelte':'Svelte','fastapi':'FastAPI','django':'Django','flask':'Flask','torch':'PyTorch','tauri':'Tauri','@tauri-apps/api':'Tauri'}


def analyze(path, text):
    result={'imports':[],'dependencies':[],'issues':[]}
    suffix=Path(path).suffix.lower()
    def issue(message,line=1):result['issues'].append({'path':path,'line':line,'message':message})
    if suffix == '.py':
        try:
            for node in ast.walk(ast.parse(text)):
                if isinstance(node,ast.Import):
                    for item in node.names:result['imports'].append({'module':item.name,'line':node.lineno,'relative':0})
                elif isinstance(node,ast.ImportFrom):
                    result['imports'].append({'module':node.module or '', 'line':node.lineno,'relative':node.level})
        except (SyntaxError,ValueError,RecursionError) as error:issue('Python syntax could not be parsed: '+str(getattr(error,'msg',type(error).__name__)),getattr(error,'lineno',1) or 1)
    elif suffix in ('.js','.jsx','.ts','.tsx','.vue','.svelte'):
        for match in re.finditer(r'''(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]([^'"\n]+)['"]''',text):
            result['imports'].append({'module':match.group(1)[:300],'line':text.count('\n',0,match.start())+1,'relative':None})
    config=None
    try:
        if Path(path).name == 'package.json':
            config=json.loads(text)
            for section in ('dependencies','devDependencies','peerDependencies'):
                for name,version in (config.get(section) or {}).items():
                    safe=str(version) if re.fullmatch(r'[A-Za-z0-9.*^~>=<,+ _-]{0,80}',str(version)) else 'source reference'
                    result['dependencies'].append({'name':str(name)[:200],'version':safe,'source':path,'kind':section})
        elif Path(path).name in ('pyproject.toml','Cargo.toml'):
            try:import tomllib
            except ImportError:
                issue('TOML analysis needs Python 3.11 or newer');return result
            config=tomllib.loads(text)
            deps=(config.get('project') or {}).get('dependencies',[]) if Path(path).name == 'pyproject.toml' else (config.get('dependencies') or {}).keys()
            for entry in deps:
                match=re.match(r'[A-Za-z0-9_.-]+',entry)
                if match:result['dependencies'].append({'name':match.group(),'source':path,'kind':'declared'})
    except (ValueError,TypeError,AttributeError) as error:issue('Configuration could not be parsed: '+type(error).__name__)
    return result


def disabled(db, project_id):
    row=db.one('SELECT value FROM project_graph WHERE project_id=?',(project_id,))
    return bool(row and json.loads(row['value']).get('disabled'))


class ScopedCodeIndex(CodeIndex):
    def update(self, project_id, root, paths=None):
        if disabled(self.db,project_id):return {'files':0,'added':0,'updated':0,'removed':0,'disabled':True}
        return super().update(project_id,root,paths)
    def search(self, project_id, text, limit=6):
        return [] if disabled(self.db,project_id) else super().search(project_id,text,limit)


class ScopedMemory(MemoryStore):
    def add(self, project_id, *args, **kwargs):
        if disabled(self.db,project_id):raise ValueError('Refresh project intelligence before adding memory')
        return super().add(project_id,*args,**kwargs)


class ProjectIntelligence:
    def __init__(self, home, scope):
        self.root=Path(home)/'project-intelligence';self.root.mkdir(mode=0o700,exist_ok=True)
        self.scope=scope;self.lock=threading.RLock();self.databases={}

    def database(self):
        scope,_=self.scope.resolve()
        with self.lock:
            if scope not in self.databases:
                path=self.root/(scope+'.sqlite');db=Database(path);path.chmod(0o600)
                db.execute('PRAGMA secure_delete=ON')
                db.execute('CREATE TABLE IF NOT EXISTS project_graph (project_id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
                self.databases[scope]=db
            return self.databases[scope]

    def index(self):return ScopedCodeIndex(self.database())
    def memory(self):return ScopedMemory(self.database())

    def refresh(self, project_id, workspace, force=False):
        root=workspace.root.resolve()
        with self.lock:
            db=self.database();row=db.one('SELECT value FROM project_graph WHERE project_id=?',(project_id,))
            previous=json.loads(row['value']) if row else {}
            if previous.get('disabled') and not force:return self.public(project_id,previous)
            files={};allowed=[];changed=[];warnings=[]
            candidates=list(iter_files(root,max_files=1001));truncated=len(candidates)>1000
            for rel,path in candidates[:1000]:
                if is_secret_path(rel) or path.is_symlink():continue
                try:
                    if root not in path.resolve().parents:continue
                    stat=path.stat()
                    if stat.st_size > MAX_FILE_BYTES: warnings.append({'path':rel,'message':'File exceeds the analysis size limit'});continue
                    prior=(previous.get('files') or {}).get(rel)
                    stamp=[stat.st_mtime_ns,stat.st_size]
                    if prior and prior['stamp'] == stamp and not force:
                        files[rel]=prior;allowed.append((rel,path));continue
                    text=path.read_text(encoding='utf-8')
                except UnicodeError:
                    warnings.append({'path':rel,'message':'Text is not UTF-8; analysis skipped'});continue
                except OSError:
                    warnings.append({'path':rel,'message':'File could not be read'});continue
                files[rel]={'stamp':stamp,'sha256':hashlib.sha256(text.encode()).hexdigest(),'analysis':analyze(rel,text)}
                allowed.append((rel,path));changed.append(rel)
                # Same-mtime changes still invalidate the reused retrieval index.
                db.execute('DELETE FROM code_chunks WHERE project_id=? AND path=?',(project_id,rel))
            removed=sorted(set(previous.get('files',{}))-set(files))
            CodeIndex(db).update(project_id,root,paths=allowed)
            edges=[];dependencies=[];issues=[]
            for rel,info in files.items():
                analysis=info['analysis'];dependencies.extend(analysis['dependencies']);issues.extend(analysis['issues'])
                for item in analysis['imports']:
                    module=item['module'];base=posixpath.dirname(rel);relative=module.startswith('.') or bool(item['relative'])
                    if Path(rel).suffix == '.py':
                        target=posixpath.join(base,*(['..']*max(0,(item['relative'] or 0)-1)),module.replace('.','/')) if item['relative'] else module.replace('.','/')
                    elif relative:target=posixpath.join(base,module)
                    else:target=module
                    target=posixpath.normpath(target)
                    matches=[target,target+'.py',target+'/__init__.py',target+'.ts',target+'.tsx',target+'.js',target+'.jsx',target+'/index.ts',target+'/index.tsx',target+'/index.js']
                    resolved=next((name for name in matches if name in files),None)
                    edges.append({'source':rel,'target':resolved or module,'line':item['line'],'local':bool(resolved)})
                    if relative and not resolved:issues.append({'path':rel,'line':item['line'],'message':'Unresolved local import: '+module})
            languages=dict(Counter(LANGUAGES.get(Path(name).suffix.lower(),'Other') for name in files))
            frameworks=sorted({FRAMEWORKS[d['name'].lower()] for d in dependencies if d['name'].lower() in FRAMEWORKS})
            configs=sorted(name for name in files if Path(name).name in BUILD_MARKERS)
            changes=([{'path':path,'kind':'changed' if path in previous.get('files',{}) else 'added','at':time.time()} for path in changed]+
                     [{'path':path,'kind':'removed','at':time.time()} for path in removed]+previous.get('recent_changes',[]))[:50]
            result={'files':files,'file_count':len(files),'languages':languages,'frameworks':frameworks,'configurations':configs,
                'dependencies':dependencies,'imports':edges,'issues':issues,'warnings':warnings,'truncated':truncated,
                'changed':changed,'removed':removed,'recent_changes':changes,'indexed_at':time.time(),
                'inspected':previous.get('inspected',[]),
                'structure':dict(Counter(name.split('/')[0] if '/' in name else '.' for name in files)),
                'summary':f"{len(files)} analyzed files; "+', '.join(f'{key}: {value}' for key,value in sorted(languages.items()))}
            db.execute('INSERT INTO project_graph(project_id,value) VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET value=excluded.value',(project_id,json.dumps(result)))
            return self.public(project_id,result)

    def public(self, project_id, state):
        out={key:value for key,value in state.items() if key != 'files'}
        out['decisions']=self.memory().list(project_id,'architecture')
        _,out['scope_warning']=self.scope.resolve()
        return out

    def status(self, project_id, workspace):
        with self.lock:
            row=self.database().one('SELECT value FROM project_graph WHERE project_id=?',(project_id,))
            if not row:return self.refresh(project_id,workspace)
            state=json.loads(row['value'])
            if time.time()-state['indexed_at'] > 10:return self.refresh(project_id,workspace)
            return self.public(project_id,state)

    def search(self, project_id, workspace, query, limit=6):
        if self.refresh(project_id,workspace).get("disabled"):
            raise ValueError("Project intelligence is disabled. Refresh it in Code → Project to index again.")
        matches=self.index().search(project_id,query,limit)
        state=self.status(project_id,workspace)
        impacted={edge['source'] for edge in state['imports'] if edge['local'] and edge['target'] in {match['path'] for match in matches}}
        return {'matches':matches,'affected_components':sorted(impacted),'reference_only':True}

    def inspected(self, project_id, workspace, path):
        resolved=workspace.resolve(path)
        relative=resolved.relative_to(workspace.root).as_posix()
        if is_secret_path(relative) or resolved.is_symlink():raise ValueError('Sensitive paths are not recorded in project intelligence')
        with self.lock:
            self.status(project_id,workspace)
            db=self.database();state=json.loads(db.one('SELECT value FROM project_graph WHERE project_id=?',(project_id,))['value'])
            if state.get('disabled'):return
            state['inspected']=([relative]+[item for item in state.get('inspected',[]) if item != relative])[:50]
            db.execute('UPDATE project_graph SET value=? WHERE project_id=?',(json.dumps(state),project_id))

    def delete(self, project_id):
        with self.lock:
            db=self.database()
            for table in ('project_graph','code_chunks','memories'):
                db.execute(f'DELETE FROM {table} WHERE project_id=?',(project_id,))
            db.execute('INSERT INTO project_graph(project_id,value) VALUES (?,?)', (project_id,json.dumps({'disabled':True,'file_count':0,'indexed_at':time.time()})))
            db.execute('VACUUM')

    def shutdown(self):
        for db in self.databases.values():db.close()
        self.databases.clear()
