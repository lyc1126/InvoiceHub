import os

import pytest

from invoice_hub.domain import InvoiceRecord
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.projections import summary
from invoice_hub.storage import generations, read_csv_rows
from invoice_hub.storage.parse_cache import ParseCache, scan_files
from invoice_hub.targets import load_config, target_profile_for
from test_monitoring import _sample_xml


def test_ten_thousand_files_only_parse_five_changes(tmp_path, monkeypatch):
    source, workspace = tmp_path / 'source', tmp_path / 'workspace'
    source.mkdir()
    for index in range(10000):
        (source / f'{index}.xml').write_text(str(index))
    calls = []
    def parse(path):
        calls.append(path.name)
        return InvoiceRecord(invoice_key=path.stem, source_file=path.name, source_path=str(path), invoice_number=str(10000000 + int(path.stem)))
    monkeypatch.setattr(summary, 'extract_invoice_record', parse)
    with ParseCache(workspace) as cache:
        summary.build_summary(source, workspace, cache=cache)
    assert len(calls) == 10000
    calls.clear()
    with ParseCache(workspace) as cache:
        summary.build_summary(source, workspace, cache=cache)
    assert calls == []
    for index in range(10000, 10003):
        (source / f'{index}.xml').write_text(str(index))
    for index in (1, 2):
        (source / f'{index}.xml').write_text('changed')
    (source / '3.xml').unlink()
    with ParseCache(workspace) as cache:
        incremental = summary.build_summary(source, workspace, cache=cache)
    assert set(calls) == {'1.xml', '2.xml', '10000.xml', '10001.xml', '10002.xml'}
    with ParseCache(workspace, rebuild=True) as cache:
        full = summary.build_summary(source, workspace, cache=cache)
    assert incremental['records'] == full['records']


def test_equal_length_time_replacement_and_parser_version(tmp_path):
    path = tmp_path / 'a.xml'
    path.write_text('alpha')
    parse = lambda: {'text': path.read_text()}
    with ParseCache(tmp_path) as cache:
        assert cache.read('test', path, 'v1', parse) == {'text': 'alpha'}
    stamp = path.stat()
    path.write_text('bravo')
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with ParseCache(tmp_path, verify=True) as cache:
        assert cache.read('test', path, 'v1', parse) == {'text': 'bravo'}
        assert cache.parsed == 1
        cache.read('test', path, 'v2', parse)
        assert cache.parsed == 2


def test_failed_candidate_keeps_complete_generation_and_manual_fields(tmp_path, monkeypatch):
    profile = target_profile_for(load_config(tmp_path))
    state = MonitorState(profile)
    path = state.watch_dir / 'a.xml'
    path.write_text(_sample_xml())
    sync = MonitorSynchronizer(state)
    assert sync.run_sync('startup', force=True)['ok']
    previous = generations.current(state.workspace_dir)
    stable = generations.resolve(state.workspace_dir, state.watch_dir, '发票汇总.csv')
    content = stable.read_bytes()
    manual = {str(path): {'source_path': str(path), 'fields': {'销售方': '人工名称'}, 'updated_at': ''}}
    state.save_manual_overrides(manual)
    (state.watch_dir / 'b.xml').write_text(_sample_xml())
    def fail(*args, **kwargs):
        raise OSError('injected')
    monkeypatch.setattr('invoice_hub.projections.incremental.CostProjectionService.rebuild', fail)
    assert not sync.run_sync('event', force=True)['ok']
    assert generations.current(state.workspace_dir) == previous and stable.read_bytes() == content
    assert state.load_manual_overrides() == manual
    assert not list((state.workspace_dir / 'projection-generations').glob('.candidate-*'))
    assert read_csv_rows(stable)[0]['销售方'] != '人工名称'


def test_missing_or_linked_scan_is_unknown(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_files(tmp_path / 'missing')
    (tmp_path / 'link.xml').symlink_to(tmp_path / 'missing')
    with pytest.raises(ValueError, match='链接'):
        scan_files(tmp_path)


def test_manifest_refuses_late_publication_and_damage(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    workspace = tmp_path / 'workspace'
    with generations.candidate(workspace) as stage:
        for name in generations.SUMMARY + generations.COST[:2]:
            (stage / name).write_text('synthetic')
        published = generations.publish(workspace, source, stage)
    with generations.candidate(workspace) as stage:
        with pytest.raises(ValueError, match='迟到'):
            generations.publish(workspace, source, stage, expected='old')
    assert generations.current(workspace)['generation'] == published['generation']
    (workspace / 'projection-manifest.json').write_text('{"version":999}')
    with pytest.raises(ValueError, match='损坏'):
        generations.resolve(workspace, source, '发票汇总.csv')


def test_raw_cache_damage_rebuilds_without_losing_manual_json(tmp_path):
    path = tmp_path / 'a.xml'
    path.write_text('synthetic')
    (tmp_path / 'manual_overrides.json').write_text('{"keep":true}')
    (tmp_path / 'parse-cache.sqlite3').write_bytes(b'broken sqlite')
    with ParseCache(tmp_path) as cache:
        assert cache.read('test', path, 'v1', lambda: {'ok': True}) == {'ok': True}
        cache.db.execute("UPDATE raw SET payload='[]'")
        cache.db.commit()
        assert cache.read('test', path, 'v1', lambda: {'repaired': True}) == {'repaired': True}
    assert (tmp_path / 'manual_overrides.json').read_text() == '{"keep":true}'


def test_generation_source_aliases_share_identity_but_other_roots_are_rejected(tmp_path):
    import json
    real = tmp_path / 'real'
    source = real / 'source'
    source.mkdir(parents=True)
    alias = tmp_path / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    workspace = tmp_path / 'workspace'
    with generations.candidate(workspace) as stage:
        for name in generations.SUMMARY + generations.COST[:2]:
            (stage / name).write_text('synthetic')
        published = generations.publish(workspace, alias / 'source', stage)
    assert published['source'] == str(source.resolve())
    assert generations.current(workspace, source)['generation'] == published['generation']
    assert generations.resolve(workspace, alias / 'source', '发票汇总.csv').read_text() == 'synthetic'
    # A pre-normalization manifest can contain the alias spelling; keep it readable.
    manifest = workspace / 'projection-manifest.json'
    published['source'] = str(alias / 'source')
    manifest.write_text(json.dumps(published), encoding='utf-8')
    assert generations.current(workspace, source)['generation'] == published['generation']
    other = tmp_path / 'other'
    (other / 'source').mkdir(parents=True)
    with pytest.raises(ValueError, match='清单损坏'):
        generations.current(workspace, other / 'source')
    alias.unlink()
    alias.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match='清单损坏'):
        generations.current(workspace, source)


def test_export_failure_recovery_and_manifest_content_validation(tmp_path, monkeypatch):
    source, workspace = tmp_path / 'source', tmp_path / 'workspace'
    source.mkdir()
    names = generations.SUMMARY + generations.COST[:2]
    def publish(value, expected=''):
        with generations.candidate(workspace) as stage:
            for name in names:
                (stage / name).write_text(value)
            return generations.publish(workspace, source, stage, expected=expected)
    first = publish('first')
    real_copy = generations.shutil.copyfile
    def fail_export(src, dst, *args, **kwargs):
        if str(dst).endswith('.tmp'):
            raise OSError('locked workbook')
        return real_copy(src, dst, *args, **kwargs)
    monkeypatch.setattr(generations.shutil, 'copyfile', fail_export)
    second = publish('second', first['generation'])
    assert len(second['export_warnings']) == 4
    assert (workspace / '发票汇总.csv').read_text() == 'first'
    assert generations.resolve(workspace, source, '发票汇总.csv').read_text() == 'second'
    monkeypatch.setattr(generations.shutil, 'copyfile', real_copy)
    generations.recover_exports(workspace, source)
    assert (workspace / '发票汇总.csv').read_text() == 'second'
    stable = generations.resolve(workspace, source, '发票汇总.csv')
    stable.write_text('damaged')
    with pytest.raises(ValueError, match='损坏'):
        generations.resolve(workspace, source, '发票汇总.csv')
