import { ArrowRight, Clock3, Footprints, GitMerge, MapPin, Radio, TrainFront } from 'lucide-react';
import type { Line, Preference, Route, RouteStep, Station } from './types';
import { JourneyLiveStatus } from './JourneyLiveStatus';
export const preferences: [Preference,string][] = [['fastest','Shortest time'],['fewest_changes','Fewer interchanges'],['least_walking','Less walking'],['shortest_distance','Shortest distance']];
const mins = (seconds: number) => `${Math.ceil(seconds/60)} min`;

export function JourneyResults({ routes, stations, lines, selected, onSelect, now, cached, onStatus }: { routes: Route[]; stations: Station[]; lines: Line[]; selected: string; onSelect: (id: string) => void; now: number; cached: boolean; onStatus?: (id: string) => void }) {
  const name = (id: string) => stations.find(s => s.id === id)?.name ?? id;
  function grouped(steps: RouteStep[]) {
    const legs: RouteStep[][] = [];
    for (const step of steps) {
      const previous = legs.at(-1);
      if (step.kind === 'ride' && previous?.[0].kind === 'ride' && (previous[0].family_id ?? previous[0].line_id) === (step.family_id ?? step.line_id)) previous.push(step);
      else legs.push([step]);
    }
    return legs;
  }
  return <div className="journey-options">{routes.map((route,index) => <article className={`panel journey-card ${selected === route.id ? 'journey-selected' : ''}`} key={route.id}>
    <div className="journey-top"><div className="recommendation-tags">{route.recommendations?.length ? route.recommendations.map(p => <span className="pill" key={p}>{preferences.find(([id]) => id === p)?.[1]}</span>) : <span className="pill">Alternative {index+1}</span>}</div><strong>{mins(route.duration_seconds)}</strong></div>
    <div className="journey-metrics"><span><GitMerge size={15}/>{route.transfers} {route.transfers === 1 ? 'interchange' : 'interchanges'}</span><span><Footprints size={15}/>{route.walking_metres ?? '—'} m walking estimate</span><span><MapPin size={15}/>{route.station_count ?? route.steps.filter(s => s.kind === 'ride').length+1} stations</span><span>{route.distance_metres ? `${(route.distance_metres/1000).toFixed(1)} km approx.` : ''}</span></div>
    <div className="journey-line-strip">{grouped(route.steps).filter(leg => leg[0].kind === 'ride').map((leg,i) => <span key={i}><i style={{background: lines.find(l => l.id === leg[0].line_id)?.color}}/>{lines.find(l => l.id === leg[0].line_id)?.name.replace(' · Inderlok branch','')}{i < grouped(route.steps).filter(l => l[0].kind === 'ride').length-1 && <ArrowRight size={12}/>}</span>)}</div>
    <details className="journey-detail" open={selected === route.id || undefined}><summary>Stations, directions and walking connections</summary><ol>{grouped(route.steps).map((leg,index) => {
      const first=leg[0],last=leg.at(-1)!, line=lines.find(l => l.id === first.line_id);
      const context=[...new Set(leg.map(s => s.context).filter(Boolean))].join(' → ');
      return <li key={index} className={first.kind === 'transfer' ? 'walk-leg' : 'ride-leg'}><span className="leg-icon" style={{background: first.kind === 'ride' ? line?.color : '#edf4f5'}}>{first.kind === 'ride' ? <TrainFront size={17}/> : <Footprints size={17}/>}</span><div><strong>{first.kind === 'ride' ? `${name(first.from_station_id)} → ${name(last.to_station_id)}` : first.from_station_id === first.to_station_id ? `Change at ${name(first.from_station_id)}` : `Walk to ${name(first.to_station_id)}`}</strong><p>{first.kind === 'ride' ? `${line?.name} · ${mins(leg.reduce((n,s) => n+s.seconds,0))} · ${leg.length} stops` : `${first.walking_metres ?? '—'} m estimated · ${mins(first.seconds)}${first.requires_exit ? ' · Exit, walk and re-enter; separate ticket' : ''}`}</p>{first.kind === 'ride' && <><p className="leg-context"><Radio size={12}/>{context || 'Static baseline'} · {leg.some(s => s.source !== 'schedule') ? 'Accepted live evidence + static time' : 'Operator travel-time estimate'}</p><details className="station-sequence"><summary>Show all {leg.length+1} stations</summary><div>{[first.from_station_id,...leg.map(s => s.to_station_id)].map((id,i) => <span key={i}>{name(id)}</span>)}</div></details></>}{first.delay_seconds ? <p className="delay">+{mins(first.delay_seconds)} {first.source === 'crowd' ? 'community-reported delay' : 'observed delay'} at boarding</p> : null}</div></li>;
    })}</ol><JourneyLiveStatus route={route} stations={stations} now={now} cached={cached}/></details>
    <div className="journey-bottom"><span><Clock3 size={13}/>{cached ? 'Saved travel estimate' : route.source === 'schedule' ? 'Static travel estimate' : 'Includes accepted live delay'}</span><div className="journey-actions">{onStatus && <button className="outline" onClick={()=>onStatus(route.id)}>Journey status</button>}<button className="outline" onClick={() => onSelect(selected === route.id ? '' : route.id)}>{selected === route.id ? 'Collapse journey' : 'View this journey'}</button></div></div>
  </article>)}</div>;
}
