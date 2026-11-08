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
