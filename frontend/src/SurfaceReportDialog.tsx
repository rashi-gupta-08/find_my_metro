import { useEffect, useState } from 'react';
import { MapPin, X } from 'lucide-react';
import type { Network, SurfaceReport } from './types';
import { StationPicker } from './StationPicker';
import type { SurfaceReportController } from './useSurfaceReports';

export function SurfaceReportDialog({ network, controller, initialStation, onClose }: { network: Network; controller: SurfaceReportController; initialStation: string; onClose: () => void }) {
  const stations=network.stations;
  const [station,setStation]=useState(stations.some(s => s.id === initialStation) ? initialStation : stations[0]?.id ?? '');
  const [line,setLine]=useState('');
  const [direction,setDirection]=useState('outbound');
  const [delay,setDelay]=useState('5');
  const [eventType,setEventType]=useState('delayed');
  const [note,setNote]=useState('');
  const [sending,setSending]=useState(false);
  const {queue,message,setMessage}=controller;
  const lines=network.lines.filter(l => l.station_ids.includes(station));
  const selected=lines.find(l => l.id === line);
  const name=(id: string) => network.stations.find(s => s.id === id)?.name ?? id;
  useEffect(() => { if (!lines.some(l => l.id === line)) setLine(lines[0]?.id ?? ''); },[station,line,network]);
  useEffect(() => { const close=(e: KeyboardEvent) => { if (e.key==='Escape') onClose(); }; window.addEventListener('keydown',close); return () => window.removeEventListener('keydown',close); },[onClose]);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setSending(true); setMessage('');
    let report: SurfaceReport | undefined;
    try {
      const location=await new Promise<GeolocationPosition>((resolve,reject) => navigator.geolocation ? navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,maximumAge:0,timeout:15000}) : reject(new Error('GPS is unavailable on this device.')));
      if (location.coords.accuracy>100) throw new Error('GPS accuracy needs to be within 100 metres. Try again outside the station.');
      report={event_id:crypto.randomUUID(),station_id:station,line_id:line,direction,event_type:eventType,delay_seconds:eventType==='delayed' ? Math.round(Number(delay)*60) : 0,observed_at:new Date(location.timestamp).toISOString(),latitude:location.coords.latitude,longitude:location.coords.longitude,accuracy_m:location.coords.accuracy,note};
      await controller.send(report);
    } catch (e) {
      setMessage((e as Error).message || 'Location permission is needed to check this report.');
    } finally { setSending(false); }
  }
  const retry=controller.retry;
  return <div className="modal-backdrop" onClick={onClose}><section className="modal panel" role="dialog" aria-modal="true" aria-labelledby="surface-title" onClick={e => e.stopPropagation()}><button className="modal-close" aria-label="Close report" onClick={onClose}><X size={21}/></button><MapPin size={27} className="teal"/><h2 id="surface-title">Report a station update</h2><p>Share what you see while waiting for the metro. Location checks that you are near the selected station. Underground location may be unavailable; the app then keeps its static estimate.</p><form onSubmit={submit}><StationPicker label="Report at" value={station} onChange={setStation} stations={stations} lines={network.lines}/><label>LINE<select aria-label="Report line" value={line} onChange={e => setLine(e.target.value)}>{lines.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label><label>TOWARDS<select value={direction} onChange={e => setDirection(e.target.value)}><option value="outbound">{selected ? name(selected.station_ids.at(-1)!) : ''}</option><option value="inbound">{selected ? name(selected.station_ids[0]) : ''}</option></select></label><label>UPDATE TYPE<select aria-label="Report type" value={eventType} onChange={e => setEventType(e.target.value)}><option value="delayed">Extra waiting time</option><option value="arrived">Train arrived</option><option value="departed">Train departed</option><option value="crowded">Crowded platform</option></select></label>{eventType==='delayed' && <label>OBSERVED EXTRA WAIT (MINUTES)<input aria-label="Observed extra wait in minutes" type="number" min="0" max="60" step="1" required value={delay} onChange={e => setDelay(e.target.value)}/></label>}<label>NOTE<textarea maxLength={500} value={note} onChange={e => setNote(e.target.value)} placeholder="What did you observe?"/></label><button className="primary" disabled={sending || !line || !station}>{sending ? 'Checking location…' : 'Check GPS and send report'}</button></form>{message && <p className="report-result" role="status">{message}</p>}{queue.length>0 && <div className="queue-notice"><span>{queue.length} queued reports</span><button className="outline" disabled={sending} onClick={retry}>Retry upload</button></div>}<p className="small muted">Three accounts must independently agree. Each report must still be less than 30 seconds old, within a maximum 120-second collection window. Arrival, departure and crowding reports do not become delay measurements. Community reports indicate a service delay; a phone location alone cannot identify or track a specific train. Location is requested only when you send a report.</p></section></div>;
}
