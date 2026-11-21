import json
import time
from types import SimpleNamespace

import pytest

from invoice_hub.services.file_preview import FilePreviewService
from invoice_hub.services.sources import SourceService
from invoice_hub.storage.source_adapters import Mounted, SourceError, safe_name
from test_monitoring import _sample_xml


def hang_worker(pipe, profile, root, kind, data):
    import os
    if os.name != 'nt':
        os.setsid()
    time.sleep(60)


def wait(service, sid):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        with service.lock:
            running = sid in service.tasks
        if not running:
            return service.get(sid)
        time.sleep(.05)
    pytest.fail('source task did not stop')


@pytest.fixture
def service(tmp_path):
    result = SourceService(tmp_path / 'private', previews=FilePreviewService(),
                           companies=SimpleNamespace(get_company=lambda _: {'company': {'name': '合成', 'taxpayer_periods': []}}))
    yield result
    result.close()


def source(service, path):
    path.mkdir(exist_ok=True)
    return service.add({'protocol': 'mounted', 'name': '合成共享', 'root': str(path)})['id']


def test_mounted_scan_summary_preview_offline_and_incremental(service, tmp_path):
    root = tmp_path / 'share'
    sid = source(service, root)
    (root / '子目录').mkdir()
    path = root / '子目录/a.xml'
    path.write_text(_sample_xml())
    original = path.read_bytes()
    service.start(sid, 'scan')
    assert wait(service, sid)['connection'] == 'online'
    listing = service.entries(sid)
    folder = listing['items'][0]
    assert folder['name'] == '子目录' and listing['scope']['files'] == 1
    entry = service.entries(sid, folder['id'])['items'][0]
    assert entry['relative'] == '子目录/a.xml'
    with pytest.raises(SourceError, match='副本'):
        service.preview(sid, entry['id'])
    service.start(sid, 'summary')
    result = wait(service, sid)
    assert result['sync'] == 'idle', result
    summary = service.summary(sid)
    assert summary['available'] and summary['count'] == 1
    assert summary['ledger']['checks_ok']
    cold = summary['stats']['parsed']
    assert cold >= 1
    assert service.preview(sid, entry['id'])['preview_type'] == 'text'
    service.start(sid, 'summary')
    assert wait(service, sid)['sync'] == 'idle'
    assert service.summary(sid)['stats']['parsed'] == 0
    service.cancel(sid, disconnect=True)
    with pytest.raises(SourceError, match='离线'):
        service.preview(sid, entry['id'])
    preview = service.preview(sid, entry['id'], allow_stale=True)
    assert preview['stale']
    assert 'Invoice' in service.preview_content(sid, preview['job_id'])
    with pytest.raises(SourceError, match='租约'):
        service.clear_cache(sid)
    assert path.read_bytes() == original
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob('*')) == ['子目录', '子目录/a.xml']


def test_listing_readable_count_uses_whole_subtree_not_filter_or_metadata(service, tmp_path):
    root = tmp_path / 'share'
    sid = source(service, root)
    for name in ['empty', 'unsupported', 'readable/nested']:
        (root / name).mkdir(parents=True)
    (root / 'unsupported/readme.txt').write_text('synthetic')
    (root / 'readable/nested/a.XML').write_text(_sample_xml())
    (root / 'readable/picture.png').write_bytes(b'synthetic metadata only')
    service.start(sid, 'scan')
    assert wait(service, sid)['sync'] == 'idle'
    listing = service.entries(sid)
    ids = {entry['name']: entry['id'] for entry in listing['items']}
    assert listing['scope']['files'] == 3
    assert listing['scope']['readable_files'] == 2
    assert service.entries(sid, ids['empty'])['scope']['readable_files'] == 0
    unsupported = service.entries(sid, ids['unsupported'])
    assert unsupported['scope']['readable_files'] == 0
    assert unsupported['items'][0]['name'] == 'readme.txt'
    filtered = service.entries(sid, ids['readable'], keyword='no-match')
    assert filtered['items'] == []
    assert filtered['scope']['readable_files'] == 2


def test_incomplete_scan_keeps_snapshot_and_rejects_root_replacement(service, tmp_path):
    root = tmp_path / 'share'
    sid = source(service, root)
    (root / 'a.xml').write_text(_sample_xml())
    service.start(sid, 'scan')
    before = wait(service, sid)['generation']
    (root / 'escape').symlink_to(tmp_path, target_is_directory=True)
    service.start(sid, 'scan')
    failed = wait(service, sid)
    assert failed['generation'] == before and failed['sync'] == 'failed'
    assert service.entries(sid)['count'] == 1
    (root / 'escape').unlink()
    root.rename(tmp_path / 'old')
    root.mkdir()
    service.start(sid, 'scan')
    assert wait(service, sid)['connection'] == 'root_changed'
    assert service.get(sid)['generation'] == before


def test_cancel_is_immediate_and_health_does_not_wait_on_network(tmp_path):
    service = SourceService(tmp_path / 'private', previews=FilePreviewService(), companies=None, worker_target=hang_worker)
    try:
        sid = source(service, tmp_path / 'share')
        service.start(sid, 'scan')
        started = time.monotonic()
        service.cancel(sid, disconnect=True)
        assert service.list()['sources'][0]['connection'] == 'offline'
        assert time.monotonic() - started < .5
        assert wait(service, sid)['generation'] == ''
    finally:
        service.close()


def test_restart_recovers_unknown_without_fabricating_empty_snapshot(service, tmp_path):
    sid = source(service, tmp_path / 'share')
    service.start(sid, 'scan')
    generation = wait(service, sid)['generation']
    payload = json.loads(service.registry.read_text())
    payload['sources'][0]['sync'] = 'downloading'
    service.registry.write_text(json.dumps(payload))
    restored = SourceService(service.root, previews=service.previews, companies=service.companies)
    try:
        state = restored.get(sid)
        assert state['snapshot'] == 'unknown' and state['generation'] == generation
        assert state['error_code'] == 'interrupted'
    finally:
        restored.close()


def test_failed_publication_does_not_promote_memory_pointers(service, tmp_path, monkeypatch):
    sid = source(service, tmp_path / 'share')
    old_profile = dict(service.profiles[sid])
    def fail(*args, **kwargs):
        raise OSError('injected full disk')
    monkeypatch.setattr('invoice_hub.services.sources.atomic_write_json', fail)
    with pytest.raises(OSError):
        service._commit(sid, service.profiles[sid], 'scan', {},
                        {'entries': [], 'root_identity': [1, 2], 'strength': 'synthetic'})
    assert service.snapshots[sid] == {}
    assert service.profiles[sid] == old_profile


def test_unnumbered_remote_invoices_keep_distinct_opaque_families(service, tmp_path):
    root = tmp_path / 'share'
    sid = source(service, root)
    xml = _sample_xml().replace('<invoiceNo>25322000000043426430</invoiceNo>', '')
    for name in ('a.xml', 'b.xml'):
        (root / name).write_text(xml)
    service.start(sid, 'scan')
    wait(service, sid)
    service.start(sid, 'summary')
    state = wait(service, sid)
    assert state['sync'] == 'idle', state
    result = service.summary(sid)
    assert len({item['source_path'] for item in result['items']}) == 2
    assert all(len(item['source_path']) == 32 for item in result['items'])
    assert result['ledger']['merged_copies']['input'] == 0


@pytest.mark.parametrize('name', ['..', '../escape', 'a/b', r'a\b', 'CON', 'trailing.', 'a\x00b'])
def test_rejects_unsafe_names(name):
    with pytest.raises(SourceError):
        safe_name(name)


def test_source_isolation_fingerprints_and_no_uri_as_path(service, tmp_path):
    root = tmp_path / 'share'
    one, two = source(service, root), source(service, root)
    (root / 'a.xml').write_text(_sample_xml())
    for sid in (one, two):
        service.start(sid, 'scan')
        wait(service, sid)
    entry = service.entries(one)['items'][0]
    with pytest.raises(SourceError):
        service.preview(two, entry['id'])
    with pytest.raises(SourceError):
        service.add({'protocol': 'mounted', 'name': 'bad', 'root': 'sftp://host/root'})
    remote = service.add({'protocol': 'sftp', 'name': 'SSH', 'root': '/invoices', 'host': 'host.invalid', 'username': 'reader', 'port': 22})
    sid = remote['id']
    with pytest.raises(SourceError, match='指纹'):
        service.start(sid, 'scan')
    service.profiles[sid]['candidate_keys'] = {'SHA256:synthetic': 'ssh-ed25519 c3ludGhldGlj'}
    service.confirm(sid, 1, 'SHA256:synthetic')
    assert 'host_key' not in service.get(sid)
    assert service.get(sid)['fingerprint'] == 'SHA256:synthetic'
    with pytest.raises(SourceError):
        service.confirm(sid, 1, 'SHA256:unknown')
    profile = service.profiles[sid]
    service._commit(sid, profile, 'probe', {}, {'keys': {'SHA256:changed': 'ssh-ed25519 Y2hhbmdlZA=='}})
    assert service.get(sid)['connection'] == 'host_key_changed'


def test_mounted_copy_rejects_changed_file(service, tmp_path):
    root = tmp_path / 'share'
    root.mkdir()
    path = root / 'a.xml'
    path.write_text('before')
    adapter = Mounted({'root': str(root)})
    entry = adapter.entries(lambda _: None)[0]
    path.write_text('after')
    with pytest.raises(SourceError, match='版本'):
        adapter.copy(entry, tmp_path / 'copy.part', lambda _: None)


def test_source_http_origin_limits_no_monitor_switch_or_local_preview_escape(tmp_path):
    from fastapi.testclient import TestClient
    from invoice_hub.api.app import create_app
    app = create_app(tmp_path / 'app')
    with TestClient(app) as client:
        active = app.state.invoice_hub.active_profile.id
        service = app.state.server_sources
        root = tmp_path / 'share'
        root.mkdir()
        (root / 'a.xml').write_text(_sample_xml())
        body = {'protocol': 'mounted', 'root': str(root), 'name': '合成共享'}
        assert client.post('/api/v1/sources', json=body, headers={'Origin': 'https://evil.invalid'}).status_code == 403
        assert client.post('/api/v1/sources', json={**body, 'password': 'not-accepted'}).status_code == 422
        sid = client.post('/api/v1/sources', json=body).json()['source']['id']
        service.start(sid, 'scan')
        wait(service, sid)
        entry = service.entries(sid)['items'][0]
        service.start(sid, 'download', entry_id=entry['id'])
        assert wait(service, sid)['sync'] == 'idle'
        preview = client.post(f'/api/v1/sources/{sid}/previews', json={'entry_id': entry['id']}).json()
        assert client.get(f"/api/v1/sources/{sid}/previews/{preview['job_id']}/text").status_code == 200
        assert client.get(f"/api/v1/invoices/preview-jobs/{preview['job_id']}/files/1/text").status_code == 404
        assert client.get(f'/api/v1/sources/{sid}/entries?parent_id=../../').status_code == 404
        assert client.get('/api/v1/sources').headers['cache-control'] == 'private, no-store'
        assert app.state.invoice_hub.active_profile.id == active
        assert client.delete(f"/api/v1/sources/{sid}/previews/{preview['job_id']}").status_code == 200
        assert client.delete(f'/api/v1/sources/{sid}/cache').status_code == 200
        assert client.delete(f'/api/v1/sources/{sid}?revision=1').status_code == 200
        assert (root / 'a.xml').exists()
