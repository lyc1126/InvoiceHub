const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const port = Number(process.argv[2] || 4173);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Expected a port from 1024 to 65535');
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff': 'font/woff' };
const server = http.createServer((request, response) => {
  if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405); response.end(); return; }
  let relative;
  try { relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname); }
  catch { response.writeHead(400); response.end(); return; }
  const target = path.resolve(root, '.' + (relative === '/' ? '/index.html' : relative));
  const inside = path.relative(root, target);
  // Expose only website assets. This preview must never serve repository or user invoice files.
  if (inside.startsWith('..') || path.isAbsolute(inside) || !types[path.extname(target)] || relative.includes('\\')) {
    response.writeHead(404); response.end(); return;
  }
  fs.readFile(target, (error, content) => {
    if (error) { response.writeHead(404); response.end(); return; }
    response.writeHead(200, { 'Content-Type': types[path.extname(target)], 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    response.end(request.method === 'HEAD' ? undefined : content);
  });
});
server.on('error', error => { console.error(error.code === 'EADDRINUSE' ? `Port ${port} is occupied. Choose another preview port.` : error.message); process.exitCode = 1; });
server.listen(port, '127.0.0.1', () => console.log(`InvoiceHub website: http://127.0.0.1:${port}/`));
