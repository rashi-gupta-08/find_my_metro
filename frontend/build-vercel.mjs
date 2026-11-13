import { cp, mkdir, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { backendOrigin, vercelConfig } from './vercel-config.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(root, '.vercel', 'output');
const require = createRequire(import.meta.url);

try {
  // Validate before compiling. Never publish a bundle pointing at localhost or a
  // placeholder, or silently present a frontend-only deployment as a working app.
  const backend = backendOrigin(process.env.BACKEND_URL);
  const config = vercelConfig(backend);
  const env = { ...process.env, VITE_WS_ORIGIN: backend.replace(/^https:/, 'wss:') };
  const commands = [
    [require.resolve('typescript/bin/tsc'), '-b'],
    [path.join(path.dirname(require.resolve('vite/package.json')), 'bin', 'vite.js'), 'build'],
    [path.join(root, 'build-offline.mjs')],
  ];
  for (const command of commands) {
    const result = spawnSync(process.execPath, command, { cwd: root, env, stdio: 'inherit' });
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(`Frontend build failed (${result.status ?? result.signal}).`);
  }
  // output is a fixed directory beneath this script's frontend folder.
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  await cp(path.join(root, 'dist'), path.join(output, 'static'), { recursive: true });
  await writeFile(path.join(output, 'config.json'), JSON.stringify(config, null, 2) + '\n');
  console.log('Vercel output prepared. REST uses the same-origin proxy; WebSockets use the hosted API.');
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
