const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/static/js/temporary-recognition.js'), 'utf8');
function harness(fetch) {
  const nodes = new Map();
  class Node {
    constructor() { this.children = []; this.dataset = {}; this.style = {}; this.open = true; this.hidden = false; this.classList = {add(){}, remove(){}, toggle(){}}; }
    replaceChildren(...items) { this.children = items; }
    append(...items) { this.children.push(...items); }
    setAttribute() {} addEventListener() {} focus() {} scrollTo() {}
    querySelector() { return this.body ||= new Node(); }
  }
  const node = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const context = vm.createContext({fetch, console, URL: {revokeObjectURL(){}, createObjectURL(){return "blob:test";}}, setTimeout:()=>1, clearTimeout(){}, matchMedia:()=>({matches:false}),
    document: {getElementById: id => id === 'temporarySettingsForm' ? null : node(id), createElement:()=>new Node()},
    window: {addEventListener(){}}, navigator: {clipboard:{writeText:async()=>{}}}});
  vm.runInContext(source.replace(/\}\)\(\);\s*$/, 'globalThis.subject = {state, refreshSession, showSession, move, renderQueue, addFiles, showPreview, verifyPreview, backFromPreview};})();'), context);
  return { ...context.subject, node };
}
const response = session => ({ok: true, json:async()=>({session})});
const ready = id => ({id, status:'ready', count:1, completed:1, title:id, created_at:'2026-10-09T00:00:00Z', unavailable:[], items:[{name:'sample.xml', status:'ready', result:{amount:'100'}}]});

test('a late historical response cannot overwrite a newer thread', async()=> {
  const pending = [];
  const h = harness(()=>new Promise(resolve=>pending.push(resolve)));
  const old = h.showSession('old');
  const current = h.showSession('new');
  pending[1](response(ready('new'))); await current;
  pending[0](response(ready('old'))); await old;
  assert.equal(h.state.result.id, 'new');
});

test('source invalidation clears already rendered invoice data', async()=> {
  const h = harness(async()=>response({...ready('job'), unavailable:['sample.xml']}));
  h.state.view = 'results'; h.state.selected = 'job'; h.state.result = ready('job');
  h.node('temporaryTable').querySelector().append({textContent:'private cached value'});
  await h.refreshSession();
  assert.equal(h.state.result, null);
  assert.equal(h.node('temporaryTable').querySelector().children.length, 0);
  assert.equal(h.node('temporaryResults').hidden, true);
  assert.match(h.node('temporaryMessage').textContent, /无法查看/);
});

test('transport failure hides cached results until originals can be checked again', async()=> {
  const h = harness(async()=> {throw new Error('offline');});
  h.state.view='results'; h.state.selected='job'; h.state.result=ready('job');
  await h.refreshSession();
  assert.equal(h.state.result, null);
  assert.equal(h.node('temporaryResults').hidden, true);
});

test('queue sorting preserves identities and refuses changes while recognizing', ()=> {
  const h = harness();
  h.state.files = ['a','b','c'].map(id=>({id,name:id,size:100}));
  h.move(2,0); assert.deepEqual(h.state.files.map(f=>f.id), ['c','a','b']);
  h.state.running='job'; h.move(0,2); assert.deepEqual(h.state.files.map(f=>f.id), ['c','a','b']);
});

test('a late picker response is discarded after closing or switching the dialog', async()=> {
  let resolve;
  const h = harness(()=>new Promise(done=>{resolve=done;}));
  const pending = h.addFiles(); h.state.generation += 1;
  resolve({ok:true,json:async()=>({files:[{id:'late',name:'late.xml',size:1}]})}); await pending;
  assert.equal(h.state.files.length, 0);
  assert.equal(h.state.busy, false);
});

test('a late failed revalidation cannot clear the newer visible thread', async()=> {
  let reject;
  const h = harness(()=>new Promise((_, fail)=>{reject=fail;}));
  h.state.view='results'; h.state.selected='old';
  const pending = h.refreshSession();
  h.state.generation += 1; h.state.selected='new'; h.state.result=ready('new');
  reject(new Error('old failure')); await pending;
  assert.equal(h.state.result.id, 'new');
  assert.equal(h.node('temporaryResults').hidden, false);
});


test('XML preview is plain text and goes back to the draft', async()=> {
  const h = harness(async(url)=>({ok:true,json:async()=>url.endsWith('/text') ? {text:'<script>alert(1)</script>',encoding:'utf-8'} : {type:'text',pages:0}}));
  await h.showPreview({id:'a',name:'sample.xml'});
  const content = h.node('temporaryPreviewBody').children[0];
  assert.equal(content.textContent, '<script>alert(1)</script>');
  assert.equal(h.state.view, 'preview');
  h.backFromPreview(); assert.equal(h.state.view, 'draft');
  assert.equal(h.node('temporaryPreviewBody').children.length, 0);
});

test('preview source validation failure clears content and offers retry', async()=> {
  let failed = false;
  const h = harness(async(url)=> {if(failed) throw new Error('source gone'); return {ok:true,json:async()=>url.endsWith('/text') ? {text:'original',encoding:'utf-8'} : {type:'text',pages:0}};});
  await h.showPreview({id:'a',name:'sample.xml'});
  failed = true; await h.verifyPreview();
  assert.equal(h.node('temporaryPreviewBody').children.length, 0);
  assert.equal(h.node('temporaryPreviewRetry').hidden, false);
});

test('late preview content cannot replace a newer file', async()=> {
  let resolve;
  const h = harness(async(url)=>({ok:true,json:async()=> url.includes('/a/') && url.endsWith('/text') ? new Promise(done=>{resolve=done;}) : url.endsWith('/text') ? {text:'new',encoding:'utf-8'} : {type:'text',pages:0}}));
  const first = h.showPreview({id:'a',name:'old.xml'});
  while(!resolve) await Promise.resolve();
  await h.showPreview({id:'b',name:'new.xml'});
  resolve({text:'old',encoding:'utf-8'}); await first;
  assert.equal(h.node('temporaryPreviewBody').children[0].textContent, 'new');
});
