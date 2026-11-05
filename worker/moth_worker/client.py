"""HTTP client for the coordinator's worker API."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx


class ServerError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class WorkerClient:
    def __init__(self, server: str, token: str | None = None, http: httpx.Client | None = None, timeout: float = 120):
        self.server = server.rstrip("/")
        self.token = token
        self.http = http or httpx.Client(base_url=self.server, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:200]
            raise ServerError(r.status_code, str(detail))
        return r

    def enroll(self, token: str, hardware: dict, version: str) -> dict:
        return self._check(self.http.post("/v1/worker/enroll", json={"token": token, "hardware": hardware,
                                                                     "version": version})).json()

    def heartbeat(self, hardware: dict | None, job_id: int | None, progress: float | None) -> dict:
        return self._check(self.http.post("/v1/worker/heartbeat", headers=self._headers(),
                                          json={"hardware": hardware, "job_id": job_id, "progress": progress})).json()

    def claim(self) -> dict | None:
        r = self._check(self.http.post("/v1/worker/jobs/claim", headers=self._headers()))
        return None if r.status_code == 204 else r.json()

    def download(self, job_id: int, what: str, expected_sha256: str) -> bytes:
        data = self._check(self.http.get(f"/v1/worker/jobs/{job_id}/{what}", headers=self._headers())).content
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ServerError(0, f"downloaded {what} failed checksum verification")
        return data

    def progress(self, job_id: int, progress: float) -> dict:
        return self._check(self.http.post(f"/v1/worker/jobs/{job_id}/progress", headers=self._headers(),
                                          json={"progress": progress})).json()

    def result(self, job_id: int, meta: dict[str, Any], payload: bytes) -> dict:
        headers = {**self._headers(), "x-moth-contribution": json.dumps(meta), "content-type": "application/octet-stream"}
        return self._check(self.http.post(f"/v1/worker/jobs/{job_id}/result", headers=headers, content=payload)).json()

    def fail(self, job_id: int, error: str) -> None:
        self._check(self.http.post(f"/v1/worker/jobs/{job_id}/fail", headers=self._headers(), json={"error": error[:2000]}))
