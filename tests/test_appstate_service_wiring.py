"""ENG-03 wiring guard: services split out of AppState must share its state, not copy it.

A service that captured the TargetProfile or config at construction keeps working until the
user switches watch_dir or saves settings, then silently reads or writes the old directory.
A service with a private lock stops being serialised with directory switches. Each service
is a public attribute of AppState that routes call directly (ENG-08); it exposes its providers as
properties (``active_profile``/``config``) and its lock as ``_lock``. This test checks them against
AppState after a switch.
"""

import pytest

from invoice_hub.api.app import create_app

# public service attribute on AppState -> which shared things that service must follow
SERVICES = {
    "bookkeeping": ("lock", "profile", "config"),
    "companies": ("lock", "profile", "config"),
    "documents": ("lock", "profile"),
    "costs": ("lock", "profile", "config"),
    "dossier": ("profile", "config"),
    "preview_print": ("lock", "profile"),
    "selection": ("lock", "profile"),
    "appearance": ("lock",),
    "ocr": ("profile", "config"),
    "about": ("lock",),
    "invoices": ("lock", "profile"),
    "rename": ("lock", "profile"),
    "settings": ("lock", "profile", "config"),
    "diagnostics": ("profile", "config"),
    "background": ("lock", "profile", "config"),
    "monitor": ("lock", "profile", "config"),
    "shutdown": ("lock", "config"),
}


@pytest.fixture
def switched_state(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
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


def test_app_state_has_no_forwarders_left():
    """ENG-08: routes call services directly; new use cases belong in a service, not on AppState."""
    from invoice_hub.services.app_state import AppState

    public = {name for name in vars(AppState) if not name.startswith("_")}
    assert public == {
        "active_profile", "ensure_active_dirs", "append_event", "get_task", "wait_events", "event_bounds",
        "health", "update_settings", "prepare_invoice_trash", "invoice_trash_status", "commit_invoice_trash",
    }
