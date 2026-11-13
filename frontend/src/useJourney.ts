import { useEffect, useState } from 'react';
import { api, readStored, saveStored } from './api';
import type { JourneySnapshot, Network, Preference } from './types';
import { offlineAqua } from './offlineAqua';

export function useJourney(origin: string, destination: string, preference: Preference, network: Network | null, enabled: boolean) {
  const networkVersion=network?.version ?? '';
  const [snapshot, setSnapshot] = useState<JourneySnapshot | null>(null);
  const [connection, setConnection] = useState<'connecting' | 'live' | 'cached' | 'unavailable'>('connecting');
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!enabled || !origin || !destination) { setSnapshot(null); setError(''); return; }
    let alive = true;
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let lastVersion = 0;
    let requestRunning = false;
    let failures = 0;
    const abort = new AbortController();
    const key = `metro-journey:${networkVersion}:${origin}:${destination}:${preference}`;
    const cached = readStored<JourneySnapshot | null>(key, null);
    const matches = (next: JourneySnapshot) => next.origin === origin && next.destination === destination && next.preference === preference && (!next.network_version || next.network_version === networkVersion);
    const usableCache = cached && matches(cached) ? cached : null;
    const fallback=usableCache ?? offlineAqua(network,origin,destination,preference);
    setSnapshot(fallback);
    setConnection(fallback ? 'cached' : 'connecting'); setError('');
    function accept(next: JourneySnapshot) {
      if (!alive || !navigator.onLine || !matches(next) || next.snapshot_version < lastVersion) return;
      lastVersion = next.snapshot_version;
      setSnapshot(next); saveStored(key, next); setConnection('live'); setError(''); failures = 0;
    }
    async function fetchSnapshot() {
      if (requestRunning || !navigator.onLine) return;
      requestRunning = true;
      try { accept(await api.routes(origin, destination, preference, AbortSignal.any([abort.signal, AbortSignal.timeout(8000)]))); }
      catch (problem) {
        if (alive && !abort.signal.aborted) { setConnection(readStored(key, null) || fallback ? 'cached' : 'unavailable'); setError((problem as Error).message); }
      } finally { requestRunning = false; }
    }
    function connect() {
      if (!alive || !navigator.onLine) return;
      clearTimeout(retry);
      if (socket && socket.readyState < WebSocket.CLOSING) return;
      // Reconnection always refreshes via REST before accepting ordered frames.
      void fetchSnapshot();
      const query = new URLSearchParams({origin, destination, preference});
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/journeys?${query}`);
      socket.onmessage = message => { try { const next = JSON.parse(message.data); if (next.type === 'journey_snapshot') accept(next); } catch { /* Retain the last valid frame. */ } };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (!alive) return;
        setConnection(readStored(key, null) || fallback ? 'cached' : 'unavailable');
        failures += 1;
        retry = setTimeout(connect, Math.min(30000, 3000 * failures));
      };
    }
    function offline() { socket?.close(); clearTimeout(retry); setConnection(readStored(key, null) || fallback ? 'cached' : 'unavailable'); }
    window.addEventListener('offline', offline); window.addEventListener('online', connect);
    connect();
    // REST remains usable if a reverse proxy or connection blocks WebSockets.
    const poll = setInterval(() => { if (!socket || socket.readyState !== WebSocket.OPEN) void fetchSnapshot(); }, 15000);
    return () => { alive = false; abort.abort(); clearTimeout(retry); clearInterval(poll); socket?.close(); window.removeEventListener('offline', offline); window.removeEventListener('online', connect); };
  }, [origin, destination, preference, networkVersion, enabled, revision]);
  return { snapshot, connection, error, refresh: () => setRevision(current => current + 1) };
}
