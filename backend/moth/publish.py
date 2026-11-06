"""Desktop side of model publishing (Owner only): Select → Validate → Upload → (server) Evaluate →
Publish → Deploy.

* **Validate** runs locally with ``moth.model.package.inspect_package`` before a single byte is sent.
* **Upload** sends an uncompressed tar of the package to MOTH Cloud in chunks with per-chunk
  SHA-256, retries with exponential backoff, and resumes after interruptions — including an app
  restart, because the upload state is persisted in the local database.
* After the upload completes the server validates and **evaluates** the model; this class follows
  the release until it is published, needs attention, or failed, and reports the server's reason.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from moth import __version__
from moth.model.package import inspect_package

RETRY_DELAYS = (1, 2, 4, 8, 16, 30, 30, 60)
POLL_SECONDS = 3.0
SETTINGS_KEY = "publish_jobs"


class PublishError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Publisher:
    def __init__(self, models_dir: Path, cache_dir: Path, db, account: Callable[[], dict | None],
                 http: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        self.models_dir, self.cache_dir, self.db, self.account = Path(models_dir), Path(cache_dir), db, account
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))
        self.sleep = sleep
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self.state: dict[str, dict[str, Any]] = {}
        for job in (db.get_setting(SETTINGS_KEY) or {}).values():
            stage = job.get("stage", "uploading")
            # a paused upload resumes from the chunks the server already has
            self.state[job["model_id"]] = {**job, "stage": "uploading" if stage == "paused" else stage}

    # ---- helpers ---------------------------------------------------------------------------------
    def _owner(self) -> dict:
        acct = self.account() or {}
        if not acct.get("token") or not acct.get("server_url"):
            raise PublishError(401, "Sign in to MOTH Cloud as the Owner to publish models.")
        if (acct.get("user") or {}).get("role") != "owner":
            raise PublishError(403, "Only the Owner can publish models to MOTH Cloud.")
        return acct

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        acct = self._owner()
        headers = {"Authorization": f"Bearer {acct['token']}", "X-Moth-Client": f"desktop/{__version__}",
                   **kw.pop("headers", {})}
        return self.http.request(method, acct["server_url"].rstrip("/") + path, headers=headers, **kw)

    def _call(self, method: str, path: str, retries: bool = True, job: str | None = None, **kw) -> httpx.Response:
        """Request with retries on network errors and 5xx; 4xx are returned to the caller. With ``job``,
        the job shows a short "interrupted — retrying" notice while it waits."""
        last: Exception | None = None
        for delay in (*RETRY_DELAYS, None) if retries else (None,):
            try:
                r = self._req(method, path, **kw)
                if r.status_code < 500:
                    if job and self.state.get(job, {}).get("notice"):
                        self._update(job, notice=None)
                    return r
                last = PublishError(r.status_code, _detail(r))
            except httpx.HTTPError as e:
                last = e  # network drop, tunnel reset, timeout: retried with backoff
            if delay is None:
                break
            if job:
                why = str(last) if isinstance(last, PublishError) else "the connection to MOTH Cloud dropped"
                self._update(job, notice=f"{why.split('. ')[0].rstrip('.')} — retrying in {delay} s")
            self.sleep(delay)
        if isinstance(last, PublishError):
            raise last
        raise PublishError(503, "MOTH Cloud could not be reached after several attempts "
                                f"({type(last).__name__}). The upload is paused and resumes automatically.")

    def _persist(self) -> None:
        keep = {k: {f: v[f] for f in ("model_id", "upload_id", "tar", "sha256", "size", "name", "release_version",
                                      "stage", "server_url") if f in v}
                for k, v in self.state.items() if v.get("stage") in ("uploading", "processing", "evaluating", "paused")}
        self.db.set_setting(SETTINGS_KEY, keep)

    def _update(self, model_id: str, **values: Any) -> None:
        with self._lock:
            self.state.setdefault(model_id, {"model_id": model_id}).update(values, updated_at=time.time())
            self._persist()

    # ---- steps ----------------------------------------------------------------------------------
    def validate(self, model_id: str) -> dict:
        d = self.models_dir / model_id
        if not d.is_dir():
            raise PublishError(404, "That model package does not exist on this computer.")
        return inspect_package(d, deep=True)

    def package(self, model_id: str) -> tuple[Path, str]:
        """An uncompressed tar of the package, cached by content (weights don't compress)."""
        d = self.models_dir / model_id
        manifest = json.loads((d / "manifest.json").read_text())
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out = self.cache_dir / f"{model_id}-{manifest['sha256'][:16]}.tar"
        if not out.exists():
            tmp = out.with_suffix(".tar.partial")
            with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tar:
                for name in ("manifest.json", "config.json", "tokenizer.json", "model.pt"):
                    info = tar.gettarinfo(str(d / name), f"{model_id}/{name}")
                    info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                    with open(d / name, "rb") as f:
                        tar.addfile(info, f)
            tmp.rename(out)
        return out, _sha256(out)

    def start(self, model_id: str) -> dict:
        """Validate, then begin (or resume) the upload. Raises PublishError(428) when MOTH Cloud wants
        the Owner's password again — the UI asks and calls start() again."""
        acct = self._owner()
        cur = self.state.get(model_id)
        if cur and cur.get("stage") in ("validating", "packaging", "uploading", "processing", "evaluating") and \
                model_id in self._threads and self._threads[model_id].is_alive():
            return cur
        self._update(model_id, stage="validating", error=None, progress=0.0)
        check = self.validate(model_id)
        if not check["ok"]:
            self._update(model_id, stage="failed", error="Validation failed: " + "; ".join(check["problems"]),
                         problems=check["problems"])
            raise PublishError(422, "This model can't be published: " + "; ".join(check["problems"]))
        self._update(model_id, stage="packaging", info=check["info"])
        tar, sha = self.package(model_id)
        manifest = json.loads((self.models_dir / model_id / "manifest.json").read_text())
        r = self._call("POST", "/v1/admin/models/uploads", retries=False,
                       json={"name": manifest.get("name") or model_id, "size": tar.stat().st_size, "sha256": sha,
                             "manifest": manifest})
        if r.status_code == 428:
            self._update(model_id, stage="idle")
            raise PublishError(428, _detail(r))
        if r.status_code >= 400:
            self._update(model_id, stage="failed", error=_detail(r))
            raise PublishError(r.status_code, _detail(r))
        body = r.json()
        if body.get("duplicate"):
            rel = body["release"]
            self._update(model_id, stage=_stage_for(rel["status"]), release_version=rel["version"],
                         release_status=rel["status"], progress=1.0, error=None, duplicate=True,
                         message=body.get("message"))
            return self.state[model_id]
        up = body["upload"]
        self._update(model_id, stage="uploading", upload_id=up["id"], tar=str(tar), sha256=sha, size=up["size"],
                     name=up["name"], release_version=up["release_version"], server_url=acct["server_url"],
                     progress=len(up["received"]) / max(1, up["chunks"]), resumed=bool(body.get("resumed")))
        self._spawn(model_id)
        return self.state[model_id]

    def start_auto_resume(self, every_s: float = 60.0) -> None:
        """Retry paused uploads in the background (e.g. after a tunnel or network outage)."""
        def loop() -> None:
            while True:
                time.sleep(every_s)
                try:
                    acct = self.account() or {}
                    if acct.get("token") and (acct.get("user") or {}).get("role") == "owner":
                        self.resume_pending()
                except Exception:  # noqa: BLE001 — never let the loop die
                    pass

        threading.Thread(target=loop, name="publish-auto-resume", daemon=True).start()

    def resume_pending(self) -> list[str]:
        """Continue uploads that were interrupted (e.g. the app was closed)."""
        resumed = []
        for model_id, job in list(self.state.items()):
            if job.get("stage") in ("uploading", "processing", "evaluating", "paused") and model_id not in self._threads:
                acct = self.account() or {}
                if acct.get("server_url") and acct.get("server_url") == job.get("server_url"):
                    self._spawn(model_id)
                    resumed.append(model_id)
        return resumed

    def _spawn(self, model_id: str) -> None:
        t = threading.Thread(target=self._run, args=(model_id,), name=f"publish-{model_id}", daemon=True)
        self._threads[model_id] = t
        t.start()

    def _run(self, model_id: str) -> None:
        try:
            job = self.state[model_id]
            if job["stage"] in ("uploading", "paused"):
                self._update(model_id, stage="uploading", error=None)
                self._upload(model_id)
            self._follow(model_id)
        except PublishError as e:
            self._update(model_id, stage="failed" if e.status not in (401, 503) else "paused", error=str(e))
        except Exception as e:  # noqa: BLE001
            self._update(model_id, stage="paused", error=f"Upload interrupted: {e}. It will resume automatically.")
        finally:
            self._threads.pop(model_id, None)

    def _upload(self, model_id: str) -> None:
        job = self.state[model_id]
        tar = Path(job["tar"])
        if not tar.exists() or _sha256(tar) != job["sha256"]:
            raise PublishError(409, "The local upload file changed or was removed; start publishing again.")
        r = self._call("GET", f"/v1/admin/models/uploads/{job['upload_id']}", job=model_id)
        if r.status_code == 404:
            raise PublishError(404, "The interrupted upload expired on MOTH Cloud; start publishing again.")
        status = r.json()
        cs, missing = status["chunk_size"], status["missing"]
        done = status["chunks"] - len(missing)
        with open(tar, "rb") as f:
            for i in missing:
                f.seek(i * cs)
                chunk = f.read(cs)
                r = self._call("PUT", f"/v1/admin/models/uploads/{job['upload_id']}/chunks/{i}", content=chunk,
                               job=model_id, headers={"X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest(),
                                                      "Content-Type": "application/octet-stream"})
                if r.status_code == 422:  # damaged in transit: one more try, then give up clearly
                    r = self._call("PUT", f"/v1/admin/models/uploads/{job['upload_id']}/chunks/{i}", content=chunk,
                                   headers={"X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest(),
                                            "Content-Type": "application/octet-stream"})
                if r.status_code >= 400:
                    raise PublishError(r.status_code, _detail(r))
                done += 1
                self._update(model_id, progress=done / status["chunks"])
        self._update(model_id, stage="processing", progress=1.0)
        r = self._call("POST", f"/v1/admin/models/uploads/{job['upload_id']}/complete", job=model_id, timeout=600)
        if r.status_code >= 400:
            raise PublishError(r.status_code, _detail(r))
        rel = r.json()["release"]
        self._update(model_id, stage=_stage_for(rel["status"]), release_version=rel["version"],
                     release_status=rel["status"])
        Path(job["tar"]).unlink(missing_ok=True)

    def _follow(self, model_id: str, timeout_s: float = 3 * 3600) -> None:
        """Track the server-side evaluation until the release settles."""
        start = time.time()
        while time.time() - start < timeout_s:
            job = self.state[model_id]
            if not job.get("release_version"):
                return
            r = self._call("GET", "/v1/admin/models")
            rel = next((x for x in r.json().get("releases", []) if x["version"] == job["release_version"]), None)
            if not rel:
                raise PublishError(404, "The release disappeared from MOTH Cloud.")
            stage = _stage_for(rel["status"])
            ev = rel.get("evaluation") or {}
            self._update(model_id, stage=stage, release_status=rel["status"], error=rel.get("error"),
                         evaluation={k: ev.get(k) for k in ("passed", "reason", "score", "dataset", "guidance",
                                                            "tokens_per_second", "note")})
            if stage not in ("processing", "evaluating"):
                return
            self.sleep(POLL_SECONDS)

    def status(self) -> list[dict]:
        out = []
        for v in self.state.values():
            item = {k: val for k, val in v.items() if k not in ("tar",)}
            item["active"] = v["model_id"] in self._threads
            out.append(item)
        return out


def _stage_for(server_status: str) -> str:
    return {"uploading": "uploading", "uploaded": "evaluating", "evaluating": "evaluating", "evaluated": "evaluated",
            "published": "published", "deploying": "published", "deployed": "deployed", "failed": "failed"}.get(
        server_status, server_status)


def _detail(r: httpx.Response) -> str:
    """A readable error, also for responses from a proxy or tunnel in front of MOTH Cloud (HTML pages)."""
    code = r.status_code
    try:
        d = r.json().get("detail")
        if d:
            return d if isinstance(d, str) else json.dumps(d)
    except ValueError:
        pass
    if code == 413:
        return ("An upload chunk was rejected as too large (HTTP 413) by a proxy in front of MOTH Cloud. Allow request "
                "bodies of at least 16 MB there (the MOTH Caddyfile allows 64 MB).")
    if code in (502, 503, 504, 520, 521, 522, 523, 524, 530):
        return (f"The connection to MOTH Cloud was interrupted (HTTP {code} from the proxy or tunnel in front of the "
                "server). The upload resumes automatically from the last completed chunk.")
    return f"MOTH Cloud answered with HTTP {code}."
