const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/static/js/page-index.js'), 'utf8');
function section(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function previewHarness(api) {
  const state = { filePreviewSelectionItems: Array.from({length: 7003}, (_, i) => ({invoice_key: `${i}`, source_file: `sample-${i}.xml`, source_path: `synthetic/${i}.xml`})),
    filePreviewTargetId: 'captured', filePreviewFileNumber: 1, filePreviewPageNumber: 1, filePreviewRequestId: 0, filePreviewContentRequestId: 0 };
  const refs = {filePreviewModal: {hidden: false}, filePreviewSubtitle: {}};
  const context = vm.createContext({state, refs, app: {api}, closeFilePreview() {}, stopFilePreviewKeepAlive() {}, clearFilePreviewObjectUrl() {},
    setFilePreviewNotice() {}, setFilePreviewState() {}, populateFilePreviewFiles() {}, updateSelectionControls() {}, updateFilePreviewControls() {},
    showFilePreviewError(e) {state.error = e.message;}, loadFilePreviewContent: async () => true, scheduleFilePreviewKeepAlive() {}});
  vm.runInContext(section('function currentFilePreviewEntry()', 'function formatPreviewModified'), context);
  vm.runInContext(section('async function loadFilePreviewJob(', 'function openFilePreview()'), context);
  vm.runInContext(section('function changeFilePreview(delta)', 'function changeFilePreviewPage'), context);
  return {state, context};
}
test('7003 selected files send one current source, retaining position after recovery', async () => {
  const calls = [];
  const {state, context} = previewHarness(async (url, req) => {calls.push(req.body); return {job_id: 'one', files: [{file_number: 1, preview_type: 'pages', page_count: 3}]};});
  await context.loadFilePreviewJob();
  state.filePreviewFileNumber = 7003; state.filePreviewPageNumber = 2;
  await context.loadFilePreviewJob({preservePosition: true, automatic: true});
  assert.equal(calls.length, 2);
  assert.equal(calls[0].items.length, 1);
  assert.equal(calls[1].items[0].invoice_key, '7002');
  assert.equal(calls[1].target_id, 'captured');
  assert.equal(state.filePreviewSelectionItems.length, 7003);
  assert.equal(state.filePreviewPageNumber, 2);
  assert.equal(state.filePreviewFileNumber, 7003);
});
test('late file response cannot replace the next file; errors leave navigation available', async () => {
  const pending = [];
  const {state, context} = previewHarness(() => new Promise((resolve, reject) => pending.push({resolve, reject})));
  const first = context.loadFilePreviewJob();
  state.filePreviewFileNumber = 2;
  const second = context.loadFilePreviewJob({preservePosition: true});
  pending[1].resolve({job_id: 'new', files: [{file_number: 1}]}); await second;
  pending[0].resolve({job_id: 'old', files: [{file_number: 1}]}); await first;
  assert.equal(state.filePreviewJob.job_id, 'new');
  const failed = context.loadFilePreviewJob({preservePosition: true});
  pending[2].reject(new Error('missing')); await failed;
  assert.equal(state.error, 'missing');
  context.changeFilePreview(1);
  pending[3].resolve({job_id: 'next', files: [{file_number: 1}]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.filePreviewJob.job_id, 'next');
  assert.equal(state.filePreviewFileNumber, 3);
});
test('file selector mounts at most 100 labels, including the final partial window', () => {
  const {state, context} = previewHarness();
  const options = [];
  context.refs.filePreviewFileSelect = {replaceChildren() {options.length = 0;}, append(option) {options.push(option);}};
  context.document = {createElement: () => ({}), getElementById: () => ({})};
  vm.runInContext(section('function populateFilePreviewFiles()', 'function populateFilePreviewPages'), context);
  context.populateFilePreviewFiles(); assert.equal(options.length, 100);
  state.filePreviewFileNumber = 7003; context.populateFilePreviewFiles();
  assert.equal(options.length, 3); assert.equal(options[2].value, '7003');
});
test('search and tax intersect without changing selected totals', () => {
  const nodes = {selectionProjectSearch: {value: '12'}, selectionTaxFilter: {value: '13%'}, selectionFilterMeta: {}};
  const projects = [
    {project_name: '钢材', tax_rate: '13%', specs: [{specification: '12'}]},
    {project_name: '钢材', tax_rate: '9%', specs: [{specification: '12'}]},
    {project_name: '运输', tax_rate: '', specs: []},
  ];
  const state = {selectionSummaryPayload: {totals: {value: 500}, cost_breakdown: {projects}}};
  const refs = {selectionSummaryDetails: {}};
  const context = vm.createContext({state, refs, document: {getElementById: id => nodes[id]}, selectionProjectHtml: project => project.tax_rate});
  vm.runInContext(section('function renderFilteredSelectionProjects()', 'document.getElementById("selectionProjectSearch")?.addEventListener'), context);
  context.renderFilteredSelectionProjects();
  assert.equal(refs.selectionSummaryDetails.innerHTML, '13%');
  assert.equal(state.selectionSummaryPayload.totals.value, 500);
  nodes.selectionProjectSearch.value = ''; nodes.selectionTaxFilter.value = 'missing';
  context.renderFilteredSelectionProjects(); assert.match(nodes.selectionFilterMeta.textContent, /1 \/ 3/);
});
test('ambiguous delete response queries the journal and never repeats the mutation', async () => {
  const calls = [];
  const trashUi = {job: {job_id: 'id', state: 'prepared'}, confirm: {}, cancel: {}, status: {}, busy: false, submitted: false};
  const context = vm.createContext({trashUi, app: {api: async (url, options) => {
    calls.push(options?.method || 'GET');
    if (options) throw new Error('lost response');
    return {state: 'running', files: [], trashed_count: 0};
  }}, renderTrashResult(job) {trashUi.job = job;}, clearSelectedInvoices() {}, refreshAll: async () => {}});
  vm.runInContext(section('async function confirmInvoiceTrash()', 'document.getElementById("trashSelectedInvoicesBtn")?.addEventListener'), context);
  await context.confirmInvoiceTrash(); await context.confirmInvoiceTrash();
  assert.deepEqual(calls, ['POST', 'GET', 'GET']);
  assert.equal(trashUi.confirm.textContent, '读取执行结果');
});
