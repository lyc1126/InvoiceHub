/* WS-08/09: synthetic design; only fixed demo snapshots may persist locally. No network, credentials or business IO. */
(() => {
  const host = document.createElement('div');
  host.id = 'serverConnectionPrototype';
  document.getElementById('addBtn').after(host);
  // Shadow DOM and a separate state prevent this preview from changing existing prototype modules.
  const root = host.attachShadow({mode: 'open'});
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seed = () => [
    {company:'商贸',dir:'成本发票',net:1000,tax:130,id:'a', name:'材料采购_001.pdf', amount:1130, cached:true, kind:'PDF'},
    {company:'商贸',dir:'费用报销',net:200,tax:18,id:'b', name:'运输服务_002.xml', amount:218, cached:true, kind:'XML'},
    {company:'商贸',dir:'开具发票',net:500,tax:65,id:'c', name:'设备配件_003.ofd', amount:565, cached:false, kind:'OFD'},
    {id:'bank',company:'商贸',dir:'银行流水',name:'收付款.xlsx',amount:null,value:1130,cached:true,kind:'XLSX'},
    {id:'deduct',company:'商贸',dir:'进项抵扣',name:'勾选清单.xlsx',amount:null,value:130,cached:true,kind:'XLSX'},
    {id:'payroll',company:'商贸',dir:'工资社保',name:'工资汇总.xlsx',amount:null,value:250,cached:true,kind:'XLSX'},
    {id:'e',company:'建设',dir:'成本发票',net:400,tax:52,name:'建设采购_005.pdf',amount:452,cached:true,kind:'PDF'},
    {id:'u',company:'未归属公司',dir:'待归属',net:300,tax:39,name:'待归属_006.pdf',amount:339,cached:true,kind:'PDF'},
    {id:'scan',company:'商贸',dir:'费用报销',name:'扫描件_待识别.png',amount:null,cached:false,kind:'PNG'}
  ];
  const s = {mode:'smb', form:false, online:false, connected:false, open:false,
    address:'smb://nas.example.test/财务', user:'reader', port:'22', path:'/财务',
    favorites:['smb://nas.example.test/财务','smb://archive.example.test/共享'], favorite:0,
    files:[], tabs:[], active:'summary', currentDir:'', directoryMenu:false, rootName:'连接目录', query:'', generation:0,
    busy:false, epoch:0, stage:'', percent:0, updated:false, stale:false,
    message:'合成演示 · 尚未连接', last:'尚无完整缓存', crashed:false, wide:false, capability:'cursor', sourceKey:'', sourceLabel:'未选择来源', cursor:0, pending:false, reconcile:false};
  root.innerHTML = `<style>
    :host{display:block;font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#252820}
    *{box-sizing:border-box}button,input,select{font:inherit}button{cursor:pointer}button:disabled{cursor:default;opacity:.45}
    button{border:1px solid #d7dbd0;background:white;color:inherit;border-radius:7px;padding:8px 11px}
    button:hover:not(:disabled){background:#f1f5e8}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #659ef5;outline-offset:2px}
    [hidden]{display:none!important}.primary{background:#2778e5;color:white;border-color:#2778e5}.primary:hover:not(:disabled){background:#1961bc}
    .entry{display:flex;align-items:center;gap:8px;margin:0 8px 6px;width:calc(100% - 16px);border:0;background:none;text-align:left;font-weight:600}
    .server-link-icon{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
    .entry small{font-size:10px;color:#69725d;background:#e9eddf;border-radius:3px;padding:2px 4px}
    dialog{padding:0;border:1px solid #d7dbd0;border-radius:16px;width:min(620px,94vw);max-height:90vh;overflow:auto;color:inherit;background:#fafbf8;box-shadow:0 24px 80px #0003}
    dialog::backdrop{background:#151c254d}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:52px 20px 18px;border-bottom:1px solid #e2e5dd}
    h2,h3,p{margin:0}h2{font-size:20px}h3{font-size:15px}.body{padding:20px}.muted{color:#70776b;font-size:12px;line-height:1.7}
    .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.spread{justify-content:space-between}.section{margin-top:16px}
    .switch{display:flex;gap:6px;margin-bottom:18px}.switch button[aria-selected=true]{background:#e6efff;border-color:#8eb6f1;color:#195ebc}
    label{display:grid;gap:6px;font-size:12px;margin-bottom:12px}input,select{width:100%;min-width:0;border:1px solid #cbd2c2;border-radius:7px;background:white;padding:10px;color:#252820}
    .fields{display:grid;grid-template-columns:1fr 100px;gap:12px}.fields label{margin:0}.favorite{display:block;text-align:left;width:100%;border:0;border-radius:0;padding:10px}
    .favorite[aria-pressed=true]{background:#e8eef8}.favorites{border:1px solid #dce0d4;border-radius:8px;overflow:hidden;margin:10px 0}
    .ssh-card{text-align:center;padding:25px 15px;background:white;border:1px solid #e0e4d8;border-radius:12px}.ssh-card p{margin:10px}
    .note{padding:10px 12px;background:#edf3fb;border-radius:8px;color:#375777;font-size:12px;line-height:1.6}
    .panel.wide{width:calc(100vw - var(--panel-left,0px))}.dock{position:fixed;right:10px;top:5px;z-index:81;display:flex;gap:4px;background:#f3f5ef;border:1px solid #d7dbd0;border-radius:8px;padding:3px}.dock button{padding:5px 8px}
    .panel{position:fixed;z-index:70;right:0;top:0;bottom:0;width:min(560px,calc(100vw - var(--panel-left,0px)));max-width:calc(100vw - var(--panel-left,0px));background:#fafbf8;border-left:1px solid #d7dbd0;box-shadow:-12px 0 45px #19261915;display:flex;flex-direction:column}
    .directory-menu{padding:8px 12px;border-bottom:1px solid #d7dbd0;background:white;max-height:240px;overflow:auto;flex-shrink:0}.directory-menu button{display:block;width:100%;border:0;text-align:left;padding:9px}.directory-toggle{border:0;background:none;padding:0 3px;font-weight:600}.empty{text-align:center;padding:30px;color:#70776b}
    .badge{font-size:11px;padding:3px 7px;border-radius:20px;background:#e6f3e6;color:#307145}.badge.off{background:#fff0dc;color:#936213}
    .path{padding:12px 18px;border-bottom:1px solid #e2e5dd;overflow-wrap:anywhere}.path button{border:0;padding:3px;background:none;color:#326caf}
    .tabs{display:flex;overflow:auto;gap:3px;border-bottom:1px solid #dbe0d3;padding:8px 12px 0;background:#f0f3eb;min-height:45px}
    .tab{position:relative;display:flex;align-items:center;white-space:nowrap;border-radius:7px 7px 0 0;background:none;border-color:transparent;padding:8px}
    .tab[aria-selected=true]{background:#fafbf8;border-color:#dbe0d3}.tab .close{margin-left:6px;border:0;padding:0 4px;background:none}
    .line{position:absolute;bottom:0;left:0;height:3px;background:#3689f5;width:0;transition:width .2s}
    .scroll{overflow:auto;flex:1;padding:18px}.tools{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}.tools button{font-size:12px}
    .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:16px 0}.stats div{border:1px solid #e0e5d5;padding:12px;border-radius:8px;background:white}.stats b{display:block;font-size:20px;margin-bottom:4px}
    table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:11px 5px;border-bottom:1px solid #e5e9de}th{color:#6b7563;font-weight:500}.file{border:0;padding:0;background:none;text-align:left;color:#285f9d;overflow-wrap:anywhere}
    .footer{padding:12px 18px;border-top:1px solid #dce1d4;background:#f0f3eb;line-height:1.6;font-size:12px}.warning{color:#8b5c1c;background:#fff3dd}
    .paper{background:white;border:1px solid #d8ddd0;margin:20px 0;padding:28px 20px;min-height:250px;box-shadow:0 4px 15px #0000000a;color:#34434c}.paper h3{text-align:center;color:#9b6154;font-size:19px;letter-spacing:3px;border-bottom:2px solid #bb8b79;padding-bottom:16px}.paper p{margin-top:18px}
    pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f3eb;padding:16px;border-radius:8px}.error{color:#9f3229;margin:10px 0;min-height:18px}
    @media(max-width:600px){.head{padding:14px}.panel>.head{padding-top:52px}h2{font-size:17px}.body,.scroll{padding:14px}.stats div{padding:8px}.stats b{font-size:17px}}
    @media(prefers-reduced-motion:reduce){*{transition:none!important}}
  </style>
  <button class="entry" data-action="configure"><svg class="server-link-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="4" y="3" width="16" height="13" rx="2"/><path d="M12 16v5M3.5 21h17"/><circle cx="12" cy="21" r="1.6" fill="currentColor" stroke="none"/></svg><span>服务器链接</span><small>（试验版）</small></button>
  <div class="dock" aria-label="文件面板控制"><button data-action="toggle" aria-label="展开服务器文件标签页" title="展开 / 收起文件标签页" aria-expanded="false">◫</button><button data-action="maximize" aria-label="放大文件面板" title="放大 / 还原文件面板">⤢</button></div>
  <dialog aria-label="服务器链接（试验版）"></dialog><aside class="panel" aria-label="服务器文件浏览" hidden></aside>`;
  const dialog = root.querySelector('dialog'), panel = root.querySelector('.panel');
  function config() {
    dialog.innerHTML = `<div class="head"><h2>服务器链接（试验版）</h2><button data-action="close-config" aria-label="关闭配置">✕</button></div><div class="body">
      <div class="switch" role="tablist" aria-label="连接方式"><button role="tab" data-mode="smb" aria-selected="${s.mode==='smb'}">共享文件夹</button><button role="tab" data-mode="ssh" aria-selected="${s.mode==='ssh'}">SSH / SFTP</button></div>
      <p class="note">交互原型 · 全部为合成数据，请勿填写真实凭据。</p>
      ${s.mode==='smb' ? `<label class="section">服务器地址<input name="address" value="${esc(s.address)}" placeholder="smb://服务器/共享目录"></label><h3>个人收藏服务器</h3>
      <div class="favorites">${s.favorites.map((f,i)=>`<button class="favorite" data-favorite="${i}" aria-pressed="${s.favorite===i}">▱ ${esc(f)}</button>`).join('') || '<p class="body muted">暂无收藏</p>'}</div>
      <div class="row"><button data-action="favorite-add" aria-label="添加收藏">＋</button><button data-action="favorite-remove" ${s.favorite<0?'disabled':''} aria-label="移除收藏">−</button><span class="muted">收藏仅在本次原型会话保留</span></div>` : `
      <div class="ssh-card section"><div style="font-size:30px">▱ ··· ▤</div><p>通过 SSH 连接到远程设备</p><button data-action="ssh-add">${s.form?'重新填写':'添加'}</button></div>
      ${s.form ? `<div class="section fields"><label>主机<input name="address" value="${esc(s.address)}" placeholder="files.example.test"></label><label>端口<input name="port" value="${esc(s.port)}" inputmode="numeric"></label></div>
      <label class="section">用户名<input name="user" value="${esc(s.user)}"></label><label>认证方式<select name="auth"><option>SSH Agent / 系统密钥（演示）</option><option>密码（演示，不输入真实密码）</option></select></label>
      <label>远程根目录<input name="path" value="${esc(s.path)}"></label><div class="note">主机指纹：SHA256:DEMO-ONLY<br>实际连接需先向管理员核对指纹；变化时停止连接。</div><label class="row section"><input name="fingerprint" type="checkbox" style="width:auto">已了解首次连接需要核对主机指纹（模拟）</label>`:''}`}
      <p class="error" role="alert" id="configError"></p><div class="row spread"><span class="muted">只读访问 · 不切换监控目录</span><div class="row"><button data-action="browse" ${s.mode==='ssh'&&!s.form?'disabled':''}>浏览</button><button class="primary" data-action="connect" ${s.mode==='ssh'&&!s.form?'disabled':''}>连接（演示）</button></div></div>
      <details class="section muted"><summary>SSH 可以做什么？</summary>SSH 提供加密远程登录、命令和端口转发；这里仅用 SFTP 浏览与读取文件。无需开启远程终端。外网可用 SSH 端口或 VPN；SMB 建议只在局域网或 VPN 中使用。</details></div>`;
  }
  function readForm() {
    for (const key of ['address','port','user','path']) {
      const el=dialog.querySelector(`[name="${key}"]`); if(el) s[key]=el.value.trim();
    }
  }
  function validate() {
    readForm(); let error='';
    if(s.mode==='smb'&&!/^smb:\/\/[^\s/@]+\/[^\s]+$/.test(s.address)) error='请填写 smb://主机/共享目录，不要在地址中填写密码。';
    if(s.mode==='ssh') {
      if(!/^[a-zA-Z0-9.-]+$/.test(s.address)||!s.user||!s.path.startsWith('/')) error='请填写主机、用户名与以 / 开头的远程根目录。';
      else if(!/^\d+$/.test(s.port)||+s.port<1||+s.port>65535) error='端口应为 1—65535。';
      else if(!dialog.querySelector('[name="fingerprint"]')?.checked) error='请先确认主机指纹核对说明。';
    }
    dialog.querySelector('#configError').textContent=error; return !error;
  }
  const roles=['成本发票','开具发票','银行流水','进项抵扣','工资社保','费用报销'];
  const directoryPaths=['商贸','建设','未归属公司','空文件夹','其他资料',...['商贸','建设'].flatMap(company=>roles.map(role=>`${company}/${role}`)),'未归属公司/待归属'];
  const folderName=path=>path?({'商贸':'示例商贸有限公司','建设':'示例建设有限公司','未归属公司':'未归属公司的目录'}[path]||path.split('/').at(-1)):s.rootName;
  const fileDirectory=f=>`${f.company}/${f.dir}`;
  const within=(path,parent)=>!parent||path===parent||path.startsWith(parent+'/');
  const readable=f=>['PDF','OFD','XML','XLSX'].includes(f.kind);
  function childDirectories(){return s.connected?directoryPaths.filter(path=>path.split('/').slice(0,-1).join('/')===s.currentDir):[];}
  function panelFiles(){return s.files.filter(f=>readable(f)&&within(fileDirectory(f),s.currentDir));}
  function total(){return panelFiles().reduce((sum,f)=>sum+(f.amount||0),0).toFixed(2);}
  function selectDirectory(path){
    if(path&&!directoryPaths.includes(path))return;
    // Browsing changes only the cached projection scope, never the source root or monitor target.
    s.currentDir=path;s.directoryMenu=false;s.active='summary';s.query='';draw();
  }
  function breadcrumbs(directory=s.currentDir){
    const parts=directory?directory.split('/'):[];
    return [{path:'',name:s.rootName},...parts.map((_,i)=>{const path=parts.slice(0,i+1).join('/');return {path,name:folderName(path)};})].map(item=>`<button data-dir-path="${esc(item.path)}">${esc(item.name)}</button>`).join(' › ');
  }
  function directoryMenu(){return `<div class="directory-menu" id="serverDirectoryMenu" role="menu" aria-label="选择子目录" ${s.directoryMenu?'':'hidden'}>${s.currentDir?`<button role="menuitem" data-dir-path="${esc(s.currentDir.split('/').slice(0,-1).join('/'))}">↑ 上一级目录</button>`:''}${childDirectories().map(path=>`<button role="menuitem" data-dir-path="${esc(path)}">▱ ${esc(folderName(path))}</button>`).join('')||'<p class="muted">没有子目录</p>'}</div>`;}
  function draw() {
    root.querySelector('[data-action=toggle]').setAttribute('aria-expanded',String(s.open));
    root.querySelector('[data-action=toggle]').setAttribute('aria-label',s.open?'收起服务器文件标签页':'展开服务器文件标签页');
    root.querySelector('[data-action=maximize]').setAttribute('aria-label',s.wide?'还原文件面板':'放大文件面板');
    panel.classList.toggle('wide',s.wide);panel.hidden=!s.open;updatePanelBoundary();if(!s.open)return;
    const file=s.files.find(f=>f.id===s.active);
    panel.innerHTML=`<div class="head"><div><h2>服务器文件</h2><span class="muted">${esc(s.sourceLabel)} · 合成演示</span></div><div class="row"><span class="badge ${s.online?'':'off'}">${s.online?'已连接':'离线'}</span><button data-action="hide" aria-label="收起服务器文件栏">✕</button></div></div>
      <div class="path">${breadcrumbs(file?fileDirectory(file):s.currentDir)}<div class="muted">${esc(s.sourceLabel)} · 只读 · 本机缓存独立保存</div></div>
      <div class="tabs" role="tablist" aria-label="服务器文件标签">${[{id:'summary',name:folderName(s.currentDir)},...s.tabs.map(id=>s.files.find(f=>f.id===id)).filter(Boolean)].map(f=>`<div class="tab" role="tab" tabindex="0" aria-selected="${s.active===f.id}" data-tab="${f.id}"><span>${esc(f.name)}</span>${f.id==='summary'?`<button class="directory-toggle" data-action="directory-menu" aria-label="选择 ${esc(f.name)} 的子目录" aria-haspopup="menu" aria-expanded="${s.directoryMenu}" aria-controls="serverDirectoryMenu">▾</button>`:`<button class="close" data-close-tab="${f.id}" aria-label="关闭 ${esc(f.name)}">×</button>`}${s.active===f.id&&s.busy?`<span class="line" style="width:${s.percent}%"></span>`:''}</div>`).join('')}</div>
      ${directoryMenu()}
      <div class="scroll"><div class="note ${s.stale?'warning':''}" role="status">${esc(s.message)}</div>
      <div class="tools"><button data-action="refresh" ${!s.online||s.busy?'disabled':''}>刷新目录</button><button data-action="change" ${!s.online||s.busy||s.updated?'disabled':''}>模拟增删改</button><button data-action="disconnect" ${!s.online?'disabled':''}>模拟断连</button><button data-action="reconnect" ${s.online?'disabled':''}>${s.crashed?'恢复应用':'重新连接'}</button><button data-action="crash" ${s.crashed?'disabled':''}>模拟崩溃</button><button data-action="queue" ${s.online||!s.connected||s.updated?'disabled':''}>离线模拟服务器增删改</button><button data-action="invalidate" ${!s.connected?'disabled':''}>模拟游标过期</button>${s.busy?'<button data-action="cancel">取消加载</button>':''}</div><label>服务器变更能力（模拟）<select name="capability"><option value="cursor" ${s.capability==='cursor'?'selected':''}>可靠变更游标 · 仅取增删改</option><option value="standard" ${s.capability==='standard'?'selected':''}>标准 SMB/SFTP · 轻量目录核对</option></select></label>
      ${file ? preview(file) : `<div class="stats"><div><b>${panelFiles().length}</b><span class="muted">可读取文件（含子目录）</span></div><div><b>¥ ${total()}</b><span class="muted">发票价税合计（示例）</span></div><div><b>v${s.generation}</b><span class="muted">完整缓存版本</span></div></div>
      <p class="muted">当前汇总：${esc(folderName(s.currentDir))}（含子目录）；只读缓存，不重复解析未变文件。</p><label class="section">筛选文件<input name="filter" placeholder="输入文件名称" value="${esc(s.query)}"></label><table><thead><tr><th>文件 / 文件夹</th><th>缓存</th><th>价税合计</th></tr></thead><tbody id="fileRows">${rows()}</tbody></table>
      <details class="section muted"><summary>刷新与完整重建的区别</summary>刷新先显示旧结果，仅解析新增和修改；删除仅移出投影。完整重建重新校验全部来源，是诊断兜底。本原型只模拟流程，不测量真实解析性能。</details>`}</div>
      <div class="footer"><b>${s.busy?esc(s.stage)+' · '+s.percent+'%（模拟）':s.online?'读取完成':s.generation?'显示离线缓存':'尚无完整缓存'}</b><br><span class="muted">上次完整汇总：${s.last} · ${s.stale?'尚未确认最新':'合成快照'}<br>缓存不等于备份 · 断连不清空汇总，不把未知当删除</span></div>`;
  }
  function rows(){
    const dirs=childDirectories().filter(path=>folderName(path).includes(s.query));
    const direct=s.files.filter(f=>fileDirectory(f)===s.currentDir&&f.name.includes(s.query));
    let output=dirs.map(path=>`<tr><td><button class="file" data-dir-path="${esc(path)}">▱ ${esc(folderName(path))}</button></td><td>目录</td><td>—</td></tr>`).join('');
    output+=direct.map(f=>`<tr><td>${readable(f)?`<button class="file" data-file="${f.id}">▧ ${esc(f.name)}</button>`:esc(f.name)}${!readable(f)?'<div class="muted">待识别，不计入汇总</div>':''}</td><td>${f.cached?'已缓存':'按需下载'}</td><td>${f.amount===null?'—':'¥ '+f.amount.toFixed(2)}</td></tr>`).join('');
    if(s.currentDir==='其他资料')output+='<tr><td>说明.zip</td><td>不支持读取</td><td>—</td></tr>';
    if(!s.generation)output+='<tr><td class="empty" colspan="3">尚无完整缓存，请先连接服务器</td></tr>';
    else if(!panelFiles().length)output+='<tr><td class="empty" colspan="3">无可读取的文件</td></tr>';
    else if(!output)output+='<tr><td class="empty" colspan="3">未找到匹配文件</td></tr>';
    return output;
  }
  function preview(f){
    if(!f.cached)return `<div class="paper"><h3>${esc(f.name)}</h3><p>本机尚无完整副本。</p><p>${s.online?'正在按需加载…':'连接后下载，当前无法离线预览。'}</p></div>`;
    if(!['PDF','OFD','XML'].includes(f.kind))return `<div class="paper"><h3>${esc(f.name)}</h3><p>合成元信息 · ${esc(f.kind)}；此类型不提供票面预览。</p></div>`;
    const content=f.kind==='XML'?`<pre>${esc(`<Invoice>\n  <Name>合成发票</Name>\n  <Total>${f.amount.toFixed(2)}</Total>\n</Invoice>`)}</pre>`:`<div class="paper"><h3>电子发票 · 合成示意</h3><p>文件：${esc(f.name)}</p><p>购买方：示例公司</p><p>价税合计：¥ ${f.amount.toFixed(2)}</p><p class="muted">这是原型票面示意，不是真实 ${f.kind} 渲染。</p></div>`;
    return `<p class="section muted">${s.online?'已缓存副本':'离线副本 · 当前源文件状态未核验'} · 只读</p>${content}<button data-action="summary">返回目录汇总</button><p class="section muted">正式实现复用受限 PNG / 纯文本预览；未联网核验时不开放业务写入、打印或导出。</p>`;
  }
  // An epoch cancels delayed demo work. Interrupted scans keep the last complete generation.
  function stop(message){s.epoch++;s.busy=false;s.stale=true;s.message=message;draw();}
  function run(stages, done){
    const epoch=++s.epoch;s.busy=true;s.percent=0;let step=0;
    const tick=()=>{if(epoch!==s.epoch)return;
      if(step===stages.length){s.busy=false;done();draw();return;}
      s.stage=stages[step];s.percent=Math.round((step+1)/(stages.length+1)*100);step++;draw();setTimeout(tick,550);
    };tick();
  }
  function openFile(id){
    const f=s.files.find(item=>item.id===id);if(!f)return;
    if(!s.tabs.includes(id))s.tabs.push(id);s.active=id;draw();
    if(!f.cached&&s.online&&!s.busy)run(['下载完整副本','校验文件版本','准备预览'],()=>{f.cached=true;saveSnapshot();s.message='文件副本已缓存，可在断连后只读查看（模拟）';});
  }
  function connect(){
    if(!validate())return;
    const key=JSON.stringify([s.mode,s.address,s.mode==='ssh'?s.port:'system',s.user,s.mode==='ssh'?s.path:'share-root']);
    if(s.sourceKey)saveSnapshot();
    stop('切换来源');s.sourceKey=key;s.sourceLabel=s.mode==='ssh'?`${s.user}@${s.address}:${s.port}${s.path}`:s.address;
    const prior=cache.get(key);
    Object.assign(s,prior?structuredClone(prior):{files:[],generation:0,cursor:0,updated:false,pending:false,reconcile:false,last:'尚无完整缓存'});
    s.tabs=[];s.active='summary';s.currentDir='';s.directoryMenu=false;s.rootName=(s.mode==='ssh'?s.path:s.address).split('/').filter(Boolean).at(-1)||'共享根目录';s.query='';s.open=true;s.online=false;s.connected=true;s.crashed=false;s.stale=true;
    s.message=prior?'已显示此来源完整缓存，正在续接变更（模拟）':'首次连接，建立完整目录清单（模拟）';dialog.close();
    if(prior)resume();
    else run(['验证服务器身份','首次枚举完整目录','解析并发布首次快照'],()=>{s.files=seed();s.generation=1;s.online=true;s.stale=false;s.last='刚刚（模拟）';s.message='首次缓存已建立；后续按来源能力获取变化。';saveSnapshot();});
  }

  function refresh(changed){
    if(!s.online||s.busy)return;s.active='summary';s.message='保留旧列表，后台核对增删改（模拟）';
    const delta=s.capability==='cursor'&&!s.reconcile;
    run([delta?'续接可靠变更游标（不枚举）':'完整轻量核对目录（不重复解析旧票）',changed?'解析新增 1、修改 1':'复用未变化的解析缓存','原子发布全部模块快照'],()=>{
      if(changed&&!s.updated){s.files=s.files.filter(f=>f.id!=='c').map(f=>f.id==='b'?{...f,amount:327,net:300,tax:27}:f);s.files.push({id:'d',company:'商贸',dir:'成本发票',name:'新到货物_004.pdf',amount:904,net:800,tax:104,cached:true,kind:'PDF'});s.generation++;s.updated=true;s.cursor++;s.tabs=s.tabs.filter(id=>s.files.some(f=>f.id===id));}
      s.pending=false;s.reconcile=false;s.stale=false;s.last='刚刚（模拟）';
      s.message=(delta?'变更游标：枚举 0 项；':'轻量核对完整目录；')+(changed?'新增 1、修改 1、删除 1；解析 2 份，其余复用。':'无变化：解析 0 份，保留原缓存版本。');saveSnapshot();
    });
  }
  function resume(){
    if(!s.connected){config();dialog.showModal();return;}
    s.crashed=false;
    if(!s.generation){s.message='首次连接未完成，请重新连接建立缓存。';config();dialog.showModal();draw();return;}
    s.online=true;refresh(s.pending);
  }
  // Cache keys include protocol, server, principal and root. Only fixed synthetic profiles persist;
  // custom form input stays in memory and never enters browser storage.
  const storageKey='invoicehub-server-demo-v2';
  const knownKeys=new Set([
    JSON.stringify(['smb','smb://nas.example.test/财务','system','reader','share-root']),
    JSON.stringify(['smb','smb://archive.example.test/共享','system','reader','share-root']),
    JSON.stringify(['ssh','files.example.test','22','reader','/财务'])
  ]);
  const cache=new Map();
  function snapshot(){return {files:structuredClone(s.files),generation:s.generation,cursor:s.cursor,updated:s.updated,pending:s.pending,reconcile:s.reconcile,last:s.last};}
  function saveSnapshot(){
    if(!s.sourceKey||!s.generation)return;
    cache.set(s.sourceKey,snapshot());
    try{localStorage.setItem(storageKey,JSON.stringify([...cache].filter(([key])=>knownKeys.has(key))));}
    catch{ /* Storage denial does not discard this session's complete snapshot. */ }
  }
  function validSnapshot(v){
    if(!v||typeof v.updated!=='boolean'||typeof v.pending!=='boolean'||typeof v.reconcile!=='boolean'||v.generation!==(v.updated?2:1)||v.cursor!==(v.updated?1:0)||v.last!=='刚刚（模拟）'||!Array.isArray(v.files))return false;
    let expected=seed();
    if(v.updated){expected=expected.filter(f=>f.id!=='c').map(f=>f.id==='b'?{...f,amount:327,net:300,tax:27}:f);expected.push({id:'d',company:'商贸',dir:'成本发票',name:'新到货物_004.pdf',amount:904,net:800,tax:104,cached:true,kind:'PDF'});}
    // Treat storage as untrusted: restore only exact demo records, with cache availability mutable.
    return v.files.length===expected.length&&v.files.every((f,i)=>typeof f.cached==='boolean'&&JSON.stringify({...f,cached:false})===JSON.stringify({...expected[i],cached:false}));
  }
  try{
    const saved=JSON.parse(localStorage.getItem(storageKey)||'[]');
    if(Array.isArray(saved))for(const item of saved){if(Array.isArray(item)&&knownKeys.has(item[0])&&validSnapshot(item[1]))cache.set(item[0],item[1]);}
  }catch{ /* Corrupt demo storage falls back to a fresh, explicitly empty source. */ }
  const scopeStyle=document.createElement('style');
  scopeStyle.textContent='.main>#tabs{padding-right:94px}';document.head.append(scopeStyle);
  // Both widths are clamped to the existing main area. ResizeObserver follows sidebar dragging;
  // the server panel must never cover the local module rail or company sidebar.
  function updatePanelBoundary(){
    const left=Math.min(window.innerWidth,Math.max(0,document.querySelector('.main').getBoundingClientRect().left));
    panel.style.setProperty('--panel-left',left+'px');
  }
  window.addEventListener('resize',updatePanelBoundary);
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(updatePanelBoundary).observe(document.querySelector('.main'));
  root.addEventListener('change',e=>{if(e.target.name==='capability'){s.capability=e.target.value;draw();}});
  root.addEventListener('input',e=>{if(e.target.name==='filter'){s.query=e.target.value;root.querySelector('#fileRows').innerHTML=rows();}});
  root.addEventListener('click',e=>{
    const el=e.target.closest('button,[data-tab]');if(!el||el.disabled)return;
    if(el.hasAttribute('data-dir-path')){selectDirectory(el.dataset.dirPath);return;}
    if(el.dataset.mode){readForm();s.mode=el.dataset.mode;s.address=s.mode==='smb'?'smb://nas.example.test/财务':'files.example.test';config();return;}
    if(el.dataset.favorite!==undefined){s.favorite=+el.dataset.favorite;s.address=s.favorites[s.favorite];config();return;}
    if(el.dataset.closeTab){s.tabs=s.tabs.filter(id=>id!==el.dataset.closeTab);if(s.active===el.dataset.closeTab)s.active='summary';draw();return;}
    if(el.dataset.tab){s.active=el.dataset.tab;draw();return;}
    if(el.dataset.file){openFile(el.dataset.file);return;}
    switch(el.dataset.action){
      case 'configure':config();dialog.showModal();break;
      case 'close-config':dialog.close();break;
      case 'ssh-add':s.form=true;config();break;
      case 'favorite-add':readForm();if(!validate())break;if(!s.favorites.includes(s.address))s.favorites.push(s.address);s.favorite=s.favorites.indexOf(s.address);config();break;
      case 'favorite-remove':s.favorites.splice(s.favorite,1);s.favorite=-1;config();break;
      case 'browse':case 'connect':connect();break;
      case 'toggle':s.open=!s.open;if(!s.open)s.directoryMenu=false;draw();break;
      case 'maximize':s.wide=!s.wide;s.open=true;draw();break;
      case 'directory-menu':s.directoryMenu=!s.directoryMenu;draw();if(s.directoryMenu)root.querySelector('[role=menuitem]')?.focus();break;
      case 'queue':s.pending=true;s.message='服务器已模拟增删改，缓存仍保持原版本；重连后获取变化。';saveSnapshot();draw();break;
      case 'invalidate':s.reconcile=true;saveSnapshot();s.stale=true;s.message='游标已过期：下次刷新需完整轻量核对目录，仍复用解析缓存。';draw();break;
      case 'hide':s.open=false;s.directoryMenu=false;draw();break;

      case 'summary':s.active='summary';draw();break;
      case 'refresh':refresh(false);break;
      case 'change':refresh(true);break;
      case 'disconnect':s.online=false;stop('连接已中断，保留上次完整汇总；未完成扫描不计删除（模拟）。');break;
      case 'crash':s.online=false;s.crashed=true;stop('已模拟任务崩溃：未发布结果丢弃，完整汇总与完成副本保留。点击“恢复应用”。');break;
      case 'reconnect':resume();break;
      case 'cancel':stop('已取消加载，保留上次完整结果与已完成副本（模拟）。');break;
    }
  });
  root.addEventListener('keydown',e=>{
    if(['Enter',' '].includes(e.key)&&e.target.dataset.tab){e.preventDefault();s.active=e.target.dataset.tab;draw();}
    if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)&&e.target.dataset.tab){e.preventDefault();const tabs=[...root.querySelectorAll('[data-tab]')];let i=tabs.indexOf(e.target);i=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;s.active=tabs[i].dataset.tab;draw();root.querySelector(`[data-tab="${s.active}"]`)?.focus();}
    if(e.key==='Escape'&&s.directoryMenu){s.directoryMenu=false;draw();root.querySelector('.directory-toggle')?.focus();e.stopPropagation();return;}
    if(e.target.getAttribute('role')==='menuitem'&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const items=[...root.querySelectorAll('[role=menuitem]')];const i=items.indexOf(e.target);items[e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();return;}
    if(e.key==='Escape'&&!dialog.open&&s.open){s.open=false;draw();e.stopPropagation();}
    if((e.key==='Tab'||e.key==='Escape')&&dialog.open)e.stopPropagation();
  });
  // Opening files preserves the local sidebar and every existing module's context.
  const reopen=document.createElement('button');reopen.className='entry';reopen.textContent='↗ 打开服务器文件列表';reopen.hidden=false;
  root.append(reopen);reopen.onclick=()=>{s.open=true;draw();};
  dialog.addEventListener('close',()=>{reopen.hidden=false;});
  draw();
})();
