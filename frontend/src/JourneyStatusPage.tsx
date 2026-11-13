import { ArrowRight, Clock3, Footprints, GitMerge, Info, MapPin, Radio, RefreshCw, Route as RouteIcon, TrainFront, Wifi, WifiOff } from 'lucide-react';
import { JourneyLiveStatus } from './JourneyLiveStatus';
import { StationPicker } from './StationPicker';
import type { Network, Route, RouteStep } from './types';
import './journey-status.css';

type Props = {
  network: Network; origin: string; destination: string;
  onOrigin: (value: string) => void; onDestination: (value: string) => void;
  requested: boolean; loading: boolean; routes: Route[]; selected: string;
  onSelect: (value: string) => void; onLoad: () => void; onRefresh: () => void;
  onPlan: () => void; onReport: () => void; connection: string;
  generatedAt: string; error: string; reason: string; now: number;
};

const duration = (seconds: number) => `${Math.ceil(seconds / 60)} min`;
const contextLabel = (context?: string) => context === 'underground' ? 'Underground' : context === 'surface' ? 'Surface' : context === 'transition' ? 'Transition' : 'Metro';

export function JourneyStatusPage(props: Props) {
  const { network, origin, destination, requested, loading, routes, selected, connection, now } = props;
  const route = routes.find(item => item.id === selected) ?? routes[0];
  const connected = connection === 'live';
  const name = (id: string) => network.stations.find(station => station.id === id)?.name ?? id;
  const selectedIndex = routes.findIndex(item => item.id === route?.id);
  const groups: RouteStep[][] = [];
  for (const step of route?.steps ?? []) {
    const previous = groups.at(-1);
    if (step.kind === 'ride' && previous?.[0].kind === 'ride' &&
      previous[0].context === step.context &&
      (previous[0].family_id ?? previous[0].line_id) === (step.family_id ?? step.line_id)) previous.push(step);
    else groups.push([step]);
  }
  const snapshotAge = props.generatedAt ? Math.max(0, Math.floor((now - Date.parse(props.generatedAt)) / 1000)) : null;

  return <section className="section journey-status-page" aria-label="Selected journey status">
    <div className="status-page-header">
      <div><h1>Journey status</h1><p>Travel time, station updates and the source behind your journey.</p></div>
      {requested && route && <span className={`pill ${connected ? 'live' : ''}`} role="status">{connected ? <Wifi size={14}/> : <WifiOff size={14}/>} {connected ? 'Updates connected' : 'Saved journey'}</span>}
    </div>

    <form className="panel status-journey-picker" onSubmit={event => { event.preventDefault(); props.onLoad(); }}>
      <StationPicker label="From" value={origin} onChange={props.onOrigin} stations={network.stations} lines={network.lines}/>
      <span className="status-picker-arrow" aria-hidden="true"><ArrowRight size={20}/></span>
      <StationPicker label="To" value={destination} onChange={props.onDestination} stations={network.stations} lines={network.lines}/>
      <button className="primary" type="submit" disabled={!origin || !destination || origin === destination || loading}><RouteIcon size={17}/>{loading ? 'Loading journey…' : 'Show status'}</button>
    </form>

    {!requested ? <div className="panel status-start">
      <span className="status-start-icon"><RouteIcon size={26}/></span>
      <h2>Your journey at a glance</h2><p>Choose your stations and select Show status to see the route, travel estimate and boarding updates.</p>
      <div className="status-start-features"><span><Clock3 size={16}/>Travel estimate</span><span><Radio size={16}/>Station delays</span><span><MapPin size={16}/>Route sections</span></div>
    </div> : loading ? <div className="panel status-start" role="status"><RefreshCw size={24}/><h2>Checking your journey</h2><p>Loading routes and station updates.</p></div> : !route ? <div className="panel status-start" role="status">
      <RouteIcon size={26}/><h2>{props.reason === 'no_valid_route' ? 'No route available' : 'Journey unavailable'}</h2>
      <p>{props.reason === 'no_valid_route' ? 'Choose another station pair or try again later.' : 'Reconnect to load this journey, or choose stations on the Aqua Line for a stored estimate.'}</p>
      <button className="outline" onClick={props.onRefresh}>Try again</button>
    </div> : <>
      {props.error && <p className="status-saved-note" role="status"><WifiOff size={15}/>Updates are unavailable. Showing the saved journey.</p>}
      <div className="panel status-route-summary">
        <div className="status-route-top"><div><span className="status-label">SELECTED JOURNEY</span><h2>{name(origin)} <ArrowRight size={19}/> {name(destination)}</h2></div>
          <button className="outline" onClick={props.onRefresh} aria-label="Refresh journey status"><RefreshCw size={15}/>Refresh</button>
        </div>
        <div className="status-route-choice">
          {routes.length > 1 ? <label>Route option<select aria-label="Journey route option" value={route.id} onChange={event => props.onSelect(event.target.value)}>{routes.map((item, index) => <option value={item.id} key={item.id}>{index === 0 ? 'Recommended route' : `Alternative ${index + 1}`} · {duration(item.duration_seconds)} · {item.transfers} {item.transfers === 1 ? 'interchange' : 'interchanges'}</option>)}</select></label> : <span className="pill">{selectedIndex === 0 ? 'Recommended route' : 'Selected route'}</span>}
          <span className="status-summary-source">{!connected ? 'Saved travel estimate' : route.source === 'schedule' ? 'Operator travel-time estimate' : 'Includes accepted live evidence'}</span>
        </div>
        <dl className="status-metrics">
          <div><dt><Clock3 size={15}/>Travel estimate</dt><dd>{duration(route.duration_seconds)}</dd></div>
          <div><dt><Radio size={15}/>Reported extra wait</dt><dd>{(route.delay_seconds ?? 0) > 0 ? `+${duration(route.delay_seconds!)}` : 'No active report'}</dd></div>
          <div><dt><GitMerge size={15}/>Interchanges</dt><dd>{route.transfers}</dd></div>
          <div><dt><Footprints size={15}/>Estimated walking</dt><dd>{route.walking_metres == null ? 'Unavailable' : `${route.walking_metres} m`}</dd></div>
        </dl>
      </div>

      <div className="status-columns">
        <section className="panel status-sections" aria-label="Planned journey sections"><h2>Journey sections</h2><p className="status-section-caption">Planned underground, surface and walking connections.</p>
          <ol>{groups.map((steps, index) => {
            const first = steps[0], last = steps.at(-1)!;
            const walking = first.kind !== 'ride';
            const line = network.lines.find(item => item.id === first.line_id);
            return <li key={`${first.from_station_id}-${index}`}>
              <span className={`status-section-icon ${walking ? 'is-walking' : ''}`} style={!walking ? { borderColor: line?.color, color: line?.color } : undefined}>{walking ? <Footprints size={18}/> : <TrainFront size={18}/>}</span>
              <div><span className="status-section-kind">{walking ? 'Walking connection' : `${contextLabel(first.context)} section`}</span><strong>{first.from_station_id === last.to_station_id ? `Change at ${name(first.from_station_id)}` : `${name(first.from_station_id)} to ${name(last.to_station_id)}`}</strong>
                <p>{walking ? `${duration(steps.reduce((sum, step) => sum + step.seconds, 0))}${first.requires_exit ? ' · Exit and re-enter' : ''}` : `${line?.name ?? 'Metro'} · ${steps.length} ${steps.length === 1 ? 'stop' : 'stops'} · ${duration(steps.reduce((sum, step) => sum + step.seconds, 0))}`}</p>
              </div>
            </li>;
          })}</ol>
        </section>
        <div className="panel status-boarding">
          {route.source_statuses?.length ? <JourneyLiveStatus route={route} stations={network.stations} now={now} cached={!connected}/> : <div className="status-no-sources"><Radio size={22}/><h2>Stored route timing</h2><p>This route uses saved operator travel times. Reconnect to check for station updates.</p></div>}
        </div>
      </div>
      <div className="status-page-footer"><p><Info size={15}/>{snapshotAge == null ? 'Stored journey' : connected ? `Snapshot refreshed ${snapshotAge}s ago` : `Saved snapshot · ${snapshotAge}s old`}. Ordinary boarding wait, station access and security are additional.</p><div><button className="outline" onClick={props.onReport}>Report a station update</button><button className="primary" onClick={props.onPlan}>View full route <ArrowRight size={16}/></button></div></div>
    </>}
  </section>;
}
