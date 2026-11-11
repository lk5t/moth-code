"""Hybrid inference settings, community participation and personal learning routes."""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from moth.community.resources import ParticipationSettings, may_contribute
from moth.inference.router import InferenceRouter, InferenceSettings
from moth.jobs import Job
from moth.server.services import Services


class ConsentIn(BaseModel):
    granted: bool


class PersonalExportIn(BaseModel):
    project_id: int | None = None
    name: str = "personal-tasks"


# Resolve postponed annotations in module globals: FastAPI otherwise treats a function-local
# model name as an unresolved query parameter, producing the reported query.body error.
class ParticipantIn(BaseModel):
    enabled: bool


class LocalResetIn(BaseModel):
    confirmation: str


class OnDeviceIn(BaseModel):
    answer_on_device: bool


def register(app: FastAPI, svc: Services, deps) -> None:
    jobs = svc.extras["jobs"]

    def inference_settings() -> InferenceSettings:
        return InferenceSettings.from_dict(svc.db.get_setting("inference"))

    def consented(project_id: int | None) -> bool:
        return svc.extras["account_scope"].consented(project_id)

    router = InferenceRouter(inference_settings, account=lambda: svc.extras.get("account"), consent=consented)
    svc.extras["inference_router"] = router

    # ---- this computer in the MOTH training network (0.5.3 unified training) ------------------------------
    from moth.community.participant import Participant, ParticipantError

    participant = Participant(svc.paths.home, account=lambda: svc.extras.get("account"),
                              get_setting=svc.db.get_setting, set_setting=svc.db.set_setting, publish=svc.bus.publish)
    svc.extras["participant"] = participant
    try:
        participant.start()  # resumes contributing if it was switched on (checkpointed job continues)
    except Exception:  # noqa: BLE001 - never blocks the app from starting
        pass

    @app.get("/api/participant", dependencies=deps)
    def participant_status():
        return participant.status()

    @app.put("/api/participant", dependencies=deps)
    def participant_set(body: ParticipantIn):
        try:
            return participant.enable() if body.enabled else participant.disable()
        except ParticipantError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/participant/{action}", dependencies=deps)
    def participant_control(action: str):
        try:
            return participant.control(action)
        except ParticipantError as e:
            raise HTTPException(409, str(e)) from None

    # ---- Genesis Reset, this computer's part: native AI data MOTH Code itself stored -----------------------
    # Deletes only MOTH Code's own model/training folders and training tables. Projects, conversations,
    # settings, the account session and the worker credential are never touched.
    LOCAL_NATIVE = {"Model packages": lambda: svc.paths.models, "Training runs and checkpoints": lambda: svc.paths.runs,
                    "Prepared datasets": lambda: svc.paths.datasets, "Tokenizers": lambda: svc.paths.tokenizers,
                    "Training-network cache": lambda: svc.paths.community,
                    "Contributed job checkpoints": lambda: svc.paths.home / "participant" / "jobs",
                    "Upload staging": lambda: svc.paths.home / "cache" / "publish"}

    def local_native_inventory() -> dict[str, Any]:
        rows = []
        for label, where in LOCAL_NATIVE.items():
            root = where()
            files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()] if root.is_dir() else []
            rows.append({"category": label, "files": len(files), "bytes": sum(p.stat().st_size for p in files)})
        running = [j.title for j in jobs.jobs.values() if j.status == "running"]
        return {"categories": rows, "files": sum(r["files"] for r in rows), "bytes": sum(r["bytes"] for r in rows),
                "training_runs": svc.db.one("SELECT COUNT(*) AS n FROM training_runs")["n"], "running_jobs": running,
                "contributing": bool(participant.status().get("running")), "confirmation": "RESET GENESIS"}

    @app.get("/api/native-ai", dependencies=deps)
    def native_ai_inventory():
        return local_native_inventory()

    @app.post("/api/native-ai/reset", dependencies=deps)
    def native_ai_reset(body: LocalResetIn):
        import shutil

        if body.confirmation != "RESET GENESIS":
            raise HTTPException(422, "Type the exact confirmation: RESET GENESIS")
        inv = local_native_inventory()
        if inv["running_jobs"]:
            raise HTTPException(409, "Stop the running training job on this computer first: " + ", ".join(inv["running_jobs"]))
        was_contributing = bool(participant.status().get("enabled"))
        participant.stop()  # checkpoint and stop the contributed job before its files are removed
        ondevice.unload()
        svc.db.set_setting("ondevice", {"answer_on_device": False})
        for where in LOCAL_NATIVE.values():
            root = where()
            if root.is_symlink():
                raise HTTPException(409, f"{root} is a link; it was not followed and nothing in it was deleted")
            if root.is_dir():
                shutil.rmtree(root)
        svc.paths.ensure()
        svc.db.execute("DELETE FROM training_metrics")
        svc.db.execute("DELETE FROM training_runs")
        svc.db.log_activity("training", "Genesis Reset: native AI data on this computer was deleted")
        if was_contributing:
            participant.start()
        after = local_native_inventory()
        return {"deleted_files": inv["files"], "deleted_bytes": inv["bytes"], "remaining_files": after["files"]}

    # ---- MOTH on this computer (0.5.2) ----------------------------------------------------------------
    from moth.inference.ondevice import OnDevice, OnDeviceError

    ondevice = OnDevice(svc.paths.models, account=lambda: svc.extras.get("account"), publish=svc.bus.publish)
    svc.extras["ondevice"] = ondevice

    @app.get("/api/ondevice", dependencies=deps)
    def ondevice_status():
        return {**ondevice.status(), "answer_on_device": bool((svc.db.get_setting("ondevice") or {}).get("answer_on_device"))}

    @app.post("/api/ondevice/download", dependencies=deps)
    def ondevice_download():
        try:
            ondevice._api()
        except OnDeviceError as e:
            raise HTTPException(401, str(e)) from None
        ondevice.start_download()
        return ondevice.status()

    @app.put("/api/ondevice/settings", dependencies=deps)
    def ondevice_settings(body: OnDeviceIn):
        if body.answer_on_device and not ondevice.installed():
            raise HTTPException(409, "Download MOTH to this computer first.")
        svc.db.set_setting("ondevice", {"answer_on_device": body.answer_on_device})
        return ondevice_status()

    @app.delete("/api/ondevice", dependencies=deps)
    def ondevice_remove():
        ondevice.remove()
        svc.db.set_setting("ondevice", {"answer_on_device": False})
        return ondevice_status()

    # ---- MOTH Cloud status & per-workspace consent -----------------------------------------------
    @app.get("/api/cloud/status", dependencies=deps)
    def cloud_status():
        return router.status()

    @app.get("/api/projects/{pid}/cloud-consent", dependencies=deps)
    def get_consent(pid: int):
        svc.project(pid)
        return {"granted": consented(pid)}

    @app.put("/api/projects/{pid}/cloud-consent", dependencies=deps)
    def set_consent(pid: int, body: ConsentIn):
        project = svc.project(pid)
        if body.granted and not (svc.extras.get('account') or {}).get('token'):
            raise HTTPException(401,'Sign in before approving project sharing.')
        svc.extras['account_scope'].consent(pid,body.granted)
        svc.db.log_activity("cloud", f"{'Allowed' if body.granted else 'Revoked'} MOTH Cloud access for {project['name']}", pid)
        return {"granted": body.granted}

    # ---- Owner tools: Select → Validate → Upload → (cloud) Evaluate → Publish → Deploy -------------
    from moth.publish import PublishError, Publisher

    publisher = Publisher(svc.paths.models, svc.paths.home / "cache" / "publish", svc.db,
                          account=lambda: svc.extras.get("account"))
    svc.extras["publisher"] = publisher
    publisher.start_auto_resume()

    def owner_only() -> None:
        acct = svc.extras.get("account") or {}
        if (acct.get("user") or {}).get("role") != "owner":
            raise HTTPException(403, "Only the signed-in Owner can publish models to MOTH Cloud.")

    @app.get("/api/publish", dependencies=deps)
    def publish_overview():
        from moth.model.registry import list_models
        from moth.training.checkpoint import latest_checkpoint

        owner_only()
        runs = []
        if svc.paths.runs.exists():
            for rd in sorted(svc.paths.runs.iterdir()):
                ck = rd / "checkpoints"
                best, latest = ck / "best.pt", latest_checkpoint(rd)
                if best.exists() or latest:
                    runs.append({"run": rd.name, "best": best.exists(), "latest": latest.name if latest else None})
        return {"models": list_models(svc.paths.models), "runs": runs, "jobs": publisher.status()}

    @app.post("/api/publish/{model_id}/validate", dependencies=deps)
    def publish_validate(model_id: str):
        owner_only()
        try:
            return publisher.validate(model_id)
        except PublishError as e:
            raise HTTPException(e.status, str(e)) from None

    @app.post("/api/models/{model_id}/publish", dependencies=deps)
    def publish_model(model_id: str):
        owner_only()
        try:
            job = publisher.start(model_id)
        except PublishError as e:
            raise HTTPException(e.status, str(e)) from None
        svc.db.log_activity("model", f"Publishing {model_id} to MOTH Cloud (release v{job.get('release_version')})")
        return job

    # ---- community learning ----------------------------------------------------------------
    def participation() -> ParticipationSettings:
        return ParticipationSettings.from_dict(svc.db.get_setting("community"))

    def client_id() -> str:
        cid = svc.db.get_setting("community_client_id")
        if not cid:  # random pseudonymous id: not derived from user/machine data
            cid = uuid.uuid4().hex
            svc.db.set_setting("community_client_id", cid)
        return cid

    def rounds_today() -> int:
        start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return int(svc.db.one("SELECT COUNT(*) AS n FROM activity WHERE kind='community' AND ts>=? AND message LIKE "
                              "'Contributed%'", (start,))["n"])

    @app.get("/api/community", dependencies=deps)
    def community():
        s = participation()
        ok, reason = may_contribute(s, dt.datetime.now(), rounds_today())
        coordinator = None
        if s.coordinator_url:
            try:
                from moth.community.client import CommunityClient

                coordinator = CommunityClient(s, client_id()).info()
            except Exception as e:
                coordinator = {"error": str(e)}
        running = [j.public() for j in jobs.running("community")]
        history = svc.db.query("SELECT ts, message FROM activity WHERE kind='community' ORDER BY id DESC LIMIT 20")
        return {"settings": s.to_dict(), "can_contribute": ok, "reason": reason, "coordinator": coordinator,
                "running": running, "history": history, "rounds_today": rounds_today()}

    @app.put("/api/community", dependencies=deps)
    def put_community(body: dict[str, Any]):
        s = ParticipationSettings.from_dict({**participation().to_dict(), **body})
        svc.db.set_setting("community", s.to_dict())
        svc.db.log_activity("community", f"Community settings updated (enabled={s.enabled}, paused={s.paused})")
        if (s.paused or not s.enabled):
            for j in jobs.running("community"):
                jobs.stop(j.id, grace=30)
        return community()

    @app.post("/api/community/contribute", dependencies=deps)
    def contribute():
        s = participation()
        ok, reason = may_contribute(s, dt.datetime.now(), rounds_today())
        if not ok:
            raise HTTPException(409, f"cannot contribute now: {reason}")
        if jobs.running("community") or jobs.running("train"):
            raise HTTPException(409, "a training job is already running")
        path = svc.paths.community / "participation.json"
        path.write_text(json.dumps(s.to_dict()))

        def on_event(job: Job, e: dict) -> None:
            if e.get("kind") == "done" and e.get("accepted"):
                svc.db.log_activity("community", f"Contributed round {e.get('round')}: {e.get('steps')} steps, "
                                                 f"loss {e.get('loss_before', 0):.3f} → {e.get('loss_after', 0):.3f}")
            elif e.get("kind") == "done":
                svc.db.log_activity("community", f"Contribution rejected: {', '.join(e.get('reasons', []))}")
            elif e.get("kind") == "error":
                svc.db.log_activity("community", f"Contribution failed: {e.get('message')}")

        job = jobs.start("community", "Community training round",
                         ["community-round", "--settings", str(path), "--client-id", client_id()],
                         on_event=on_event)
        return job.public()

    # ---- personal learning ------------------------------------------------------------------
    @app.post("/api/learning/personal/export", dependencies=deps)
    def export_personal(body: PersonalExportIn):
        """Write verified agent transcripts as local chat-format training data (never uploaded)."""
        from moth.agent.protocol import TOOL_CALL

        q = "SELECT * FROM tasks WHERE status='completed'"
        params: list[Any] = []
        if body.project_id is not None:
            q += " AND project_id=?"
            params.append(body.project_id)
        rows = svc.db.query(q, params)
        out_dir = svc.paths.datasets / "_sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{body.name}-{int(time.time())}.jsonl"
        n = 0
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                result = json.loads(r["result"] or "{}")
                verification = result.get("verification") or {}
                if not (verification.get("ran") and verification.get("passed")):
                    continue  # only test-verified successes
                steps = json.loads(r["steps"] or "{}").get("steps", [])
                msgs = [{"role": "user", "content": r["goal"]}]
                for s in steps:
                    call = json.dumps({"tool": s["tool"], "args": s["args"]})
                    msgs.append({"role": "assistant", "content": f"{s.get('thought', '')}{TOOL_CALL}{call}"})
                    msgs.append({"role": "tool_result", "content": s["result"]})
                summary = result.get("model_summary") or "done"
                msgs.append({"role": "assistant", "content": TOOL_CALL + json.dumps({"tool": "finish", "args": {"summary": summary}})})
                f.write(json.dumps({"messages": msgs, "moth_trusted": True}) + "\n")
                n += 1
        if n == 0:
            path.unlink(missing_ok=True)
            raise HTTPException(409, "no test-verified completed tasks to learn from yet")
        svc.db.log_activity("learning", f"Exported {n} verified task transcripts for local training")
        return {"path": str(path), "examples": n, "source_spec": f"jsonl:{path}"}
