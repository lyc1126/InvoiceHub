import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import CompareGallery from '../src/components/CompareGallery.vue';
import { VIEW_ACTIVE } from '../src/modules';
import type { CompareRecord } from '../src/api/types';

const invoice = (id: number, allowed = true): CompareRecord => ({
  id: `input:${id}`, invoice_number: String(id), invoice_date: '2026-07-03', counterpart: '合成供应商', amount: '10.00', source_file: `${id}.xml`,
  ...(allowed ? { preview: { target_id: 't1', items: [{ invoice_key: String(id), source_path: `synthetic/${id}.xml` }] } } : {}),
  detail: { label: String(id), record_ids: { a: [`input:${id}`], b: [] }, steps: ['合成明细'] },
});
const job = (page = 1) => ({ job_id: 'job', initial_page: page, keep_alive_url: '/renew', files: [{ file_number: 1, name: 'source', preview_type: page === 1 ? 'text' : 'pages', page_count: 3, page_url_template: '/pages/{page_number}', text_url: '/text', reason: '' }] });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('compare source gallery', () => {
  it('bounds requests by six visible tiles, never previews unmarked invoices, and filters by backend identities', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { requests.push(url); return new Response(JSON.stringify(job())); }));
    const wrapper = mount(CompareGallery, { props: { records: { a: Array.from({ length: 8 }, (_, i) => invoice(i + 1, i !== 1)), b: [] }, labels: { a: '成本发票', b: '开具发票' }, focus: null } });
    await flushPromises();
    expect(wrapper.findAll('.compare-gallery__card')).toHaveLength(6);
    expect(requests).toHaveLength(5);
    expect(wrapper.text()).toContain('XML 原文');
    expect(wrapper.text()).toContain('原票需先将来源设为监控目录');
    await wrapper.get('.actions button:last-child').trigger('click');
    await flushPromises();
    expect(wrapper.findAll('.compare-gallery__card')).toHaveLength(2);
    expect(requests).toHaveLength(7);
    const focus = { label: 'one', record_ids: { a: ['input:2'], b: [] }, steps: [] };
    await wrapper.setProps({ focus });
    await flushPromises();
    expect(wrapper.findAll('.compare-gallery__card')).toHaveLength(1);
    expect(requests).toHaveLength(7);
    await wrapper.get('.compare-gallery__card button.link').trigger('click');
    expect(wrapper.emitted('detail')![0]![0]).toMatchObject({ record_ids: focus.record_ids });
    wrapper.unmount();
  });

  it('uses company receipt capabilities and the actual receipt page, stopping renewals while hidden', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    const active = ref(true);
    const requests: { url: string; body?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => { requests.push({ url, body: String(init.body || '') }); return new Response(JSON.stringify(job(3))); }));
    const receipt: CompareRecord = { ...invoice(1, false), invoice_number: '', id: 'receipt:r1', source_file: '回单.pdf', preview: { kind: 'receipt', company_id: 'co_1', receipt_id: 'r1', token: 'capability', page: 3 } };
    const wrapper = mount(CompareGallery, { props: { records: { a: [], b: [] }, receipts: [receipt], labels: { a: '成本发票', b: '银行流水' }, focus: null }, global: { provide: { [VIEW_ACTIVE as symbol]: active } } });
    await flushPromises();
    expect(requests[0]!.url).toBe('/api/v1/companies/co_1/receipt-preview-jobs');
    expect(JSON.parse(requests[0]!.body!)).toEqual(receipt.preview);
    expect(wrapper.get('.compare-thumbnail img').attributes('src')).toBe('/pages/3');
    await wrapper.get('.compare-thumbnail').trigger('click');
    await flushPromises();
    expect(wrapper.get('img.source-preview__page').attributes('src')).toBe('/pages/3');
    active.value = false;
    await flushPromises();
    const count = requests.length;
    vi.advanceTimersByTime(600_000);
    await flushPromises();
    expect(requests).toHaveLength(count);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    active.value = true;
    await flushPromises();
    expect(requests).toHaveLength(count + 1);
    wrapper.unmount();
  });

  it('discards a late thumbnail response after switching sources', async () => {
    let resolveOld!: (value: Response) => void;
    vi.stubGlobal('fetch', vi.fn((url, init) => JSON.parse(String(init.body)).items[0].invoice_key === '1'
      ? new Promise<Response>((resolve) => { resolveOld = resolve; }) : Promise.resolve(new Response(JSON.stringify(job(2))))));
    const wrapper = mount(CompareGallery, { props: { records: { a: [invoice(1)], b: [] }, labels: { a: '成本发票', b: '开具发票' }, focus: null } });
    await wrapper.setProps({ records: { a: [invoice(2)], b: [] } });
    await flushPromises();
    resolveOld(new Response(JSON.stringify({ ...job(3), files: [{ ...job(3).files[0], page_url_template: '/old/{page_number}' }] })));
    await flushPromises();
    expect(wrapper.get('.compare-thumbnail img').attributes('src')).toBe('/pages/2');
    wrapper.unmount();
  });
});
