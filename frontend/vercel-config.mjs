// Build Output API configuration. Only the public backend origin enters this file.
export function backendOrigin(value) {
  if (!value) throw new Error('Set BACKEND_URL in Vercel to your hosted HTTPS FastAPI origin before deploying.');
  let url;
  try { url = new URL(value); }
  catch { throw new Error('BACKEND_URL must be a valid public HTTPS origin.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
      ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname.toLowerCase()) ||
      url.hostname.endsWith('.localhost') || url.hostname.endsWith('.example.com')) {
    throw new Error('BACKEND_URL must be your public HTTPS backend origin, without credentials, a path, query or fragment.');
  }
  return url.origin;
}

export function vercelConfig(origin) {
  const backend = backendOrigin(origin);
  const websocket = backend.replace(/^https:/, 'wss:');
  return {
    version: 3,
    routes: [
      {
        src: '/(.*)',
        headers: {
          'X-Content-Type-Options': 'nosniff',
          'X-Frame-Options': 'DENY',
          'Referrer-Policy': 'strict-origin-when-cross-origin',
          'Permissions-Policy': 'geolocation=(self)',
          'Content-Security-Policy': `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ${websocket}; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`,
        },
        continue: true,
      },
      // Keep REST and session cookies on the frontend origin. Query strings are
      // forwarded by Vercel; API responses must never fall through to the SPA.
      { src: '/api/(.*)', dest: `${backend}/api/$1`, headers: { 'Cache-Control': 'no-store' } },
      { src: '/assets/(.*)', headers: { 'Cache-Control': 'public, max-age=31536000, immutable' }, continue: true },
      { src: '/(?:index\\.html|sw\\.js|manifest\\.webmanifest)?', headers: { 'Cache-Control': 'no-cache' }, continue: true },
      { handle: 'filesystem' },
      // WebSockets go directly to the backend; missing API/assets remain 404s.
      { src: '/(?!api(?:/|$)|ws(?:/|$)|assets(?:/|$))[^.]*', dest: '/index.html', headers: { 'Cache-Control': 'no-cache' } },
    ],
  };
}
