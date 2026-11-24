"""WS-04: synthetic receipts, matching and company/file-bound read-only previews."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.company_bank import CachedFolderReader
from test_bank_workpaper import write_receipts_pdf, write_statement_pdf, statement_text
from test_company_views import _company


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr('invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics', lambda *a, **k: None)
    app = create_app(tmp_path / 'app')
    client = TestClient(app)
    root = tmp_path / 'synthetic-company'
    bank = root / '银行流水'
    bank.mkdir(parents=True)
    write_receipts_pdf(bank / 'receipts.pdf')
    write_statement_pdf(bank / 'statement.pdf', statement_text())
    company = _company(client, root)
    service = app.state.invoice_hub.company_views.receipts
    return client, company, bank, service


def base(company):
    return f'/api/v1/companies/{company}/receipt-preview-jobs'


def test_synthetic_receipts_match_and_render_their_own_page(setup):
    client, company, bank, service = setup
    before = {p: p.stat().st_mtime_ns for p in bank.rglob('*')}
    rows = service.catalog(company)['records']
    assert len(rows) == 5 and all(len(r['flow_ids']) == 1 for r in rows)
    assert len({r['flow_ids'][0] for r in rows}) == 5
    third_page = next(r for r in rows if r['preview']['page'] == 3)
    response = client.post(base(company), json=third_page['preview'])
    assert response.status_code == 200, response.text
    job = response.json()
    assert job['initial_page'] == 3 and job['files'][0]['page_count'] == 3
    url = job['files'][0]['page_url_template'].replace('{page_number}', '3')
    page = client.get(url)
    assert page.status_code == 200 and page.content.startswith(b'\x89PNG')
    assert 'no-store' in page.headers['cache-control']
    assert client.post(job['keep_alive_url']).status_code == 200
    assert client.get(url.replace('/3', '/99')).status_code in (404, 422)
    assert {p: p.stat().st_mtime_ns for p in bank.rglob('*')} == before


@pytest.mark.parametrize('change', [
    {'token': 'invalid'}, {'receipt_id': 'unknown'}, {'kind': 'invoice'},
    {'company_id': 'other'}, {'page': True}, {'page': 99}, {'path': '/outside.pdf'},
])
def test_capability_cannot_be_extended_or_forged(setup, change):
    client, company, _, service = setup
    preview = service.catalog(company)['records'][0]['preview']
    assert client.post(base(company), json={**preview, **change}).status_code == 409
    assert client.post(base(company), json=preview, headers={'Origin': 'http://evil.example'}).status_code in (400, 403)


def test_replacement_with_restored_size_and_mtime_invalidates_capability_and_job(setup):
    client, company, bank, service = setup
    preview = service.catalog(company)['records'][0]['preview']
    job = client.post(base(company), json=preview).json()
    source = bank / 'receipts.pdf'
    stat = source.stat()
    content = source.read_bytes()
    source.write_bytes(content.replace(b'/Producer', b'/ProdUcer'))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    assert client.post(base(company), json=preview).status_code == 409
    assert client.post(job['keep_alive_url']).status_code == 409


def test_directory_replacement_and_cross_company_jobs_are_refused(setup, tmp_path):
    client, company, bank, service = setup
    preview = service.catalog(company)['records'][0]['preview']
    job = client.post(base(company), json=preview).json()
    other = tmp_path / 'other-company'
    other.mkdir()
    other_id = _company(client, other, revision=1, name="乙公司")
    assert client.post(base(other_id) + '/' + job['job_id'] + '/keep-alive').status_code == 410
    moved = bank.with_name('old-bank')
    bank.rename(moved)
    bank.mkdir()
    shutil.copy(moved / 'receipts.pdf', bank / 'receipts.pdf')
    assert client.post(base(company), json=preview).status_code == 409
    assert client.post(job['keep_alive_url']).status_code == 409


def test_symlink_and_ambiguous_basename_do_not_grant_preview(setup):
    client, company, bank, service = setup
    preview = service.catalog(company)['records'][0]['preview']
    source = bank / 'receipts.pdf'
    moved = bank / 'actual.pdf'
    source.rename(moved)
    source.symlink_to(moved)
    assert client.post(base(company), json=preview).status_code == 409
    source.unlink()
    moved.rename(source)
    nested = bank / 'nested'
    nested.mkdir()
    shutil.copy(source, nested / source.name)
    assert all(r['preview'] is None for r in service.catalog(company)['records'])


def test_changes_during_parse_are_not_cached(tmp_path):
    source = tmp_path / 'file.pdf'
    source.write_bytes(b'old')
    def parse(paths):
        # Change size as well as content so fast writes within one Windows NTFS
        # 15.6ms mtime tick still change the stat signature.
        paths[0].write_bytes(b'newer')
        return 'stale result'
    reader = CachedFolderReader(parse, ('.pdf',), 'synthetic')
    result = reader.read(tmp_path)
    assert result.data is None and not result.complete


def test_change_during_render_and_expired_job_are_refused(setup, monkeypatch):
    client, company, bank, service = setup
    preview = service.catalog(company)['records'][0]['preview']
    job = client.post(base(company), json=preview).json()
    url = job['files'][0]['page_url_template'].replace('{page_number}', '1')
    render = service.renderer.get_page
    def change_after_render(*args):
        result = render(*args)
        (bank / 'receipts.pdf').touch()
        return result
    monkeypatch.setattr(service.renderer, 'get_page', change_after_render)
    assert client.get(url).status_code == 409
    service._jobs.clear()
    assert client.post(job['keep_alive_url']).status_code == 410
