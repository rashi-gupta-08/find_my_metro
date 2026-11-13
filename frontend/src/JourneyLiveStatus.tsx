import { Clock3, Radio, ShieldCheck } from 'lucide-react';
import { sourceName } from './api';
import type { JourneySourceStatus, Route, Station } from './types';

const label = (value: string) => value.replaceAll('_', ' ');
const time = (value: string) => new Date(value).toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit'});

export function JourneyLiveStatus({route, stations, now, cached}: {route: Route; stations: Station[]; now: number; cached: boolean}) {
  const statuses = route.source_statuses ?? [];
  if (!statuses.length) return null;
  const stationName = (id?: string) => stations.find(station => station.id===id)?.name ?? id;
  const contexts = [...new Set(route.steps.filter(step => step.kind==='ride').map(step => step.context).filter(Boolean))];
  function render(status: JourneySourceStatus, index: number) {
    const expired = Boolean(status.valid_until && now>=Date.parse(status.valid_until));
    const live = !cached && !expired && status.source!=='schedule';
    const source = expired ? 'schedule' : status.source;
    const age = status.last_observed_at ? Math.max(0, Math.floor((now-Date.parse(status.last_observed_at))/1000)) : null;
    const next = status.next_arrival;
    const scheduled = next && (next.source==='schedule' || expired) && next.scheduled_arrival_at;
    const arrivalLabel = scheduled || next?.source==='schedule' ? 'scheduled arrival' : expired ? 'saved prediction' : 'predicted arrival';
    return <div className="journey-source" key={index} data-source={source}>
      <div className="journey-source-heading"><strong>{stationName(status.boarding_station_id)}</strong><span className={`pill ${live ? 'good' : ''}`}>{live ? sourceName[source] : cached ? 'Saved status' : 'Static estimate'}</span></div>
      <p><Radio size={13}/>{label(status.planned_context)} section · {status.preferred_source==='static_and_phone' ? 'Static time + validated phone evidence' : status.preferred_source==='crowd' ? 'GPS-checked community evidence preferred' : 'Evidence checked during handover'}</p>
      {next && <p><Clock3 size={13}/>{next.train_code} · {arrivalLabel} {time(scheduled || next.arrival_at)}{cached && ' · saved'}</p>}
      {live ? <>
        <p><ShieldCheck size={13}/>{status.scope==='station_service' ? 'Independent reports agree at this station' : `Accepted train context: ${label(status.train_context ?? status.planned_context)}`} · trust {status.trust_score?.toFixed(2)} (heuristic)</p>
        <p className="small muted">Observation {age}s ago · {status.source==='estimate' ? 'Bounded position estimate; no new observation' : label(status.freshness_status)}</p>
        {status.delay_seconds>=60 && <p className="delay">+{Math.ceil(status.delay_seconds/60)} min {status.scope==='station_service' ? 'reported extra wait' : 'delay against the timetable'} · counted once at boarding</p>}
        {status.source==='estimate' && status.transition && <p className="handover-status">Handover in progress · {Math.max(0,Math.ceil((Date.parse(status.transition.deadline)-now)/1000))}s remaining</p>}
      </> : <p className="small muted">{cached ? `Last saved evidence${age===null ? '' : ` ${age}s ago`}; reconnect to refresh.` : expired ? 'Live evidence expired. The static baseline is being refreshed.' : status.next_arrival ? 'Timetable fallback; live tracking evidence is unavailable.' : 'No identified upcoming train yet. Travel time uses the static baseline.'}</p>}
    </div>;
  }
  return <section className="journey-live" aria-label="Journey source status"><h3>Journey source status</h3><div className="journey-contexts">{contexts.map(context => <span className="pill" key={context}>{context}</span>)}</div>{statuses.map(render)}<p className="small muted">Source selection follows the configured station and segment context. Community updates describe station service; they do not identify a particular train. Live evidence expires after 30 seconds.</p></section>;
}
