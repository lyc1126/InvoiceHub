(function () {
  'use strict';
  const canvas = document.getElementById('paper-canvas');
  const context = canvas.getContext('2d');
  if (!context) return;
  const hero = document.querySelector('.hero');
  const button = document.getElementById('motion-toggle');
  const hitArea = document.getElementById('scene-expand');
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = preference.matches;
  let visible = true;
  let frame = 0;
  let width = 0;
  let height = 0;
  let pointerX = 0;
  let pointerY = 0;
  let smoothX = 0;
  let smoothY = 0;
  let lastFrame = 0;
  let spread = 0;
  let hovering = false;
  let pinned = false;
  let ctx;
  const layers = [];
  // Separate cached layers keep the print artwork crisp while papers and labels move independently.
  function layer(dx, dy, angle, paint) {
    const art = document.createElement('canvas');
    art.width = 1200; art.height = 1280;
    ctx = art.getContext('2d');
    ctx.scale(2, 2); ctx.translate(300, 310);
    paint();
    layers.push({ art, dx, dy, angle });
  }

  function receiptPath(x, y, w, h) {
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + h);
    for (let px = x + w; px > x; px -= 10) { ctx.lineTo(px - 5, y + h - 5); ctx.lineTo(Math.max(x, px - 10), y + h); }
    ctx.lineTo(x, y); ctx.closePath();
  }
  function rule(x1, y, x2, color = '#d5d9cc') { ctx.strokeStyle = color; ctx.lineWidth = .8; ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke(); }
  function text(value, x, y, font, color = '#252720') { ctx.font = font; ctx.fillStyle = color; ctx.fillText(value, x, y); }
  function drawArtwork() {
    layers.length = 0;
    layer(62, 8, .07, () => {
    ctx.save(); ctx.rotate(.11);
    ctx.fillStyle = '#c2d594'; receiptPath(-178, -222, 374, 485); ctx.fill();
    ctx.fillStyle = '#eef2e3'; receiptPath(-190, -235, 374, 483); ctx.fill();
    text('PDF / OFD / XML', -162, -200, '10px monospace', '#8c9678');
    for (let y = -162; y < 220; y += 20) rule(-165, y, 156, '#d2d8c5');
    ctx.restore();
    });

    layer(-38, 9, -.045, () => {
    ctx.save(); ctx.rotate(-.115);
    ctx.shadowColor = '#455c2635'; ctx.shadowBlur = 25; ctx.shadowOffsetY = 17; ctx.shadowOffsetX = 8;
    ctx.fillStyle = '#fcfdf6'; receiptPath(-214, -262, 392, 506); ctx.fill(); ctx.shadowColor = 'transparent';
    text('INVOICEHUB', -186, -229, 'bold 10px Arial');
    text('NO. IH-001', 84, -229, '9px monospace');
    rule(-186, -211, 151, '#262a20');
    text('A LITTLE HI.', -186, -189, '8px monospace', '#697558');
    text('A LOT OF ORDER.', 55, -189, '8px monospace', '#697558');
    text('hi', -201, 29, '245px HubDisplay, Arial Black, sans-serif');
    text('HELLO, EVERYTHING IN ORDER.', -184, 66, '9px monospace', '#65704f');
    rule(-186, 87, 151, '#aab49b');
    text('LESS', -185, 111, '9px monospace', '#7e896e');
    text('PAPERWORK', 70, 111, '9px monospace', '#7e896e');
    text('MORE', -185, 133, '9px monospace', '#7e896e');
    text('POSSIBILITY', 59, 133, '9px monospace', '#7e896e');
    rule(-186, 151, 151);
    for (let i = 0, x = -185; i < 77; i++) {
      const barWidth = (i * 13 % 7) < 3 ? 1 : 2;
      ctx.fillStyle = '#343a2b'; ctx.fillRect(x, 168, barWidth, 32); x += barWidth + 2.4;
    }
    text('I N V O I C E H U B  /  O P E N  S O U R C E', -184, 216, '7px monospace', '#65704f');
    ctx.restore();
    });

    layer(-65, -26, -.1, () => {
    ctx.save(); ctx.translate(-214, -142); ctx.rotate(-.22);
    ctx.fillStyle = '#fdfef9'; ctx.strokeStyle = '#a0b269'; ctx.lineWidth = .7;
    ctx.fillRect(-17, -37, 86, 64); ctx.strokeRect(-17, -37, 86, 64);
    text('100%', -6, -8, 'bold 25px Arial', '#353e25');
    text('YOUR FILES', -5, 11, '8px monospace', '#7c865f'); ctx.restore();
    });

    layer(61, 37, .08, () => {
    ctx.save(); ctx.translate(163, 124); ctx.rotate(.13);
    ctx.fillStyle = '#242820'; ctx.fillRect(-99, -32, 179, 90);
    text('ALL IN', -83, -1, 'bold 19px Arial', '#e1ff79');
    text('ORDER.', -83, 29, 'bold 30px Arial', '#e1ff79');
    ctx.strokeStyle = '#d9fb5c'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(44, -10); ctx.lineTo(44, -19); ctx.lineTo(62, -19); ctx.lineTo(62, 0); ctx.moveTo(42, 1); ctx.lineTo(62, -19); ctx.stroke(); ctx.restore();
    });

    layer(55, -35, .14, () => {
    ctx.save(); ctx.translate(174, -201); ctx.rotate(.16);
    ctx.fillStyle = '#e96c51'; ctx.fillRect(-35, -34, 72, 72);
    text('IT JUST', -25, -9, 'bold 10px Arial', '#242520');
    text('ADDS', -25, 9, 'bold 16px Arial', '#242520');
    text('UP.', -25, 27, 'bold 16px Arial', '#242520'); ctx.restore();
    });
  }

  function geometry() {
    const mobile = width <= 720 && height > 430;
    const mobileTop = height <= 600 ? 312 : 352;
    const mobileSpace = height - 53 - mobileTop;
    const scale = mobile ? Math.min(width * .9 / 600, mobileSpace / 600) : Math.min(width <= 900 ? width * .4 / 600 : width * .48 / 560, height * .96 / 640, 1.12);
    const x = mobile ? width * .51 : Math.min(width * .766, width - 315 * scale);
    const y = mobile ? mobileTop + mobileSpace * .54 : height * .487;
    return { x, y, scale };
  }
  function draw() {
    if (!width || !height) return;
    const { x, y, scale } = geometry();
    context.clearRect(0, 0, width, height);
    layers.forEach((item, index) => {
      context.save();
      const depth = (index + 1) * 1.3 * spread;
      context.translate(x + (item.dx * spread + smoothX * depth) * scale, y + (item.dy * spread + smoothY * depth) * scale);
      context.rotate(item.angle * spread);
      context.drawImage(item.art, -300 * scale, -320 * scale, 600 * scale, 640 * scale);
      context.restore();
    });
    canvas.dataset.spread = spread.toFixed(3);
  }
  function resize() {
    const box = hero.getBoundingClientRect(); width = box.width; height = box.height;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0); draw();
    const { x, y, scale } = geometry();
    const inner = document.querySelector('.hero-inner').getBoundingClientRect();
    Object.assign(hitArea.style, { left: `${x - 285 * scale - (inner.left - box.left)}px`, top: `${y - 290 * scale}px`, width: `${555 * scale}px`, height: `${555 * scale}px` });
  }
  function animate(time) {
    frame = 0;
    if (!visible || document.hidden || paused) return;
    // Limit decorative rendering to 30 fps; hidden sections stop scheduling frames entirely.
    const target = hovering || pinned ? 1 : 0;
    if (time - lastFrame >= 32) {
      lastFrame = time;
      spread += (target - spread) * .14;
      smoothX += (pointerX - smoothX) * .12; smoothY += (pointerY - smoothY) * .12;
      if (Math.abs(target - spread) < .001) spread = target;
      draw();
    }
    if (spread !== target || Math.abs(pointerX - smoothX) + Math.abs(pointerY - smoothY) > .005) frame = requestAnimationFrame(animate);
  }
  function schedule() {
    cancelAnimationFrame(frame); frame = 0;
    if (preference.matches) { spread = hovering || pinned ? 1 : 0; smoothX = 0; smoothY = 0; draw(); }
    else if (visible && !document.hidden && !paused) frame = requestAnimationFrame(animate);
    else draw();
    const expanded = hovering || pinned;
    hitArea.setAttribute('aria-pressed', String(expanded));
    hitArea.setAttribute('aria-label', expanded ? '归拢票据与标签' : '展开票据与标签');
  }
  function updateButton() {
    button.setAttribute('aria-pressed', String(paused));
    button.setAttribute('aria-label', paused ? '播放品牌动画' : '暂停品牌动画');
    button.title = paused ? '播放品牌动画' : '暂停品牌动画';
    button.innerHTML = paused ? '<i data-icon="play"></i>' : '<i data-icon="pause"></i>';
    window.invoiceHubRenderIcons?.(button);
    document.documentElement.classList.toggle('motion-paused', paused);
  }
  button.addEventListener('click', () => { paused = !paused; updateButton(); schedule(); });
  preference.addEventListener('change', event => { paused = event.matches; updateButton(); schedule(); });
  hitArea.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse' && (!paused || preference.matches)) { hovering = true; schedule(); } });
  hitArea.addEventListener('pointermove', event => {
    if (event.pointerType !== 'mouse' || paused) return;
    const box = hitArea.getBoundingClientRect();
    pointerX = (event.clientX - box.left) / box.width * 2 - 1; pointerY = (event.clientY - box.top) / box.height * 2 - 1;
    if (!frame) schedule();
  }, { passive: true });
  hitArea.addEventListener('pointerleave', event => {
    // Touch pointerleave precedes click; retain its toggle until the next tap or focus departure.
    if (event.pointerType === 'touch' || event.pointerType === 'pen') return;
    hovering = false; pinned = false; pointerX = 0; pointerY = 0; schedule();
  });
  // Keyboard and touch get the same composition change; reduced motion switches it without interpolation.
  hitArea.addEventListener('click', event => { if (event.detail === 0 || event.pointerType === 'touch' || event.pointerType === 'pen' || !window.matchMedia('(hover: hover)').matches) { pinned = !pinned; hovering = false; if (paused && !preference.matches) { spread = pinned ? 1 : 0; draw(); } schedule(); } });
  hitArea.addEventListener('blur', () => { pinned = false; schedule(); });
  document.addEventListener('visibilitychange', schedule);
  if ('IntersectionObserver' in window) new IntersectionObserver(entries => { visible = entries[0].isIntersecting; schedule(); }).observe(hero);
  new ResizeObserver(resize).observe(hero);
  drawArtwork(); resize(); updateButton(); hero.classList.add('scene-ready'); schedule();
  document.fonts.ready.then(() => { drawArtwork(); draw(); });
})();
