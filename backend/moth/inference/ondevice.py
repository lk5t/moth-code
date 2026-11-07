"""MOTH on this computer: download the model MOTH Cloud serves and run it locally (0.5.2).

The download is verified end to end before anything is loaded:

1. for official releases, the signed release manifest must verify with the MOTH release key built into
   MOTH Code, and name the same weights SHA-256 as the server;
2. the package archive must match the SHA-256 the server reports (resumable download);
3. the extracted package is validated (weights hash, configuration, tokenizer) like any MOTH package.

Answers are then generated on this computer — no network, no metering. Chat uses the local model when
the user chose "Answer on this computer", or automatically when MOTH Cloud cannot be reached.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

# The MOTH release public key (same as deploy/agent/release-signing.pub). Only releases signed with the
# matching private key, which exists only in the release workflow's secrets, verify.
RELEASE_PUBKEY = "JMITaZ0m8unDwq44iP45h7i7kjbZmgTg8izA3KNk+jQ="


class OnDeviceError(RuntimeError):
    pass


def _verify_ed25519(pub_b64: str, data: bytes, sig_b64: str) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(base64.b64decode(sig_b64), data)
        return True
    except (InvalidSignature, ValueError):
        return False
    except ImportError:  # pragma: no cover - cryptography is a dependency
        return False


class OnDevice:
    def __init__(self, models_dir: Path, account: Callable[[], dict | None], publish: Callable[[str, dict], None],
                 http_factory: Callable[[], httpx.Client] | None = None, pubkey: str = RELEASE_PUBKEY):
        self.root = Path(models_dir) / "on-device"
        self.root.mkdir(parents=True, exist_ok=True)
        self.account = account
        self.publish = publish
        self.http_factory = http_factory or (lambda: httpx.Client(timeout=60.0, follow_redirects=True))
        self.pubkey = pubkey
        self.state: dict[str, Any] = {"downloading": False, "progress": None, "error": None}
        self._lock = threading.Lock()
        self.engine = None

    # ---- what is installed ---------------------------------------------------------------------------
    def installed(self) -> dict[str, Any] | None:
        cur = self.root / "current.json"
        if not cur.exists():
            return None
        info = json.loads(cur.read_text())
        return info if (self.root / info["dir"] / "manifest.json").exists() else None

    def status(self) -> dict[str, Any]:
        inst = self.installed()
        return {**self.state, "installed": inst, "loaded": bool(self.engine and self.engine.available())}

    # ---- download --------------------------------------------------------------------------------------
    def _api(self) -> tuple[str, str]:
        acct = self.account() or {}
        if not acct.get("token") or not acct.get("server_url"):
            raise OnDeviceError("Sign in to MOTH Cloud to download MOTH.")
        return acct["server_url"].rstrip("/"), acct["token"]

    def start_download(self) -> None:
        with self._lock:
            if self.state["downloading"]:
                return
            self.state.update(downloading=True, progress=0.0, error=None)
        threading.Thread(target=self._download_safe, daemon=True, name="ondevice-download").start()

    def _download_safe(self) -> None:
        try:
            self.download()
        except Exception as e:  # noqa: BLE001 - reported to the app
            self.state["error"] = str(e) or type(e).__name__
            self.publish("ondevice", {"kind": "error", "error": self.state["error"]})
        finally:
            self.state.update(downloading=False, progress=None)
            self.publish("ondevice", {"kind": "status", **self.status()})

    def download(self) -> dict[str, Any]:
        base, token = self._api()
        h = {"Authorization": f"Bearer {token}"}
        with self.http_factory() as http:
            r = http.get(base + "/v1/models/deployed/package-info", headers=h)
            if r.status_code == 404:
                raise OnDeviceError("MOTH Cloud has no model deployed yet.")
            r.raise_for_status()
            info = r.json()
            official = False
            signed_by_server = False
            if info.get("server_manifest") and not info.get("release_manifest"):
                # a model this MOTH Cloud produced itself: signed with the server's model key, pinned here
                raw = base64.b64decode(info["server_manifest"])
                key = self._trusted_key(base, info.get("server_key", ""))
                if not _verify_ed25519(key, raw, info.get("server_signature", "")):
                    raise OnDeviceError("The model's manifest is not signed by this MOTH Cloud's model key.")
                if json.loads(raw).get("weights_sha256") != info["weights_sha256"]:
                    raise OnDeviceError("The model on MOTH Cloud does not match its signed manifest.")
                signed_by_server = True
            if info.get("release_manifest"):
                raw = base64.b64decode(info["release_manifest"])
                if not _verify_ed25519(self.pubkey, raw, info.get("release_signature", "")):
                    raise OnDeviceError("The model's release signature does not verify: it was not published by MOTH.")
                m = json.loads(raw)
                if (m.get("model") or {}).get("weights_sha256") != info["weights_sha256"]:
                    raise OnDeviceError("The model on MOTH Cloud does not match its signed release.")
                official = True
            inst = self.installed()
            if inst and inst.get("weights_sha256") == info["weights_sha256"]:
                return inst  # already installed: nothing is downloaded again
            part = self.root / f"download-{info['version']}.tar.part"
            have = part.stat().st_size if part.exists() else 0
            hdr = dict(h)
            if have:
                hdr["Range"] = f"bytes={have}-"
            with http.stream("GET", base + "/v1/models/deployed/package", headers=hdr) as resp:
                if resp.status_code not in (200, 206):
                    raise OnDeviceError(f"download failed (HTTP {resp.status_code})")
                mode = "ab" if resp.status_code == 206 else "wb"
                done = have if mode == "ab" else 0
                with open(part, mode) as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        self.state["progress"] = round(done / max(1, int(info["size"])), 4)
        digest = hashlib.sha256()
        with open(part, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != info["package_sha256"]:
            part.unlink(missing_ok=True)
            raise OnDeviceError("The downloaded model does not match its SHA-256; it was deleted. Try again.")
        dest = self.root / f"v{info['version']}-{info['weights_sha256'][:12]}"
        tmp = dest.with_name(dest.name + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        with tarfile.open(part) as tar:
            for mem in tar.getmembers():
                if mem.issym() or mem.islnk() or mem.name.startswith("/") or ".." in Path(mem.name).parts \
                        or not mem.isfile() or not mem.name.startswith("model/"):
                    raise OnDeviceError("the model archive contains unexpected entries")
                target = tmp / Path(mem.name).name
                with tar.extractfile(mem) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        from moth.model.package import inspect_package

        check = inspect_package(tmp, deep=True)
        if not check["ok"] or check["info"]["sha256"] != info["weights_sha256"]:
            shutil.rmtree(tmp, ignore_errors=True)
            raise OnDeviceError("the model package failed validation: " + "; ".join(check["problems"] or ["hash"]))
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
        part.unlink(missing_ok=True)
        old = self.installed()
        cur = {"dir": dest.name, "version": info["version"], "display_name": info.get("display_name"),
               "model_version": info.get("model_version"), "params": info.get("params"),
               "weights_sha256": info["weights_sha256"], "official": official, "signed_by_server": signed_by_server,
               "installed_at": time.time()}
        (self.root / "current.json").write_text(json.dumps(cur, indent=1))
        if old and old["dir"] != dest.name:
            shutil.rmtree(self.root / old["dir"], ignore_errors=True)
        self.unload()
        return cur

    def _trusted_key(self, server: str, offered: str) -> str:
        """Trust on first use: the first key a server presents is pinned; a different key later is refused."""
        f = self.root / "trusted-server-keys.json"
        try:
            keys = json.loads(f.read_text())
        except (OSError, ValueError):
            keys = {}
        if server not in keys and offered:
            keys[server] = offered
            f.write_text(json.dumps(keys, indent=1))
        if keys.get(server) != offered:
            raise OnDeviceError("This MOTH Cloud now presents a different model-signing key than before; the "
                                "download was refused. Ask the Owner whether the server was reinstalled.")
        return keys[server]

    # ---- inference -------------------------------------------------------------------------------------
    def ensure_loaded(self):
        from moth.inference.local import LocalInference

        inst = self.installed()
        if inst is None:
            raise OnDeviceError("MOTH is not downloaded to this computer yet.")
        if self.engine is None or self.engine.model_id != inst["dir"]:
            eng = LocalInference(self.root)
            eng.load(inst["dir"], "auto")
            self.engine = eng
        return self.engine

    def unload(self) -> None:
        if self.engine is not None:
            self.engine.unload()
        self.engine = None

    def remove(self) -> None:
        self.unload()
        inst = self.installed()
        if inst:
            shutil.rmtree(self.root / inst["dir"], ignore_errors=True)
        (self.root / "current.json").unlink(missing_ok=True)
