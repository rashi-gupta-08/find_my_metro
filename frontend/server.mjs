// Local serving of the built app; containers use nginx. No development compiler runs here.
import http from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = process.env.STATIC_ROOT ? path.resolve(process.env.STATIC_ROOT) : path.join(path.dirname(fileURLToPath(import.meta.url)), 'dist');
const port = Number(process.env.PORT || 5173);
const target = new URL(process.env.BACKEND_URL || 'http://127.0.0.1:8000');
const csp = process.env.MOBILE_CLIENT === 'true'
  ? "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
  : "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'";
const headers = { 'Content-Security-Policy': csp, 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'strict-origin-when-cross-origin', 'Permissions-Policy': 'geolocation=(self)' };
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.json': 'application/json', '.webmanifest':'application/manifest+json', '.wasm':'application/wasm', '.ttf':'font/ttf', '.woff2':'font/woff2' };

function permitted(request) {
  return [`localhost:${port}`, `127.0.0.1:${port}`].includes(request.headers.host || '');
}
function proxyHeaders(request) {
  const copied = { ...request.headers };
  for (const key of ['forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto']) delete copied[key];
  return copied;
}
const handleRequest = async (request, response) => {
  if (!permitted(request)) { response.writeHead(400).end('Invalid host'); return; }
  if (/^\/api(?:\/|$)/.test(request.url)) {
    const upstream = http.request({ hostname: target.hostname, port: target.port, path: request.url, method: request.method, headers: proxyHeaders(request), timeout: 20000 }, (result) => {
      response.writeHead(result.statusCode, { ...result.headers, ...headers }); result.pipe(response);
    });
    upstream.on('timeout', () => upstream.destroy());
    upstream.on('error', () => { if (!response.headersSent) response.writeHead(503, { ...headers, 'Content-Type': 'application/json' }); response.end('{"detail":"Service temporarily unavailable"}'); });
    request.on('aborted', () => upstream.destroy()); request.pipe(upstream); return;
  }
  if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405, headers).end(); return; }
  let filename;
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (/^\/(?:@|src\/|node_modules\/)/.test(pathname)) { response.writeHead(404, headers).end(); return; }
    filename = path.resolve(root, '.'+pathname);
    if (filename !== root && !filename.startsWith(root+path.sep)) { response.writeHead(403, headers).end(); return; }
    if (filename === root) filename = path.join(root, 'index.html');
    let info;
    try { info = await stat(filename); }
    catch {
      if (path.extname(pathname)) { response.writeHead(404, headers).end(); return; }
      filename = path.join(root, 'index.html'); info = await stat(filename);
    }
    if (!info.isFile()) { response.writeHead(404, headers).end(); return; }
    response.writeHead(200, { ...headers, 'Content-Type': types[path.extname(filename)] || 'application/octet-stream',
      'Content-Length': info.size, 'Cache-Control': filename.includes(path.sep+'assets'+path.sep) ? 'public, max-age=31536000, immutable' : 'no-cache' });
    if (request.method === 'HEAD') response.end();
    else createReadStream(filename).on('error', () => response.destroy()).pipe(response);
  } catch { response.writeHead(400, headers).end(); }
};
const server = http.createServer(handleRequest);
const ipv6 = http.createServer(handleRequest);
server.requestTimeout = 20000;
server.headersTimeout = 10000;
ipv6.requestTimeout = 20000;
ipv6.headersTimeout = 10000;
const upgrade = (request, socket, head) => {
  if (!permitted(request) || !(/^\/ws\/eta\//.test(request.url) || /^\/ws\/journeys(?:\?|$)/.test(request.url))) { socket.destroy(); return; }
  const upstream = http.request({ hostname: target.hostname, port: target.port, path: request.url, headers: proxyHeaders(request), timeout: 10000 });
  upstream.on('upgrade', (result, connection, extra) => {
    socket.write(`HTTP/1.1 ${result.statusCode} ${result.statusMessage}\r\n`+Object.entries(result.headers).map(([name,value]) => `${name}: ${value}`).join('\r\n')+'\r\n\r\n');
    if (extra.length) socket.write(extra);
    if (head.length) connection.write(head);
    socket.pipe(connection).pipe(socket);
    connection.on('error', () => socket.destroy()); socket.on('error', () => connection.destroy()); socket.on('close', () => connection.destroy());
  });
  upstream.on('response', () => socket.destroy()); upstream.on('error', () => socket.destroy()); upstream.on('timeout', () => upstream.destroy()); upstream.end();
};
server.on('upgrade', upgrade);
ipv6.on('upgrade', upgrade);
server.listen(port, '127.0.0.1', () => console.log(`FindMyMetro: http://localhost:${port}`));
ipv6.on('error', (error) => { if (error.code !== 'EAFNOSUPPORT') console.error('IPv6 loopback listener:', error.code); });
ipv6.listen(port, '::1');
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { server.close(); ipv6.close(); setTimeout(() => process.exit(0), 5000).unref(); });
