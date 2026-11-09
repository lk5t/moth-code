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
