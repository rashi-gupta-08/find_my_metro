export function resolveWebSocketUrl(path: string, origin: string): string {
  const url = new URL(path, origin);
  if (url.protocol === 'https:') url.protocol = 'wss:';
  else if (url.protocol === 'http:') url.protocol = 'ws:';
  if (!['ws:', 'wss:'].includes(url.protocol)) throw new Error('Invalid WebSocket origin');
  return url.toString();
}

export function websocketUrl(path: string): string {
  return resolveWebSocketUrl(path, import.meta.env.VITE_WS_ORIGIN || location.origin);
}
