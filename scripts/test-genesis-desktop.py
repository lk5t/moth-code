#!/usr/bin/env python3
"""Native Windows GENESIS smoke: real installer, frozen backend, isolated Cloud and UI.

The release executable is unchanged. WebView debugging applies only to this test process.
No production account, model, signing key or service is used or modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
evaluate = runpy.run_path(str(ROOT / 'scripts/test-published-desktop-update.py'))['evaluate']


def wait(fn, description, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
        except (OSError, ValueError, AssertionError, StopIteration):
            pass
        time.sleep(1)
    raise AssertionError(f'Timed out: {description}')


def click(label, role=None):
    selector = f'[role={role}]' if role else 'button'
    expression = f"""(() => {{ const b = [...document.querySelectorAll({json.dumps(selector)})].find(
      b => b.offsetParent !== null && (b.getAttribute('aria-label') === {json.dumps(label)} || b.textContent.trim() === {json.dumps(label)}));
      if (!b || b.disabled) return false;
      b.dispatchEvent(new MouseEvent('mousedown', {{bubbles:true,button:0}})); b.click(); return true; }})()"""
    wait(lambda: evaluate(expression), f'click {label}')


def main(installer):
    assert sys.platform == 'win32', 'Run this test on Windows'
    import winreg
    out = Path(os.environ['RUNNER_TEMP']) / 'genesis-desktop-test'
    out.mkdir(parents=True, exist_ok=True)
    cloud = 'http://127.0.0.1:8910'  # loopback API test; signed HTTPS updates have their own native test
    env = {**os.environ, 'MOTH_SERVER_DATA_DIR': str(out / 'cloud'), 'MOTH_SERVER_PUBLIC_URL': cloud,
           'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'}
    password = 'N8!' + secrets.token_urlsafe(32)
    subprocess.run([sys.executable, '-m', 'moth_server.cli', 'init-owner', '--email', 'native@test.invalid', '--password-stdin'],
                   input=password + '\n', text=True, env=env, check=True, timeout=60, capture_output=True)
    log = (out / 'cloud.log').open('w')
    server = subprocess.Popen([sys.executable, '-m', 'moth_server.cli', 'serve', '--port', '8910'], env=env, stdout=log, stderr=log)
    app = None
    token = None

    def api(path, body=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(cloud + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r) if r.status != 204 else None

    def local(path):
        # Keep the per-launch bearer token inside the WebView; never print/persist it.
        return evaluate(f"""(async () => {{ const b = await window.__TAURI_INTERNALS__.invoke('backend_info');
          const r = await fetch(b.url + {json.dumps(path)}, {{headers:{{Authorization:'Bearer '+b.token}}}});
          if (!r.ok) throw new Error('Local API returned '+r.status); return r.json(); }})()""")

    try:
        wait(lambda: api('/v1/health'), 'isolated Cloud health')
        session = api('/v1/auth/login', {'username': 'LK5T', 'password': password})
        token, user = session['token'], session['user']
        api('/v1/admin/evolution/settings', {'changes': {'paused': True, 'training': {
            'steps': 8, 'batch_size': 2, 'seq_len': 64, 'checkpoint_interval': 4, 'eval_interval': 4},
            'limits': {'cpu_threads': 2, 'min_free_memory_gb': 0.05, 'min_free_disk_gb': 0.05}}}, 'PUT')
        api('/v1/admin/evolution/initialize', {}, 'POST')
        api('/v1/admin/evolution/initialize/activate', {}, 'POST')
        api('/v1/admin/config/flags', {'cloud_inference_enabled': True}, 'PUT')
        subprocess.run([str(installer.resolve()), '/S'], check=True, timeout=600)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall') as parent:
            exe = None
            for i in range(winreg.QueryInfoKey(parent)[0]):
                with winreg.OpenKey(parent, winreg.EnumKey(parent, i)) as key:
                    try:
                        if winreg.QueryValueEx(key, 'DisplayName')[0] == 'MOTH Code':
                            directory = Path(winreg.QueryValueEx(key, 'UninstallString')[0].strip('"')).parent
                            exe = next(p for p in directory.glob('*.exe') if 'uninstall' not in p.name.lower())
                            break
                    except FileNotFoundError:
                        continue
        assert exe, 'Installed MOTH Code executable was not registered'
        appenv = {**env, 'MOTH_HOME': str(out / 'desktop-home'),
                  'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': '--remote-debugging-port=9222'}
        app = subprocess.Popen([str(exe)], env=appenv)
        wait(lambda: evaluate('!!window.__TAURI_INTERNALS__'), 'native WebView')
        account = {'server': cloud, 'username': user['username'], 'role': 'owner', 'last_used': time.time()}
        evaluate(f"""(async () => {{ localStorage.setItem('moth.serverUrl', {json.dumps(cloud)});
          localStorage.setItem('moth.welcome.done','1'); localStorage.setItem('moth.navigation',JSON.stringify({{view:'chat',workspaceMode:'chat'}}));
          await window.__TAURI_INTERNALS__.invoke('accounts_remember',{{account:{json.dumps(account)},token:{json.dumps(token)}}}); return true; }})()""")
        evaluate('location.reload(); true')
        wait(lambda: evaluate("!!document.querySelector('button[aria-label=Intelligence]')"), 'real app launch and restored Owner session')
        assert local('/api/participant')['available'], 'Frozen backend omitted MOTH Worker'
        wait(lambda: evaluate("[...document.querySelectorAll('textarea')].some(t => t.offsetParent !== null && !t.disabled)"), 'chat connected to real model')
        evaluate("""(() => { const t=[...document.querySelectorAll('textarea')].find(t=>t.offsetParent!==null);
          Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(t,'native unsent draft');
          t.dispatchEvent(new Event('input',{bubbles:true})); return true; })()""")
        click('Code')
        click('Chat')
        assert evaluate("[...document.querySelectorAll('textarea')].some(t=>t.offsetParent!==null && t.value==='native unsent draft')")
        click('Intelligence')
        wait(lambda: evaluate("document.querySelectorAll('[role=tab]').length===5"), 'five Intelligence tabs')
        wait(lambda: evaluate("!!document.querySelector('[aria-label=\"Inspect layer 2\"]')"), 'real model architecture')
        click('Inspect layer 2', 'button')
        assert evaluate("document.querySelector('[aria-label=\"Inspect layer 2\"]').getAttribute('aria-pressed')==='true'")
        click('Training', 'tab')
        for value in (False, True):
            click('Use cloud workers', 'switch')
            wait(lambda: api('/v1/admin/evolution/status')['settings']['backends']['workers'] is value, 'worker toggle persisted')
        click('Contribute this computer', 'switch')
        participant = wait(lambda: (s if (s := local('/api/participant'))['enabled'] and s['worker_id'] else None), 'real desktop worker enrollment')
        assert not participant['error'], participant['error']
        click('Contribute this computer', 'switch')
        wait(lambda: not local('/api/participant')['enabled'], 'participant disable persisted')
        click('Resume MOTH training')
        cycle = wait(lambda: api('/v1/admin/evolution/status').get('cycle'), 'eligible cycle created by UI', timeout=120)
        wait(lambda: any(e.get('progress', {}).get('step', 0) > 0 or e.get('candidate_version')
                         for e in (api('/v1/admin/evolution/status').get('cycle') or {}).get('experiments', [])),
             'real CPU training progress from requested cycle', timeout=180)
        api('/v1/admin/evolution/pause', {}, 'POST')
        for label in ('Evolution', 'Network', 'Data'):
            click(label, 'tab')
        click('Workspace · Code / Chat')
        assert evaluate("[...document.querySelectorAll('textarea')].some(t=>t.offsetParent!==null && t.value==='native unsent draft')")
        # Navigation/layout are persisted across a real WebView reload; drafts are kept across switches.
        click('Intelligence')
        click('Data', 'tab')
        evaluate('location.reload(); true')
        wait(lambda: evaluate("document.querySelector('[role=tab][data-state=active]')?.textContent==='Data'"), 'navigation restored after reload')
        evidence = {'native_windows': True, 'real_frozen_backend': True, 'real_cloud_api': True,
                    'draft_preserved_across_modes': True, 'intelligence_tabs': 5,
                    'worker_enrollment_id': participant['worker_id'], 'training_cycle_id': cycle['id'],
                    'production_reset': False, 'trained_foundation': False}
        (out / 'evidence.json').write_text(json.dumps(evidence, indent=2))
        print('::notice title=GENESIS native Windows verification::' + json.dumps(evidence), flush=True)
    finally:
        if app:
            subprocess.run(['taskkill', '/PID', str(app.pid), '/T', '/F'], capture_output=True, timeout=30)
        server.terminate()
        server.wait(timeout=30)
        log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--installer', required=True, type=Path)
    try:
        main(parser.parse_args().installer)
    except Exception as e:
        detail = str(e).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print('::error title=GENESIS native Windows verification failed::' + detail, flush=True)
        raise
