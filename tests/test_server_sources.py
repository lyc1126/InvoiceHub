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
    path.write_text(_sample_xml(), encoding="utf-8")
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
    (root / 'unsupported/readme.txt').write_text('synthetic', encoding="utf-8")
    (root / 'readable/nested/a.XML').write_text(_sample_xml(), encoding="utf-8")
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
    (root / 'a.xml').write_text(_sample_xml(), encoding="utf-8")
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
    payload = json.loads(service.registry.read_text(encoding="utf-8"))
    payload['sources'][0]['sync'] = 'downloading'
    service.registry.write_text(json.dumps(payload), encoding="utf-8")
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
        (root / name).write_text(xml, encoding="utf-8")
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
    (root / 'a.xml').write_text(_sample_xml(), encoding="utf-8")
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
    path.write_text('before', encoding="utf-8")
    adapter = Mounted({'root': str(root)})
    entry = adapter.entries(lambda _: None)[0]
    path.write_text('after', encoding="utf-8")
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
        (root / 'a.xml').write_text(_sample_xml(), encoding="utf-8")
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


def test_scoped_summary_filters_sort_selection_and_batch_preview(service, tmp_path):
    root = tmp_path / 'share'
    sid = source(service, root)
    (root / '项目A/发票').mkdir(parents=True)
    (root / '项目B').mkdir(parents=True)
    xml_1 = _sample_xml()
    xml_2 = (
        _sample_xml()
        .replace('25322000000043426430', '25322000000043426431')
        .replace('2026-05-23', '2026-08-15')
        .replace('示例销售方有限公司', '乙材料供应有限公司')
    )
    (root / '项目A/发票/inv1.xml').write_text(xml_1, encoding='utf-8')
    (root / '项目A/发票/inv2.xml').write_text(xml_2, encoding='utf-8')
    # macOS AppleDouble sidecar must be skipped during invoice summary, and a broken non-invoice PDF
    # must not discard the valid header summary of the folder.
    (root / '项目A/发票/._inv1.pdf').write_bytes(b'appledouble')
    (root / '项目A/发票/说明文件.pdf').write_bytes(b'not-a-valid-pdf')
    (root / '项目B/other.xml').write_text(xml_2, encoding='utf-8')

    service.start(sid, 'scan')
    assert wait(service, sid)['connection'] == 'online'
    proj_a = next(item for item in service.entries(sid)['items'] if item['name'] == '项目A')
    proj_b = next(item for item in service.entries(sid)['items'] if item['name'] == '项目B')
    inv_dir = next(item for item in service.entries(sid, proj_a['id'])['items'] if item['name'] == '发票')

    # Summarize ONLY 项目A/发票; 项目B remains unsummarized and untouched.
    service.start(sid, 'summary', parent_id=inv_dir['id'])
    done = wait(service, sid)
    assert done['sync'] == 'idle', done
    assert service.summary(sid, proj_b['id'])['available'] is False

    scoped = service.summary(sid, inv_dir['id'], page=1, page_size=50, date_sort='desc')
    assert scoped['available'] is True
    assert scoped['total_count'] == 3  # inv1.xml, inv2.xml, 说明文件.pdf (._inv1.pdf skipped)
    assert scoped['invoice_stats']['all']['total'] == 3
    assert scoped['invoice_stats']['all']['recognized'] == 2
    assert scoped['invoice_stats']['all']['needs_review'] == 1
    assert scoped['items'][0]['invoice_date'] == '2026-08-15'
    assert scoped['items'][1]['invoice_date'] == '2026-05-23'

    filtered = service.summary(sid, inv_dir['id'], keyword='乙材料', file_ext='.xml', status='已识别')
    assert filtered['count'] == 1
    assert filtered['invoice_stats']['filtered']['total'] == 1
    assert filtered['invoice_stats']['all']['total'] == 3

    # Selection summary deduplicates families and validates summary generation.
    entry_ids = [item['entry_id'] for item in scoped['items'] if item['file_format'] == 'XML']
    sel = service.selection_summary(sid, entry_ids=entry_ids, parent_id=inv_dir['id'], generation=scoped['generation'])
    assert sel['selection']['invoice_count'] == 2
    assert sel['totals']['total_with_tax']['valid_invoice_count'] == 2
    with pytest.raises(SourceError, match='代际'):
        service.selection_summary(sid, entry_ids=entry_ids, parent_id=inv_dir['id'], generation='0' * 32)

    # Batch multi-file preview and keep-alive work on cached source files.
    preview = service.preview(sid, entry_ids=entry_ids)
    assert preview['record_count'] == 2 and len(preview['files']) == 2
    assert 'Invoice' in service.preview_content(sid, preview['job_id'], file_number=2)
    assert service.keep_alive_preview(sid, preview['job_id'])['ok'] is True
    service.release_preview(sid, preview['job_id'])


def test_batch_download_and_mounted_shares_http_routes(tmp_path):
    from fastapi.testclient import TestClient
    from invoice_hub.api.app import create_app

    app = create_app(tmp_path / 'app')
    with TestClient(app) as client:
        shares = client.get('/api/v1/sources/mounted-shares')
        assert shares.status_code == 200
        assert shares.headers['cache-control'] == 'private, no-store'
        assert isinstance(shares.json()['shares'], list)

        root = tmp_path / 'share'
        root.mkdir()
        (root / 'a.xml').write_text(_sample_xml(), encoding='utf-8')
        (root / 'b.xml').write_text(_sample_xml().replace('25322000000043426430', '25322000000043426439'), encoding='utf-8')
        sid = client.post('/api/v1/sources', json={'protocol': 'mounted', 'root': str(root), 'name': '合成批量'}).json()['source']['id']
        service = app.state.server_sources
        service.start(sid, 'scan')
        wait(service, sid)
        ids = [item['id'] for item in service.entries(sid)['items']]

        res = client.post(f'/api/v1/sources/{sid}/tasks', json={'kind': 'download', 'entry_ids': ids})
        assert res.status_code == 200
        assert wait(service, sid)['sync'] == 'idle'

        prev = client.post(f'/api/v1/sources/{sid}/previews', json={'entry_ids': ids})
        assert prev.status_code == 200
        payload = prev.json()
        assert payload['record_count'] == 2
        assert client.get(f"/api/v1/sources/{sid}/previews/{payload['job_id']}/files/2/text").status_code == 200
        assert client.post(f"/api/v1/sources/{sid}/previews/{payload['job_id']}/keep-alive").status_code == 200
        assert client.delete(f"/api/v1/sources/{sid}/previews/{payload['job_id']}").status_code == 200
