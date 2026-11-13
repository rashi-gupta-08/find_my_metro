import { useEffect, useState } from 'react';
import { api, readStored, saveStored } from './api';
import type { Snapshot } from './types';
import { websocketUrl } from './websocketUrl';

export function useArrivals(station: string) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connection, setConnection] = useState<'connecting' | 'live' | 'cached' | 'unavailable'>('connecting');
  useEffect(() => {
    let alive = true;
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout>;
    let lastVersion = 0;
    const key = `metro-live-snapshot:${station}`;
    setSnapshot(readStored<Snapshot | null>(key, null));
    setConnection('connecting');
    if (!station) { setSnapshot(null); setConnection('unavailable'); return; }
    function accept(next: Snapshot) {
      if (!alive || next.station_id !== station || !navigator.onLine || next.snapshot_version < lastVersion) return;
      lastVersion = next.snapshot_version;
      setSnapshot(next);
      saveStored(key, next);
      setConnection('live');
    }
    function connect() {
      if (!alive || !navigator.onLine) return;
      clearTimeout(retry);
      if (socket && socket.readyState < WebSocket.CLOSING) return;
      api.eta(station).then(accept).catch(() => {
        if (alive) setConnection(readStored(key, null) ? 'cached' : 'unavailable');
      });
      socket = new WebSocket(websocketUrl(`/ws/eta/${encodeURIComponent(station)}`));
      socket.onmessage = (message) => {
        try { accept(JSON.parse(message.data)); } catch { /* A bad frame cannot replace the current snapshot. */ }
      };
      socket.onclose = () => {
        if (!alive) return;
        setConnection(readStored(key, null) ? 'cached' : 'unavailable');
        retry = setTimeout(connect, 3000);
      };
      socket.onerror = () => socket?.close();
    }
    function offline() {
      socket?.close();
      clearTimeout(retry);
      setConnection(readStored(key, null) ? 'cached' : 'unavailable');
    }
    window.addEventListener('offline', offline);
    window.addEventListener('online', connect);
    connect();
    return () => { alive = false; clearTimeout(retry); socket?.close(); window.removeEventListener('offline', offline); window.removeEventListener('online', connect); };
  }, [station]);
  return { snapshot, connection };
}
