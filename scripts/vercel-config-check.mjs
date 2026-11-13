import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { backendOrigin, vercelConfig } from '../frontend/vercel-config.mjs';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('../frontend/src/websocketUrl.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { resolveWebSocketUrl } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));

for (const value of [undefined, '', 'not-a-url', 'http://metro.test', 'https://localhost', 'https://127.0.0.1',
  'https://[::1]', 'https://your-backend.example.com', 'https://name:secret@metro.test',
  'https://metro.test/api', 'https://metro.test?token=secret', 'https://metro.test/#fragment']) {
  assert.throws(() => backendOrigin(value), 'Missing/private/placeholder or malformed backend must fail before deployment');
}
assert.equal(backendOrigin('https://metro.test/'), 'https://metro.test');
const config = vercelConfig('https://metro.test');
assert.equal(config.version, 3);
const api = config.routes.find(route => route.src === '/api/(.*)');
assert.equal(api.dest, 'https://metro.test/api/$1');
assert.equal(api.headers['Cache-Control'], 'no-store');
const path = '/api/v1/routes';
const query = '?origin=station-a&destination=station-b&preference=fewest_changes';
assert.equal(path.replace(new RegExp(`^${api.src}$`), api.dest) + query,
  'https://metro.test/api/v1/routes' + query);
const fallback = config.routes.at(-1);
const match = new RegExp(`^${fallback.src}$`);
assert(match.test('/journey'));
for (const path of ['/api/v1/auth/me', '/api', '/ws/journeys', '/assets/missing.js', '/missing.js']) assert(!match.test(path));
assert(config.routes[0].headers['Content-Security-Policy'].includes("connect-src 'self' wss://metro.test;"));
assert.equal(resolveWebSocketUrl('/ws/journeys' + query, 'https://metro.test'), 'wss://metro.test/ws/journeys' + query);
assert.equal(resolveWebSocketUrl('/ws/eta/a', 'http://localhost:5173'), 'ws://localhost:5173/ws/eta/a');
assert.equal(resolveWebSocketUrl('/ws/eta/a', 'wss://metro.test'), 'wss://metro.test/ws/eta/a');
assert.throws(() => resolveWebSocketUrl('/ws/eta/a', 'ftp://metro.test'));
console.log('Vercel configuration checks passed: backend validation, REST routing, no-store, SPA exclusions, CSP, cloud and local sockets.');
