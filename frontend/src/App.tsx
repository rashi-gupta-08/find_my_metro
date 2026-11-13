import { Fragment, useEffect, useState } from 'react';
import { Activity, ArrowDownUp, ArrowRight, Bell, CheckCircle2, ChevronRight, Clock3, MapPin, MessageSquarePlus, Navigation, Radio, Route as RouteIcon, ShieldCheck, TrainFront, Wifi, WifiOff, X } from 'lucide-react';
import { api, ApiError, readStored, saveStored, sourceName } from './api';
import type { Account } from './api';
import { AccountDialog } from './AccountDialog';
import { SoftwareControls } from './SoftwareControls';
import { useArrivals } from './useArrivals';
import { useJourney } from './useJourney';
import { StationPicker } from './StationPicker';
import { JourneyResults, preferences } from './JourneyResults';
import { SurfaceReportDialog } from './SurfaceReportDialog';
import { useSurfaceReports } from './useSurfaceReports';
import { MyReports } from './MyReports';
import { DelayAlerts } from './DelayAlerts';
import { displayRoute } from './journeyFreshness';
import { NetworkMap } from './NetworkMap';
import { JourneyStatusPage } from './JourneyStatusPage';
import { useScrollMotion } from './useScrollMotion';
import type { Arrival, CommunitySignal, Network, Preference, Report, SourceStatus, Trip } from './types';

const minutes = (seconds: number) => seconds < 15 ? 'Now' : `${Math.ceil(seconds / 60)} min`;
const clock = (timestamp: string) => new Date(timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
const titleCase = (value: string) => value.replaceAll('_', ' ').replaceAll('-', ' ');

function Brand() {
  return <span className="brand"><span className="crest"><TrainFront size={20} /></span>FindMy<span className="teal">Metro</span></span>;
}

export default function App() {
  const motionRoot = useScrollMotion();
  const [network, setNetwork] = useState<Network | null>(() => readStored('metro-live-network', null));
  const [page, setPage] = useState('home');
  const [scope,setScope]=useState('all');
  const [error, setError] = useState('');
  const [origin, setOrigin] = useState(() => readStored<{origin: string}>('metro-last-journey',{origin:''}).origin);
  const [destination, setDestination] = useState(() => readStored<{destination: string}>('metro-last-journey',{destination:''}).destination);
  const [station, setStation] = useState('');
  const [searchedJourney, setSearchedJourney] = useState<{origin: string; destination: string} | null>(null);
  const [preference, setPreference] = useState<Preference>('fastest');
  const [selectedRoute, setSelectedRoute] = useState('__initial__');
  const [community, setCommunity] = useState<CommunitySignal[]>([]);
  const [communityAvailable,setCommunityAvailable] = useState(false);
  const [locationMessage, setLocationMessage] = useState('');
  const [trips, setTrips] = useState<Trip[]>([]);
  const [selectedTrip, setSelectedTrip] = useState('');
  const [source, setSource] = useState<SourceStatus | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [reportTrip, setReportTrip] = useState('');
  const [reportNote, setReportNote] = useState('');
  const [reportMessage, setReportMessage] = useState('');
  const [queue, setQueue] = useState<Report[]>([]);
  const [user, setUser] = useState<Account | null>(null);
  const [showAccount, setShowAccount] = useState(false);
  const [accountRecovery, setAccountRecovery] = useState<{token:string;username:string}|null>(null);
  useEffect(()=>{
    function readRecoveryLink() {
      const fragment = new URLSearchParams(window.location.hash.slice(1));
      const token = fragment.get('reset-password');
      if(token) {
        setAccountRecovery({token,username:fragment.get('username')??''});setShowAccount(true);
        // Remove the secret from the address and keep it out of persistent storage.
        window.history.replaceState(null,'',window.location.pathname+window.location.search);
      }
    }
    readRecoveryLink();window.addEventListener('hashchange',readRecoveryLink);
    return()=>window.removeEventListener('hashchange',readRecoveryLink);
  },[]);
  const [reportSending, setReportSending] = useState(false);
  const [health, setHealth] = useState('connecting');
  const [now, setNow] = useState(Date.now());
  const surfaceReports=useSurfaceReports(user);
  const { snapshot, connection } = useArrivals(station);
  const journeyRequested = searchedJourney?.origin===origin && searchedJourney?.destination===destination;
  const journey = useJourney(origin,destination,preference,network,(page==='plan' || page==='tracking') && journeyRequested);
  const matchingSnapshot = journey.snapshot?.origin===origin && journey.snapshot?.destination===destination && journey.snapshot?.preference===preference;
  const routeOptions = (matchingSnapshot ? journey.snapshot?.routes ?? [] : []).map(route=>displayRoute(route,now,journey.connection==='live'));
  const routeReason = journey.snapshot?.reason ?? '';
  const routeLoading = Boolean(journeyRequested && !matchingSnapshot && journey.connection==='connecting');
  const routeUpdatedAt = journey.snapshot?.generated_at ?? '';
  const stations = network?.stations ?? [];
  const lines = network?.lines ?? [];
  const stationName = (id: string) => stations.find((s) => s.id === id)?.name ?? id;
  const lineName = (id: string) => lines.find((line) => line.id === id)?.name ?? id;

  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }); }, [page]);

  useEffect(() => {
    let alive = true;
    async function refresh() {
      const results = await Promise.allSettled([api.network(), api.health(), api.trips(), api.serviceStatus()]);
      if (!alive) return;
      if (results[0].status === 'fulfilled') { setNetwork(results[0].value); saveStored('metro-live-network', results[0].value); setError(''); }
      else setError('The local backend is unavailable. Start it, then this page will reconnect.');
      if (results[1].status === 'fulfilled') setHealth(results[1].value.ready ? 'ready' : 'worker unavailable');
      else setHealth('unavailable');
      if (results[2].status === 'fulfilled') {
        setTrips(results[2].value.trips);
        setReportTrip((current) => results[2].status === 'fulfilled' && results[2].value.trips.some((trip) => trip.id === current) ? current : results[2].status === 'fulfilled' ? results[2].value.trips[0]?.id ?? '' : '');
      }
      if (results[3].status === 'fulfilled') { setCommunity(results[3].value.signals); setCommunityAvailable(true); }
      else setCommunityAvailable(false);
    }
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedTrip) { setSource(null); return; }
    let alive = true;
    const refresh = () => api.status(selectedTrip).then((next) => { if (alive) setSource(next); }).catch(() => {});
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [selectedTrip]);

  useEffect(() => {
    let alive=true;
    const refresh=()=>{if(navigator.onLine)void api.me().then(result=>{if(alive)setUser(result.user);}).catch(()=>{});};
    const expired=()=>{setUser(null);setShowReport(false);};
    refresh();
    const timer=setInterval(refresh,60000);
    window.addEventListener('online',refresh);
    window.addEventListener('focus',refresh);
    window.addEventListener('metro-session-expired',expired);
    return()=>{alive=false;clearInterval(timer);window.removeEventListener('online',refresh);window.removeEventListener('focus',refresh);window.removeEventListener('metro-session-expired',expired);};
  }, []);
  useEffect(() => {
    setQueue(user ? readStored<Report[]>(`metro-private-reports:${user.id}`, []).filter((r) => Date.now()-new Date(r.observed_at).getTime() < 86400000) : []);
  }, [user?.id]);
  useEffect(() => { if (user) saveStored(`metro-private-reports:${user.id}`, queue); }, [queue, user]);
  useEffect(() => {
    const prune = setInterval(() => setQueue((current) => {
      const recent = current.filter((report) => Date.now()-new Date(report.observed_at).getTime() < 86400000);
      return recent.length === current.length ? current : recent;
    }), 60000);
    return () => clearInterval(prune);
  }, []);
  useEffect(() => {
    if (!stations.some((s) => s.id === station)) setStation((network?.simulated ? stations.at(-1) : stations[0])?.id ?? '');
    if (!stations.some((s) => s.id === origin)) setOrigin((stations.find(s => s.id === 'dmrc-ndi') ?? (network?.simulated ? stations[1] : stations[0]))?.id ?? '');
    if (!stations.some((s) => s.id === destination)) setDestination((stations.find(s => s.id === 'nmrc-17') ?? stations.at(-1))?.id ?? '');
  }, [network]);
  useEffect(() => { setSearchedJourney(null); setSelectedRoute('__initial__'); },[origin,destination]);
  useEffect(() => {
    if (routeOptions.length && selectedRoute && !routeOptions.some(route => route.id===selectedRoute)) setSelectedRoute(routeOptions[0].id);
  },[journey.snapshot]);
  useEffect(() => {
    if (!showReport) return;
    const listener = (event: KeyboardEvent) => { if (event.key === 'Escape') setShowReport(false); };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  }, [showReport]);

  function loadJourney(target: 'plan' | 'tracking') {
    if (!origin || !destination || origin === destination) { setError('Choose two different stations.'); return; }
    setError(''); setPage(target); setSearchedJourney({origin,destination}); saveStored('metro-last-journey',{origin,destination}); journey.refresh();
  }
  function findRoute() { loadJourney('plan'); }

  async function sendReport(event: React.FormEvent) {
    event.preventDefault(); setReportMessage('');
    const trip = trips.find((t) => t.id === reportTrip);
    if (!trip || !user) { setShowAccount(true); return; }
    setReportSending(true);
    let report: Report | undefined;
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) => {
        if (!navigator.geolocation) reject(new Error('Location is unavailable on this device.'));
        else navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
      });
      if (position.coords.accuracy > 100) throw new Error('Your location is too imprecise. Try again near the station.');
      report = { event_id: crypto.randomUUID(), trip_id: trip.id, contributor_id: user.id,
        direction: trip.direction, observed_at: new Date(position.timestamp).toISOString(),
        latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy_m: position.coords.accuracy,
        kind: 'sighting', note: reportNote };
      const result = await api.submit([report]);
      const ack = result.acknowledgements[0];
      setReportMessage(ack.status === 'queued' ? 'Your sighting has been received and is being checked.' : `${ack.status}: ${ack.reason ?? ''}`);
      setReportNote('');
    } catch (problem) {
      if (report && (!(problem instanceof ApiError) || [429, 503].includes(problem.status))) {
        setQueue((current) => [...current.slice(-99), report!]);
        setReportMessage('Saved on this device for up to 24 hours. Retry when the service is available.');
      } else setReportMessage((problem as Error).message || 'Location permission is needed to verify a sighting.');
    } finally { setReportSending(false); }
  }

  async function flushQueue() {
    if (!queue.length || reportSending) return;
    setReportSending(true);
    try {
      const result = await api.submit(queue);
      const stored = new Set(result.acknowledgements.filter((ack) => ['queued', 'duplicate', 'rejected', 'conflict'].includes(ack.status)).map((ack) => ack.client_event_id ?? ack.event_id));
      setQueue((current) => current.filter((item) => !stored.has(item.event_id)));
      setReportMessage(`${stored.size} report(s) acknowledged. Late reports remain historical.`);
    } catch { setReportMessage('Backend unavailable. Reports are still saved on this device.'); }
    finally { setReportSending(false); }
  }

  const snapshotAge = snapshot ? Math.max(0, Math.floor((now - new Date(snapshot.generated_at).getTime()) / 1000)) : null;
  const arrivals = snapshot?.arrivals ?? [];
  const primary = trips.find((trip) => lines.some((line) => line.id === trip.line_id));
  useEffect(() => {
    if (primary && !trips.some((trip) => trip.id === selectedTrip && lines.some((line) => line.id === trip.line_id))) setSelectedTrip(primary.id);
  }, [trips, network]);
  const elapsed = source?.transition ? Math.max(0, 60 - Math.ceil((new Date(source.transition.deadline).getTime() - now) / 1000)) : 0;

  function ArrivalCard({ arrival }: { arrival: Arrival }) {
    const line = lines.find((item) => item.id === arrival.line_id);
    const remaining = Math.max(0, Math.ceil((new Date(arrival.arrival_at).getTime() - now) / 1000));
    const stale = connection === 'cached' || snapshotAge !== null && snapshotAge > 10;
    return <button className="arrival-card" onClick={() => { setSelectedTrip(arrival.trip_id); setPage('tracking'); }} style={{ '--line-color': line?.color } as React.CSSProperties}>
      <div className="arrival-top"><strong>Towards {stationName(arrival.towards)}</strong><b className="eta">{stale ? 'Cached' : minutes(remaining)}</b></div>
      <p className="small muted">{line?.name} · Platform {arrival.platform} · {clock(arrival.arrival_at)}</p>
      <div className="card-tags"><span><TrainFront size={14} /> {arrival.train_code}</span><span className="pill"><Radio size={13} /> {sourceName[arrival.source]}</span></div>
      <div className="trust-row"><span className="trust-track"><i style={{ width: `${arrival.trust_score * 100}%` }} /></span><span>{arrival.source === 'schedule' ? 'Schedule fallback' : `${Math.round(arrival.trust_score * 100)}% trust score`}</span><ChevronRight size={17} /></div>
      {arrival.delay_seconds >= 60 && arrival.source !== 'schedule' && <p className="delay">Estimated delay: {minutes(arrival.delay_seconds)}</p>}
    </button>;
  }

  function Planner() {
    return <div className="planner">
      <StationPicker label="From" value={origin} onChange={setOrigin} stations={scope==='aqua' ? stations.filter(s=>s.id.startsWith('nmrc-')) : stations} lines={lines}/>
      <button className="swap" aria-label="Swap start and destination" onClick={() => { setOrigin(destination); setDestination(origin); }}><ArrowDownUp size={18} /></button>
      <StationPicker label="To" value={destination} onChange={setDestination} stations={scope==='aqua' ? stations.filter(s=>s.id.startsWith('nmrc-')) : stations} lines={lines}/>
      <button className="primary find-route" disabled={!network?.configured || routeLoading || origin === destination} onClick={findRoute}><Navigation size={17} />{routeLoading ? 'Finding routes…' : 'Find my route'}</button>
    </div>;
  }

  async function nearestStation() {
    setLocationMessage('Finding your nearest station…');
    try {
      const location=await new Promise<GeolocationPosition>((resolve,reject) => navigator.geolocation ? navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,maximumAge:30000,timeout:15000}) : reject(new Error('Location is unavailable.')));
      const distance=(s: typeof stations[number]) => Math.hypot((s.lat-location.coords.latitude)*111195,(s.lng-location.coords.longitude)*111195*Math.cos(location.coords.latitude*Math.PI/180));
      const nearest=[...stations].sort((a,b) => distance(a)-distance(b))[0];
      if (nearest) { setOrigin(nearest.id); setLocationMessage(`${nearest.name} · ${(distance(nearest)/1000).toFixed(1)} km away in a straight line`); }
    } catch { setLocationMessage('Location unavailable. Search for your station instead.'); }
  }

  const sortedRoutes=[...routeOptions].sort((a,b) => preference==='fewest_changes' ? a.transfers-b.transfers || a.duration_seconds-b.duration_seconds : preference==='least_walking' ? (a.walking_metres ?? 0)-(b.walking_metres ?? 0) || a.duration_seconds-b.duration_seconds : preference==='shortest_distance' ? (a.distance_metres ?? 0)-(b.distance_metres ?? 0) || a.duration_seconds-b.duration_seconds : a.duration_seconds-b.duration_seconds);
  const displayedCommunity=community.filter(signal=>now<Date.parse(signal.expires_at ?? new Date(Date.parse(signal.last_observed_at)+30000).toISOString()));

  return <>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="header"><div className="header-inner"><button className="brand-button" onClick={() => setPage('home')}><Brand /></button>
      <nav aria-label="Main navigation">{[['home', 'Home'], ['plan', 'Plan'], ['map', 'Map'], ['alerts', 'Alerts'], ['tracking', network?.simulated ? 'Tracking' : 'Journey status']].map(([id, label]) => <button key={id} className={page === id ? 'nav-active' : ''} onClick={() => { setPage(id); if (id === 'tracking' && !selectedTrip && primary) setSelectedTrip(primary.id); }}>{label}</button>)}</nav>
      <button className="report-button" onClick={() => { if (!user) setShowAccount(true); else setShowReport(true); setReportMessage(''); }}><MessageSquarePlus size={16} />Report{queue.length > 0 && ` (${queue.length})`}</button>
      <button className="outline account-button" onClick={() => setShowAccount(true)}>{user ? user.display_name : 'Sign in'}</button>
      <span className={`header-status ${health === 'ready' ? 'is-connected' : ''}`} role="status" aria-label={health === 'ready' ? 'Service connected' : 'Service unavailable'} title={health === 'ready' ? 'Service connected' : 'Service unavailable'}><Activity size={14}/></span>
    </div></header>
    <main id="main" className="container" ref={motionRoot}>
      {error && <div className="error-banner" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
      {network?.simulated && new URLSearchParams(location.search).has('developer') && <SoftwareControls onReplay={() => { setSelectedTrip(''); setSource(null); setPage('tracking'); }} />}
      {network?.simulated && <p className="software-notice">Software validation · No real Delhi or Noida train positions are displayed.</p>}

      {(page === 'home' || page === 'plan') && <section className="hero"><p className="eyebrow">DELHI & NOIDA, ONE JOURNEY</p><h1>Your station. Your best route.</h1><p>Compare journey time, interchanges and walking across the metro network.</p>{stations.length ? <>{Planner()}<label className="network-scope">NETWORK<select aria-label="Network scope" value={scope} onChange={e=>{const next=e.target.value;setScope(next);if(next==='aqua'){const aqua=stations.filter(s=>s.id.startsWith('nmrc-'));setOrigin(aqua[0]?.id ?? '');setDestination(aqua.at(-1)?.id ?? '');setSearchedJourney(null);}}}><option value="all">Delhi + Noida catalogue</option><option value="aqua">Aqua Line · Phase 1 · 21 stations</option></select></label><div className="preference-controls" role="group" aria-label="Route preference">{preferences.map(([id,label]) => <button className={preference === id ? 'preference-active' : ''} aria-pressed={preference === id} key={id} onClick={() => setPreference(id)}>{label}</button>)}</div><div className="location-action"><button onClick={nearestStation}><MapPin size={14}/>Use my location for the nearest station</button>{locationMessage && <span role="status">{locationMessage}</span>}</div></> : <div className="data-unavailable"><Radio size={22}/><p>Connecting to the station catalogue…</p></div>}<div className="hero-footer"><ShieldCheck size={14}/>{network?.journey_planning ? 'Operator travel-time estimates · Community/GPS delays when confirmed' : `${stations.length} stations · ${lines.length} line paths`}</div></section>}

      {page === 'plan' && <section className="section"><div className="section-heading"><div><h2>Journey options</h2><p>{stationName(origin)} <ArrowRight size={12} /> {stationName(destination)}</p></div><button className="text-button" onClick={findRoute}>Refresh routes</button></div>
        {journey.error && <p className="error-banner" role="alert">{journey.snapshot ? 'Updates are unavailable. Showing the last saved journey.' : journey.error}</p>}
        {!routeOptions.length && <div className="empty">{routeLoading ? 'Checking departure times and transfers…' : routeReason === 'no_valid_route' ? 'No valid route is available for these stations.' : 'Choose your stations, then find a route.'}</div>}
        {journey.connection==='live' && journey.snapshot?.rerouting?.valid_until && now<Date.parse(journey.snapshot.rerouting.valid_until) && ['alternative_suggested','no_faster_alternative','saving_below_threshold'].includes(journey.snapshot.rerouting.status) && <p className="delay-alert" role="status">{journey.snapshot.rerouting.status==='alternative_suggested' ? `A validated delay exceeds 3 minutes. The faster route saves ${Math.floor(journey.snapshot.rerouting.saving_seconds/60)} minutes.` : journey.snapshot.rerouting.status==='no_faster_alternative' ? 'A delay is confirmed. No faster metro alternative is available in the configured network; keep this route and allow extra time.' : 'A delay is confirmed. Alternative savings are below the 2-minute switch threshold.'}</p>}
        <JourneyResults routes={sortedRoutes} stations={stations} lines={lines} selected={selectedRoute} onSelect={setSelectedRoute} now={now} cached={journey.connection!=='live'} onStatus={id=>{setSelectedRoute(id);setPage('tracking');}}/>
        {network && routeOptions.length>0 && <DelayAlerts route={routeOptions.find(route=>route.id===selectedRoute) ?? sortedRoutes[0]} network={network} now={now} connected={journey.connection==='live'}/>}
        {routeOptions.length>0 && <div className="route-method"><p>{journey.snapshot?.timing_note ?? 'Journey times include metro travel and estimated interchange walking. Boarding waits, station access and security are additional.'} Walking distances are approximate.</p><p>{routeUpdatedAt && `Updated ${Math.max(0,Math.floor((now-Date.parse(routeUpdatedAt))/1000))}s ago · `}{journey.connection==='live' ? 'Journey updates connected' : 'Saved journey · Live status may have changed'}. Source changes and accepted delays refresh automatically.</p></div>}
      </section>}

      {network?.configured && (page === 'home' || page === 'alerts') && <section className="section"><div className="section-heading"><div><h2>Community service updates</h2><p>Location-checked station reports · Live evidence lasts 30 seconds.</p></div><button className="text-button" onClick={() => user ? setShowReport(true) : setShowAccount(true)}>Share a delay</button></div>
        {displayedCommunity.length ? <div className="cards-grid">{displayedCommunity.map((signal,index) => <article className="panel community-card" key={index}><Radio size={20}/><div><strong>{stationName(signal.station_id)}</strong><p>{lineName(signal.line_id)} · {signal.status === 'confirmed' ? signal.event_type && signal.event_type!=='delayed' ? `Community reports: ${signal.event_type}` : `${Math.ceil((signal.delay_seconds ?? 0)/60)} min community-reported extra wait` : `Awaiting agreement · ${signal.confirmations}/${signal.required_confirmations} accounts`}</p><small>{!communityAvailable ? 'Saved service update' : signal.status === 'confirmed' ? 'Community signal' : 'Unconfirmed report'} · {Math.max(0,Math.floor((now-Date.parse(signal.last_observed_at))/1000))}s old</small></div></article>)}</div> : <div className="panel no-alerts"><Radio size={20}/><div><strong>Live delay evidence is not available yet</strong><p>Route planning uses operator travel-time estimates. Delays appear after three nearby accounts agree. Underground sections use static travel times when accurate phone evidence is unavailable.</p></div></div>}
      </section>}

      {network?.journey_planning && user && (page==='home' || page==='alerts') && <MyReports key={user.id} network={network} controller={surfaceReports} now={now}/>}
      {network?.configured && page === 'alerts' && <section className="section"><div className="section-heading"><div><h2>Next trains at {stationName(station)}</h2><p>{connection === 'cached' ? `Cached snapshot · ${snapshotAge}s old` : 'Updates from the local backend every two seconds.'}</p></div><div className="station-controls"><span className={`pill ${connection === 'live' ? 'live' : ''}`}>{connection === 'live' ? <Wifi size={13} /> : <WifiOff size={13} />}{connection === 'live' ? 'Connected' : connection}</span><select aria-label="Arrivals station" value={station} onChange={(e) => setStation(e.target.value)}>{stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div></div>
        {arrivals.length ? <div className="cards-grid">{arrivals.slice(0, 6).map((arrival) => <Fragment key={arrival.id}>{ArrivalCard({arrival})}</Fragment>)}</div> : <div className="empty">{network ? 'No verified upcoming service is available at this station.' : 'Connecting to the local backend…'}</div>}
      </section>}

      {page==='map' && network?.configured && <NetworkMap network={network} selected={station} onSelect={setStation}
        onFrom={id=>{setOrigin(id);setScope('all');setSearchedJourney(null);setPage('plan');}}
        onTo={id=>{setDestination(id);setScope('all');setSearchedJourney(null);setPage('plan');}}
        arrivals={arrivals} signals={displayedCommunity} connection={connection} now={now}/>}

      {network?.configured && page==='home' && <section className="section"><div className="section-heading"><div><h2>Explore your metro network</h2><p>Find your station and discover connections across Delhi and Noida.</p></div><button className="text-button" onClick={()=>setPage('map')}>Network map</button></div>
        <div className="station-grid">{stations.slice(0,4).map(s=><button className="panel station-card" key={s.id} onClick={()=>{setStation(s.id);setPage('map');}}><MapPin size={15}/><strong>{s.name}</strong><span>{s.area}</span><span className="small">{s.zone}</span><div className="line-dots">{s.line_ids.map(id=><i key={id} style={{background:lines.find(line=>line.id===id)?.color}}/>)}</div></button>)}</div>
      </section>}

      {page === 'tracking' && network?.configured && !network.simulated && <JourneyStatusPage network={network} origin={origin} destination={destination} onOrigin={setOrigin} onDestination={setDestination} requested={journeyRequested} loading={routeLoading} routes={sortedRoutes} selected={selectedRoute} onSelect={setSelectedRoute} onLoad={()=>loadJourney('tracking')} onRefresh={journey.refresh} onPlan={()=>setPage('plan')} onReport={()=>user ? setShowReport(true) : setShowAccount(true)} connection={journey.connection} generatedAt={routeUpdatedAt} error={journey.error} reason={routeReason} now={now}/>}

      {page === 'tracking' && network?.simulated && <section className="section"><div className="section-heading"><div><h1>Source tracking</h1><p>Context, trust and decisions for a single journey.</p></div><select aria-label="Tracked trip" value={selectedTrip} onChange={(e) => setSelectedTrip(e.target.value)}><option value="">Choose a train</option>{trips.map((trip) => <option value={trip.id} key={trip.id}>{trip.code} · {trip.direction}</option>)}</select></div>
        {source ? <><div className="mode-grid">{['underground', 'transition', 'surface'].map((mode) => <div className={`panel mode-card ${source.context === mode ? 'mode-selected' : ''}`} key={mode}><Radio size={22} /><strong>{mode}</strong><span>{mode === 'underground' ? 'Static + phone evidence' : mode === 'surface' ? 'Validated crowd preferred' : 'Bounded source arbitration'}</span></div>)}</div><div className="panel tracking-detail"><div className="detail-grid"><div><span>Accepted source</span><strong>{sourceName[source.source]}</strong></div><div><span>Heuristic trust</span><strong>{Math.round(source.trust * 100)}%</strong></div><div><span>Position along route</span><strong>{Math.round(source.position_m)} m</strong></div><div><span>Last observation</span><strong>{source.last_observed_at ? clock(source.last_observed_at) : 'Awaiting evidence'}</strong></div></div><p className="reason"><ShieldCheck size={16} />{titleCase(source.reason)}</p>{source.transition && <div className="transition-bar"><label>60-second arbitration · {Math.min(60, elapsed)}s elapsed</label><progress value={Math.min(60, elapsed)} max={60} /></div>}<div className="score-grid">{Object.entries(source.scores).map(([name, score]) => <div key={name}><span>{name.toUpperCase()}</span><progress value={score} max={1} /><b>{Math.round(score * 100)}%</b></div>)}</div></div>{source.arbitration && <div className="panel arbitration-comparison"><h3>Transition arbitration</h3><p>Estimated position trust: <strong>{Math.round(source.arbitration.estimated_trust * 100)}%</strong></p>{Object.entries(source.arbitration.incoming_trust).map(([name, value]) => <p key={name}>{sourceName[name] ?? name}: <strong>{Math.round(value * 100)}%</strong></p>)}<p>{titleCase(source.arbitration.reason)}</p></div>}<h2 className="decision-title">Decision history</h2><div className="panel decision-log">{source.decisions.map((decision, i) => <div key={i}><time>{clock(decision.at)}</time><strong>{sourceName[decision.source]}</strong><span>{titleCase(decision.reason)}</span></div>)}</div><p className="small muted">Trust scores are heuristic indicators, not calibrated probabilities. Estimates keep their original observation age.</p></> : <div className="tracking-start"><button className="primary" onClick={() => setPage('plan')}>Plan a journey <ArrowRight size={16}/></button></div>}
      </section>}

      {page === 'map' && network?.journey_planning && <details className="explorer-data"><summary>About this network and its data sources</summary><p>{network.coverage_note}</p><p>Catalogue retrieved {network.published_at ? new Date(network.published_at).toLocaleDateString('en-IN') : 'recently'}. Platform walking distances are estimates.</p><div>{network.sources?.map((source,i) => <a key={i} href={source.url} target="_blank" rel="noreferrer">{source.scope}</a>)}</div></details>}
      {!network?.configured && <section className="section"><div className="section-heading"><div><h2>Metro connections</h2><p>Operator data has not been connected yet. Official passenger information is available below.</p></div></div><div className="cards-grid">{network?.operators.map((item) => <article className="panel operator-card" key={item.id}><TrainFront size={24} /><h3>{item.name}</h3><span className="pill">Arrival data unavailable</span><p>Check stations and plan your journey with the operator.</p><a className="text-button" href={item.map_url} target="_blank" rel="noreferrer">Official journey information <ArrowRight size={14} /></a></article>)}</div></section>}
      <footer><Brand /><button className="text-button" onClick={() => setShowAccount(true)}>My account</button></footer>
    </main>

    {showAccount && <AccountDialog user={user} recovery={accountRecovery} onClose={() => {setShowAccount(false);setAccountRecovery(null);}} onAuthenticated={setUser} onSignedOut={() => { if (user) { localStorage.removeItem(`metro-private-reports:${user.id}`); localStorage.removeItem(`metro-surface-queue:${user.id}`); } setQueue([]); setUser(null); setShowReport(false); }} />}
    {showReport && network?.journey_planning && user && <SurfaceReportDialog network={network} controller={surfaceReports} initialStation={origin} onClose={() => setShowReport(false)}/> }
    {showReport && !network?.journey_planning && <div className="modal-backdrop" onClick={() => setShowReport(false)}><section className="modal panel" role="dialog" aria-modal="true" aria-labelledby="report-title" onClick={(e) => e.stopPropagation()}><button className="modal-close" aria-label="Close report" onClick={() => setShowReport(false)}><X size={21} /></button><MessageSquarePlus size={28} className="teal" /><h2 id="report-title">Share a train sighting</h2><p>Your location is used once, with your permission, to check this sighting. It is never tracked in the background.</p><form onSubmit={sendReport}><label>TRAIN<select value={reportTrip} onChange={(e) => setReportTrip(e.target.value)} aria-label="Report train">{trips.map((trip) => <option value={trip.id} key={trip.id}>{trip.code} · {trip.direction} · {lineName(trip.line_id)}</option>)}</select></label><label>NOTE<textarea value={reportNote} onChange={(e) => setReportNote(e.target.value)} maxLength={500} placeholder="Optional observation" /></label><button className="primary" type="submit" disabled={!reportTrip || !user || reportSending}>{reportSending ? 'Saving…' : 'Send sighting'}</button></form>{reportMessage && <p className="report-result" role="status">{reportMessage}</p>}{queue.length > 0 && <div className="queue-notice"><span>{queue.length} report(s) saved on this device</span><button className="outline" onClick={flushQueue} disabled={reportSending}>Retry upload</button></div>}<p className="small muted">Sightings need independent agreement before they influence an arrival estimate. Queued reports keep their original time and are removed when you sign out.</p></section></div>}
  </>;
}



