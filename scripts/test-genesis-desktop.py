#!/usr/bin/env python3
"""Native Windows GENESIS smoke: real installer, frozen backend, isolated Cloud and UI.

Windows accessibility drives the unchanged release through its normal account and Settings UI.
No production account, model, signing key or service is used or modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WindowsUI = runpy.run_path(str(ROOT / 'scripts/windows-desktop-ui.py'))['WindowsUI']


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


def main(installer):
    assert sys.platform == 'win32', 'Run this test on Windows'
    import winreg
    verify = runpy.run_path(str(ROOT / 'scripts/check-release-secrets.py'))['check_updater_signature']
    assert verify(installer, installer.with_name(installer.name + '.sig')), 'Production installer signature is invalid'
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

    def participant_setting():
        with sqlite3.connect(out / 'desktop-home/moth.db') as db:
            row = db.execute("SELECT value FROM settings WHERE key='participant'").fetchone()
        value = json.loads(row[0]) if row else {}
        return {'enabled': bool(value.get('enabled')), 'worker_id': value.get('worker_id')}

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
        measured = api('/v1/admin/evolution/resources')['local']['memory']
        assert measured and measured['available'] > 0, 'Native available RAM could not be measured safely'
        appenv = {**env, 'MOTH_HOME': str(out / 'desktop-home')}
        subprocess.run([str(installer.resolve()), '/S'], check=True, timeout=600, env=appenv)
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
        subprocess.run(['taskkill', '/F', '/T', '/IM', exe.name], capture_output=True, timeout=30)
        app = subprocess.Popen([str(exe)], env=appenv)
        ui = WindowsUI(app.pid)
        ui.configure_cloud(cloud)
        ui.login(user['username'], password)
        print('::notice title=GENESIS native stage::Signed installer, frozen backend and Owner login passed', flush=True)
        ui.click('Chat')
        ui.draft('native unsent draft')
        ui.click('Code')
        ui.click('Chat')
        assert ui.draft() == 'native unsent draft'
        ui.click('Intelligence')
        for label in ('Overview','Chat','Code','Intelligence','Data','Network','Activity','Settings'):
            ui.find(label, ('Button',))
        ui.click('Overview')
        ui.click('Model details')
        ui.click('Inspect layer 2')
        wait(lambda: 'Layer 2 selected' in ui.text(), 'selected architecture layer')
        ui.click('Intelligence')
        ui.click('Training', control_type='TabItem')
        print('::notice title=GENESIS native stage::Workspace drafts and interactive Intelligence tabs passed', flush=True)
        worker_backend = api('/v1/admin/evolution/status')['settings']['backends']['workers']
        for value in (False, True):
            ui.click('Use cloud workers')
            wait(lambda: api('/v1/admin/evolution/status')['settings']['cloud_workers'] is value,
                 'cloud worker toggle persisted')
            assert api('/v1/admin/evolution/status')['settings']['backends']['workers'] is worker_backend, \
                'Cloud infrastructure toggle must not change personal-worker backend policy'
        ui.click('Contribute this computer')
        participant = wait(lambda: (s if (s := participant_setting())['enabled'] and s['worker_id'] else None), 'real desktop worker enrollment')
        assert any(w['id'] == participant['worker_id'] and w['hardware'].get('client') == 'moth-code'
                   for w in api('/v1/training/workers')['workers'])
        ui.click('Contribute this computer')
        wait(lambda: not participant_setting()['enabled'], 'participant disable persisted')
        ui.click('Resume MOTH training')
        print('::notice title=GENESIS native stage::Cloud worker toggle and actual desktop enrollment passed; waiting for CPU progress', flush=True)
        cycle = wait(lambda: api('/v1/admin/evolution/status').get('cycle'), 'eligible cycle created by UI', timeout=120)
        wait(lambda: any(e.get('progress', {}).get('step', 0) > 0 or e.get('candidate_version')
                         for e in (api('/v1/admin/evolution/status').get('cycle') or {}).get('experiments', [])),
             'real CPU training progress from requested cycle', timeout=180)
        api('/v1/admin/evolution/pause', {}, 'POST')
        ui.resize(800, 600)
        ui.click('Evolution', control_type='TabItem')
        for label in ('Network','Data','Activity'):
            ui.click(label, control_type='Button')
        ui.click('Chat')
        assert ui.draft() == 'native unsent draft'
        ui.click('Data')
        ui.close()
        app.wait(timeout=30)
        app = subprocess.Popen([str(exe)], env=appenv)
        ui = WindowsUI(app.pid)
        ui.find('Dataset Quality Studio', ('Text',))  # persisted Data workspace
        ui.click('Settings');ui.optional_tab('Account')
        ui.find(user['username'],('Text',),contains=True)  # actual Windows credential-vault session survived
        ui.click('Advanced · Native AI operations')
        ui.click('Inspect deletion inventory')
        reset=wait(lambda:(r if (r:=api('/v1/admin/evolution/native-reset')).get('status')=='preview' else None),'native reset preview')
        assert reset['inventory']['records']['model_releases']>0
        ui.set_text('Confirm all native AI deletion','DELETE ALL NATIVE AI DATA')
        ui.click('Permanently delete reviewed native AI data')
        wait(lambda:api('/v1/admin/evolution/native-reset').get('status')=='completed','isolated native reset',timeout=120)
        assert api('/v1/intelligence/progress')['current'] is None
        ui.click('Overview');ui.find('No native model available',('Text',))
        api('/v1/admin/evolution/initialize',{},'POST')
        assert api('/v1/admin/evolution/versions'), 'Explicit fresh initialization failed after isolated reset'
        evidence = {'native_windows': True, 'real_frozen_backend': True, 'real_cloud_api': True,
                    'draft_preserved_across_modes': True, 'main_workspaces': 8, 'isolated_full_reset_verified': True, 'fresh_initialization_after_reset': True,
                    'owner_session_and_navigation_restored_after_restart': True, 'tested_window': [800, 600],
                    'worker_enrollment_id': participant['worker_id'], 'training_cycle_id': cycle['id'],
                    'production_reset': False, 'trained_foundation': False}
        (out / 'evidence.json').write_text(json.dumps(evidence, indent=2))
        print('::notice title=GENESIS native Windows verification::' + json.dumps(evidence), flush=True)
    except Exception:
        # Keep the actual scheduling/optimizer error accessible even when Actions log downloads
        # are network-restricted. This is the isolated fixture, never the production service.
        try:
            status = api('/v1/admin/evolution/status')
            diagnostic = {key: status.get(key) for key in ('state', 'cycle', 'warnings')}
            diagnostic['local_resources'] = api('/v1/admin/evolution/resources')['local']
            diagnostic['trainer_logs'] = [p.read_text(errors='replace')[-3000:]
                                          for p in sorted((out / 'cloud/evolution/runs').glob('exp-*/train.log'))[-3:]]
            (out / 'failure.json').write_text(json.dumps(diagnostic, indent=2))
            detail = json.dumps(diagnostic).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print('::notice title=GENESIS native failure diagnostics::' + detail, flush=True)
        except Exception as error:
            print('::notice title=GENESIS native diagnostics unavailable::' + type(error).__name__, flush=True)
        raise
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
