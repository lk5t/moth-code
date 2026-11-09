#!/usr/bin/env python3
"""Windows regression with the actual published 0.5.1 and 0.5.4 installers and production public keys.

Uses an isolated HTTPS MOTH Server; never changes the production server or release rollout.
Windows accessibility drives the unmodified release through its normal Settings controls.
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import runpy
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = "lk5t/moth-code"


def run(*args, **kw):
    kw.setdefault('timeout', 180)
    return subprocess.run(args, check=True, **kw)


def download_release(version, dest):
    dest.mkdir(parents=True, exist_ok=True)
    release = json.loads(run("gh", "api", f"repos/{REPO}/releases/tags/desktop-v{version}", capture_output=True).stdout)
    assert not release["draft"] and not release["prerelease"], release
    for asset in release["assets"]:
        assert asset["state"] == "uploaded" and asset["size"] > 0
        with (dest / asset["name"]).open("wb") as output:
            run("gh", "api", "-H", "Accept: application/octet-stream", f"repos/{REPO}/releases/assets/{asset['id']}", stdout=output)
        data = (dest / asset["name"]).read_bytes()
        assert len(data) == asset["size"]
        if asset.get("digest"):
            assert "sha256:" + hashlib.sha256(data).hexdigest() == asset["digest"]
    return verify_bundle(version,dest)


def verify_bundle(version,dest):
    run(sys.executable, str(ROOT / "scripts/verify-release.py"), str(dest))
    exe = dest / f"MOTH.Code_{version}_x64-setup.exe"
    verifier = runpy.run_path(str(ROOT / "scripts/check-release-secrets.py"))
    assert verifier["check_updater_signature"](exe, exe.with_name(exe.name + ".sig"))
    # Authenticate the trusted comment too, including the version required by the installed app.
    lines = base64.b64decode(exe.with_name(exe.name + ".sig").read_text()).decode().splitlines()
    packet = base64.b64decode(lines[1])
    comment = lines[2].removeprefix("trusted comment: ")
    pub_lines = base64.b64decode((ROOT / "app/src-tauri/updater.pub").read_text()).decode().splitlines()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_lines[1])[10:]).verify(
        base64.b64decode(lines[3]), packet[10:] + comment.encode())
    assert f"\tversion:{version}" in comment
    print(f"VERIFIED signed desktop {version}: SHA-256, manifest signature, installer signature and signed version", flush=True)
    return exe, json.loads((dest / f"moth-release-desktop-{version}.json").read_text())


def published_updater_key(version):
    # Release jobs intentionally use shallow checkouts. Read the exact published
    # tag through the authenticated repository API rather than assuming local tags.
    source=json.loads(run("gh","api",f"repos/{REPO}/contents/app/src-tauri/updater.pub?ref=desktop-v{version}",capture_output=True).stdout)
    if source.get('encoding')!='base64':raise AssertionError('Published updater key is not a base64 repository file')
    return base64.b64decode(source['content']).strip()


def probe_cloud(manifest, out):
    server = "https://mothcloud.ddns.net"
    from moth_server.releases import bucket
    eligible = next(f"verify-{i}" for i in range(1000) if bucket(f"verify-{i}", "0.5.4") < 10)
    deferred = next(f"verify-{i}" for i in range(1000) if bucket(f"verify-{i}", "0.5.4") >= 50)
    results = []
    for name, install_id, path in [
        ("health", eligible, "/v1/health"),
        ("eligible-first-stage", eligible, "/v1/updates/desktop/windows/x86_64/0.5.1?channel=stable"),
        ("later-stage", deferred, "/v1/updates/desktop/windows/x86_64/0.5.1?channel=stable"),
        ("latest-relayed-desktop", eligible, "/v1/updates/desktop/windows/x86_64/0.0.0?channel=stable"),
    ]:
        req = urllib.request.Request(f"{server}{path}",
                                     headers={"X-Moth-Install-Id": install_id, "X-Moth-Client": "desktop/0.5.1", "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode()
                result = {"probe": name, "status": r.status, "body": body, "headers": dict(r.headers)}
                if r.status == 200 and "/updates/desktop/" in path:
                    offer = json.loads(body)
                    if offer["version"] == "0.5.4":
                        assert offer["signature"] == manifest["components"]["desktop"]["windows-x86_64"]["signature"]
        except urllib.error.HTTPError as e:
            result = {"probe": name, "status": e.code, "body": e.read().decode()[:2000]}
        except urllib.error.URLError as e:
            result = {"probe": name, "error": str(e)}
        results.append(result)
        print("::notice title=Live Cloud read-only update probe::" + json.dumps(result), flush=True)
    (out / "live-cloud-probe.json").write_text(json.dumps(results, indent=2))


def evaluate(expression):
    import websocket
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
            targets = json.load(r)
    except urllib.error.URLError:
        with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
            targets = json.load(r)
    target = next(t for t in targets if t.get("type") == "page")
    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                assert "error" not in msg and "exceptionDetails" not in msg.get("result", {}), msg
                return msg["result"]["result"].get("value")
    finally:
        ws.close()


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--from-version',default='0.5.1')
    parser.add_argument('--candidate-dir',type=Path)
    args=parser.parse_args()
    assert re.fullmatch(r'\d+\.\d+\.\d+',args.from_version),'Invalid source version'
    old_version=args.from_version
    assert sys.platform == "win32", "Run this native installer test on Windows"
    out = Path(os.environ["RUNNER_TEMP"]) / "published-desktop-test"
    out.mkdir(parents=True, exist_ok=True)
    old, _ = download_release(old_version, out / "old")
    if args.candidate_dir:
        assert old_version=='0.5.9','Candidate upgrade verification starts at the published 0.5.9 release'
        manifest_path=next(args.candidate_dir.glob('moth-release-desktop-*.json'))
        target_version=json.loads(manifest_path.read_text())['version']
        assert re.fullmatch(r'\d+\.\d+\.\d+',target_version)
        shutil.copytree(args.candidate_dir,out/'new',dirs_exist_ok=True)
        new,manifest=verify_bundle(target_version,out/'new')
    else:
        target_version='0.5.4'
        new,manifest=download_release(target_version,out/'new')
    assert published_updater_key(old_version) == (ROOT / "app/src-tauri/updater.pub").read_bytes().strip()
    if not args.candidate_dir:probe_cloud(manifest, out)

    # Isolated TLS trust for the stock production installer. No insecure transport or signature bypass.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False).sign(key, hashes.SHA256()))
    (out / "tls.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (out / "tls.der").write_bytes(cert.public_bytes(serialization.Encoding.DER))
    (out / "tls.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    print('::notice title=Published lifecycle stage::Installing isolated test TLS certificate', flush=True)
    # CurrentUser\Root can display a consent dialog in a noninteractive Windows runner.
    # Hosted Windows runners are administrators: use their isolated machine store, then remove it.
    run("certutil", "-f", "-addstore", "Root", str(out / "tls.der"))
    data = out / "server-data"
    data.mkdir(exist_ok=True)
    (out / "agent.token").write_text("isolated-desktop-test")
    env = {**os.environ, "MOTH_SERVER_DATA_DIR": str(data), "MOTH_SERVER_PUBLIC_URL": "https://localhost:8900",
           "MOTH_AGENT_TOKEN_FILE": str(out / "agent.token"), "MOTH_RELEASE_PUBKEY": (ROOT / "deploy/agent/release-signing.pub").read_text().strip()}
    # Uvicorn factory reads the ordinary server settings, including the isolated data directory.
    log = (out / "server.log").open("w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "moth_server.app:create_app", "--factory", "--port", "8900",
                               "--ssl-certfile", str(out / "tls.pem"), "--ssl-keyfile", str(out / "tls.key")], env=env, stdout=log, stderr=log)
    appdata = Path(os.environ["APPDATA"]) / "dev.mothcode.desktop"
    update_log = appdata / "logs/updates.log"
    try:
        import ssl
        tls = ssl.create_default_context(cafile=str(out / "tls.pem"))
        for _ in range(60):
            try:
                urllib.request.urlopen("https://localhost:8900/v1/health", context=tls, timeout=2).close()
                break
            except (urllib.error.URLError, OSError): time.sleep(1)
        # Trust the isolated CA for the helper; clients still enforce HTTPS and the production keys.
        os.environ["SSL_CERT_FILE"] = str(out / "tls.pem")
        harness = runpy.run_path(str(ROOT / "scripts/desktop-update-harness.py"))
        print(f'::notice title=Published lifecycle stage::Registering verified {target_version} on the isolated server', flush=True)
        harness["register"]("https://localhost:8900", data, out / "agent.token", out / "new", ssl_context=tls)
        # Isolated fixture only: offer the authentic release to every test install ID.
        # This changes no signed bytes or signature checks and never touches production rollout.
        with sqlite3.connect(data / 'moth-server.db') as db:
            db.execute("UPDATE software_releases SET status='complete', rollout_percent=100 WHERE component='desktop' AND version=?",(target_version,))
        served = data / "storage/software/desktop" / target_version / new.name
        # Corrupt an already relayed installer: the stock client's independent minisign check
        # must reject it, even though the release metadata and signature are authentic.
        with served.open("r+b") as f:
            f.seek(-1, 2)
            last = f.read(1)
            f.seek(-1, 2)
            f.write(bytes([last[0] ^ 1]))
        from moth_server.releases import bucket
        install_id = next(f"published-ci-{i}" for i in range(1000) if bucket(f"published-ci-{i}", target_version) < 10)
        home = out / "backend-home"
        home.mkdir(exist_ok=True)
        app_env = {**os.environ, "MOTH_HOME": str(home)}
        print(f'::notice title=Published lifecycle stage::Installing the original {old_version} desktop', flush=True)
        # An installer-started app must also use the isolated backend home.
        run(str(old), "/S", timeout=600, env=app_env)
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall") as parent:
            for i in range(winreg.QueryInfoKey(parent)[0]):
                sub = winreg.EnumKey(parent, i)
                with winreg.OpenKey(parent, sub) as reg:
                    try:
                        if winreg.QueryValueEx(reg, "DisplayName")[0] == "MOTH Code":
                            reg_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{sub}"
                            folder = Path(winreg.QueryValueEx(reg, "UninstallString")[0].strip('"')).parent
                            break
                    except FileNotFoundError: pass
        def installed_version():
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as reg:
                return winreg.QueryValueEx(reg, "DisplayVersion")[0]
        assert installed_version() == old_version
        exe = next(p for p in folder.glob("*.exe") if not p.name.lower().startswith("uninstall"))
        subprocess.run(['taskkill', '/F', '/T', '/IM', exe.name], capture_output=True, timeout=30)
        appdata.mkdir(exist_ok=True)
        update_log.unlink(missing_ok=True)  # generated runner logs from a preceding isolated test
        marker = appdata / "workspace-preservation-marker.txt"
        marker.write_text("keep original workspace")
        accounts = appdata / "accounts.json"
        accounts.write_text(json.dumps({"active": None, "accounts": [{"server": "https://localhost:8900", "username": "preserved-ci-account", "last_used": 0}]}))
        (home / "workspace.txt").write_text("keep workspace content")
        print('::notice title=Published lifecycle stage::Starting original desktop and setting the isolated Cloud address', flush=True)
        desktop_log = (out / 'desktop-process.log').open('w')
        desktop = subprocess.Popen([str(exe)], env=app_env, stdout=desktop_log, stderr=desktop_log)
        WindowsUI = runpy.run_path(str(ROOT / 'scripts/windows-desktop-ui.py'))['WindowsUI']
        ui = WindowsUI(desktop.pid)
        ui.configure_cloud('https://localhost:8900')
        # Do not force-kill a browser while it is committing the selected Cloud address.
        # Keep the real process alive through negative verification and the eventual normal close.
        if not update_log.exists() or 'update error:' not in update_log.read_text():
            ui.check_update(wait_for_enabled=False)
        print('::notice title=Published lifecycle stage::Waiting for tampered-download rejection', flush=True)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if update_log.exists() and "update error:" in update_log.read_text(): break
            time.sleep(2)
        else: raise AssertionError(f"Stock {old_version} did not report the tampered installer failure")
        assert "signature" in update_log.read_text().lower(), update_log.read_text()
        assert installed_version() == old_version, "an invalid signature must never install"
        print('::notice title=Published lifecycle stage::Tampered update rejected; restoring the authentic installer', flush=True)
        shutil.copyfile(new, served)
        ui.check_update()
        print('::notice title=Published lifecycle stage::Valid update check requested; waiting for verification', flush=True)
        deadline = time.monotonic() + 480
        while time.monotonic() < deadline:
            if update_log.exists() and f"downloaded and verified {target_version}" in update_log.read_text(): break
            time.sleep(2)
        else: raise AssertionError(f"Stock {old_version} did not detect, download and verify signed {target_version}")
        assert installed_version() == old_version, "must wait for close, not install during download"
        # WM_CLOSE exercises the installed app's actual onCloseRequested handler.
        print('::notice title=Published lifecycle stage::Closing original desktop to install its verified update', flush=True)
        run("powershell", "-NoProfile", "-Command", f"Get-Process | Where-Object {{ $_.Path -eq '{exe}' }} | ForEach-Object {{ $_.CloseMainWindow() | Out-Null }}")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and installed_version() != target_version: time.sleep(2)
        assert installed_version() == target_version, "close did not install the verified update"
        # Installer may relaunch; start it if needed, then require a success report from the app.
        time.sleep(10)
        try: ui = WindowsUI(desktop.pid, timeout=5)
        except Exception:
            desktop = subprocess.Popen([str(exe)], env=app_env)
            ui = WindowsUI(desktop.pid)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with sqlite3.connect(data / "moth-server.db") as db:
                reports = db.execute("SELECT ok FROM update_reports WHERE component='desktop' AND from_version=? AND to_version=?",(old_version,target_version)).fetchall()
            if (1,) in reports: break
            time.sleep(2)
        assert (0,) in reports and (1,) in reports, reports
        assert marker.read_text() == "keep original workspace"
        assert (home / "workspace.txt").read_text() == "keep workspace content"
        assert json.loads(accounts.read_text())["accounts"][0]["username"] == "preserved-ci-account"
        ui.click('Settings')
        ui.optional_tab('Account')
        assert ui.text_value('MOTH Cloud server address') == 'https://localhost:8900'
        evidence = {'completed': True, 'from_version': old_version, 'to_version': installed_version(),
                    'production_signatures': True, 'tampered_installer_rejected': True,
                    'verified_download_before_close': True, 'installed_on_close': True,
                    'restart_report_received': True, 'settings_accounts_workspaces_preserved': True}
        (out / 'evidence.json').write_text(json.dumps(evidence, indent=2))
        print('::notice title=Published desktop lifecycle completed::' + json.dumps(evidence), flush=True)
        print(f"PASS: actual signed {old_version} -> {target_version} detected, downloaded, signature-verified, installed on close, restarted and reported success; data preserved", flush=True)
    finally:
        # Semantic diagnostics stay available through the GitHub checks API when artifact/log
        # download hosts are unavailable. Never include credentials or editable field values.
        observations = {'log_exists': update_log.exists()}
        if update_log.exists():
            observations['updater_log'] = update_log.read_text(errors='replace')[-2000:]
        try:
            observations['ui_status'] = [c.element_info.name for c in ui.root.descendants(control_type='Text')
                                         if any(word in c.element_info.name.lower() for word in
                                                ('update', 'checking', 'ready', 'error', 'up to date', 'signature', 'verified', 'connected', 'server address'))][-30:]
            observations['address_matches_fixture'] = ui.text_value('MOTH Cloud server address') == 'https://localhost:8900'
        except Exception:
            pass
        try:
            requests = re.findall(r'"(GET|POST|PUT|DELETE) ([^ ?]+)(?:\?[^ ]*)? HTTP/[^\"]+" (\d+)',
                                  (out / 'server.log').read_text(errors='replace'))
            observations['request_counts'] = [list(key) + [count] for key, count in collections.Counter(requests).most_common(40)]
            with sqlite3.connect(data / 'moth-server.db') as db:
                observations['reports'] = db.execute("SELECT from_version,to_version,ok,error FROM update_reports WHERE component='desktop'").fetchall()[-10:]
        except Exception:
            pass
        print('::notice title=Published desktop update observations::' + json.dumps(observations), flush=True)
        server.terminate()
        server.wait(timeout=30)
        log.close()
        if update_log.exists(): shutil.copy(update_log, out / "updates.log")
        run("certutil", "-f", "-delstore", "Root", cert.fingerprint(hashes.SHA1()).hex())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"::error title=Published desktop update failed::{type(exc).__name__}: {exc}", flush=True)
        raise
