from moth.community.participant import Participant


def test_saved_opt_in_cannot_start_compute_on_launch(tmp_path):
    settings = {'participant': {'enabled': True, 'worker_token': 'old', 'server': 'https://cloud.invalid'}}
    participant = Participant(tmp_path, lambda: None, settings.get, settings.__setitem__, lambda *args: None)
    participant.start()
    assert not settings['participant']['enabled']
    assert participant.thread is None


def test_session_change_cannot_reuse_authorization(tmp_path):
    settings = {'participant': {'enabled': True, 'worker_token': 'old', 'server': 'https://cloud.invalid'}}
    participant = Participant(tmp_path, lambda: {'server_url': 'https://cloud.invalid', 'token': 'other'},
                              settings.get, settings.__setitem__, lambda *args: None)
    participant.authorized_session = ('https://cloud.invalid', 'original')
    participant.start()
    assert not settings['participant']['enabled']
    assert participant.authorized_session is None


def test_revoke_stops_local_compute_and_invalidates_server_device(tmp_path):
    import httpx
    calls = []
    settings = {'participant': {'enabled': True, 'worker_id': 7, 'worker_token': 'worker', 'server': 'https://cloud.invalid'}}
    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={'status': 'revoked'})
    participant = Participant(tmp_path, lambda: {'server_url': 'https://cloud.invalid', 'token': 'account'},
                              settings.get, settings.__setitem__, lambda *args: None,
                              http_factory=lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(respond)))
    participant.authorized_session = ('https://cloud.invalid', 'account')
    participant.control('revoke')
    assert calls == [('POST', '/v1/training/workers/7/revoke')]
    assert settings['participant'] == {'enabled': False}
    assert participant.authorized_session is None


def test_supported_pressure_signals_pause_without_inventing_sensor_values():
    from moth.training.resources import pressure_reason
    assert pressure_reason({}) is None
    assert pressure_reason({'temperature_c': 90})
    assert pressure_reason({'on_battery': True, 'battery_percent': 15})
    assert pressure_reason({'on_battery': False, 'battery_percent': 15}) is None


def test_a_revoked_saved_registration_is_replaced_by_a_new_enrollment(tmp_path, monkeypatch):
    """2.2: "Could not authorize this device (HTTP 409)" — the saved worker was revoked on MOTH Cloud."""
    import httpx

    from pathlib import Path

    from moth.community import participant as P

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "worker"))
    from moth_worker import hardware

    monkeypatch.setattr(P, "available", lambda: True)
    monkeypatch.setattr(hardware, "machine_id", lambda: "pc-1")
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/me":
            return httpx.Response(200, json={"user": {"id": 5}})
        if request.url.path == "/v1/training/workers/7/resume":
            return httpx.Response(409, json={"detail": "This worker was revoked."})
        return httpx.Response(200, json={"id": 8})

    settings = {"participant": {"enabled": False, "worker_id": 7, "worker_token": "old", "server": "https://cloud.invalid",
                                "account_id": 5, "device_id": "pc-1"}}
    p = Participant(tmp_path, lambda: {"server_url": "https://cloud.invalid", "token": "account"},
                    settings.get, settings.__setitem__, lambda *args: None,
                    http_factory=lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(p, "_enroll", lambda server, token: {"server": server, "worker_id": 8, "worker_token": "new"})
    monkeypatch.setattr(p, "start", lambda: None)
    p.enable()
    assert ("POST", "/v1/training/workers/7/resume") in calls and ("POST", "/v1/training/workers/8/resume") in calls
    assert settings["participant"]["worker_id"] == 8 and settings["participant"]["enabled"]
