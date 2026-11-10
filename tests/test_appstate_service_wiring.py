"""ENG-03 wiring guard: services split out of AppState must share its state, not copy it.

A service that captured the TargetProfile or config at construction keeps working until the
user switches watch_dir or saves settings, then silently reads or writes the old directory.
A service with a private lock stops being serialised with directory switches. Each service
exposes its providers as properties (``active_profile``/``config``) and its lock as
``_lock``; this test checks them against AppState after a switch.
"""

import pytest

from invoice_hub.api.app import create_app

# attribute on AppState -> which shared things that service must follow
SERVICES = {
    "_bookkeeping": ("lock", "profile", "config"),
    "_documents": ("lock", "profile"),
    "_costs": ("lock", "profile", "config"),
    "_dossier": ("profile", "config"),
    "_preview_print": ("lock", "profile"),
    "_selection": ("lock", "profile"),
    "_appearance": ("lock",),
    "_ocr": ("profile", "config"),
}


@pytest.fixture
def switched_state(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.app_state.AppState.run_background_diagnostics", lambda *args, **kwargs: None)
    state = create_app(tmp_path).state.invoice_hub
    before = (state.active_profile, state.config)
    other = tmp_path / "其它目录"
    other.mkdir()
    state.update_settings({"watch_dir": str(other)})
    assert state.active_profile is not before[0] and state.config is not before[1]
    return state


@pytest.mark.parametrize("attr", sorted(SERVICES))
def test_split_service_follows_app_state(switched_state, attr):
    service = getattr(switched_state, attr)
    shared = SERVICES[attr]
    if "lock" in shared:
        assert service._lock is switched_state._lock
    if "profile" in shared:
        assert service.active_profile is switched_state.active_profile
    if "config" in shared:
        assert service.config is switched_state.config
