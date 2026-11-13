import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { ArrowDownLeft, ArrowUpRight, Check, Clock3, Expand, GitMerge, MapPin, Minus, MousePointer2, Plus, Radio, RotateCcw, TrainFront, Wifi, WifiOff } from 'lucide-react';
import { StationPicker } from './StationPicker';
import type { Arrival, CommunitySignal, Line, Network, Station } from './types';
import './network-map.css';

type View = { x: number; y: number; width: number; height: number };
type Props = {
  network: Network;
  selected: string;
  onSelect: (id: string) => void;
  onFrom: (id: string) => void;
  onTo: (id: string) => void;
  arrivals: Arrival[];
  signals: CommunitySignal[];
  connection: string;
  now: number;
};
const family = (line: Line) => line.family_id ?? line.id;
const nameOf = (line: Line | undefined) => line?.name.split(' · ')[0] ?? 'Metro line';
const zoneName: Record<string, string> = { underground: 'Underground', surface: 'Surface', transition: 'Transition zone' };

function fit(stations: Station[], aspect: number): View {
  if (!stations.length) return { x: 0, y: 0, width: 850, height: 500 };
  const xs = stations.map(s => s.x), ys = stations.map(s => s.y);
  const left = Math.min(...xs)-36, top = Math.min(...ys)-36;
  let width = Math.max(90, Math.max(...xs)-left+36);
  let height = Math.max(90, Math.max(...ys)-top+36);
  if (width/height < aspect) width = height*aspect;
  else height = width/aspect;
  return { x: (Math.min(...xs)+Math.max(...xs)-width)/2, y: (Math.min(...ys)+Math.max(...ys)-height)/2, width, height };
}

export function NetworkMap({ network, selected, onSelect, onFrom, onTo, arrivals, signals, connection, now }: Props) {
  const [operator, setOperator] = useState('all');
  const [lineFilter, setLineFilter] = useState('all');
  const [showNames, setShowNames] = useState(false);
  const [hovered, setHovered] = useState('');
  const [size, setSize] = useState({ width: 800, height: 560 });
  const [view, setView] = useState<View | null>(null);
  const [dragging, setDragging] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: number; x: number; y: number; view: View; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const stationMap = useMemo(() => new Map(network.stations.map(s => [s.id, s])), [network.version]);
  const operatorLines = useMemo(() => network.lines.filter(l => operator === 'all' || l.operator_id === operator), [network.version, operator]);
  const families = [...new Map(operatorLines.map(l => [family(l), l])).values()];
  const activeLines = operatorLines.filter(l => lineFilter === 'all' || family(l) === lineFilter);
  const activeIds = new Set(activeLines.flatMap(l => l.station_ids));
  const activeStations = network.stations.filter(s => activeIds.has(s.id));
  const base = useMemo(() => fit(network.stations.filter(s => {
    return network.lines.some(l => (operator === 'all' || l.operator_id === operator) && (lineFilter === 'all' || family(l) === lineFilter) && l.station_ids.includes(s.id));
  }), size.width/size.height), [network.version, operator, lineFilter, size.width, size.height]);
  const current = view ?? base;
  const scale = Math.min(size.width/current.width, size.height/current.height);
  const zoom = base.width/current.width;
  const station = stationMap.get(selected);
  const serving = station ? [...new Map(network.lines.filter(l => l.station_ids.includes(station.id)).map(l => [family(l), l])).values()] : [];
  const termini = new Set(activeLines.flatMap(l => [l.station_ids[0], l.station_ids.at(-1)!]));
  const interchanges = new Set(network.stations.filter(s => new Set(network.lines.filter(l => l.station_ids.includes(s.id)).map(family)).size > 1).map(s => s.id));
  const selectedVisible = activeIds.has(selected);
  const updates = signals.filter(s => s.station_id === selected && s.status === 'confirmed' && s.expires_at && now < Date.parse(s.expires_at));
  const stationArrivals = arrivals.filter(a => a.station_id === selected).slice(0, 3);
  const primaryLine = network.lines.find(l => l.station_ids.includes(selected) && (lineFilter === 'all' || family(l) === lineFilter)) ?? serving[0];
  const index = primaryLine?.station_ids.indexOf(selected) ?? -1;
  const neighbours = primaryLine && index >= 0 ? [primaryLine.station_ids[index-1], primaryLine.station_ids[index+1]].filter(Boolean).map(id => stationMap.get(id)!).filter(Boolean) : [];

  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width && height) setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { setView(null); setHovered(''); }, [base.x, base.y, base.width, base.height]);

  function zoomAt(factor: number, point?: { x: number; y: number }) {
    setView(previous => {
      const before = previous ?? base;
      const nextZoom = Math.max(1, Math.min(7, base.width/before.width*factor));
      const width = base.width/nextZoom, height = base.height/nextZoom;
      const px = point?.x ?? before.x+before.width/2;
      const py = point?.y ?? before.y+before.height/2;
      return { x: px-(px-before.x)*width/before.width, y: py-(py-before.y)*height/before.height, width, height };
    });
  }
  function focusStation(id: string) {
    const point = stationMap.get(id);
    if (!point) return;
    onSelect(id);
    let bounds = base;
    if (!activeIds.has(id)) {
      setOperator('all'); setLineFilter('all');
      // Fit after clearing a filter; centring runs in the following animation frame.
      bounds = fit(network.stations, size.width/size.height);
    }
    const width = bounds.width/2.4, height = bounds.height/2.4;
    requestAnimationFrame(() => setView({ x: point.x-width/2, y: point.y-height/2, width, height }));
  }
  function pointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0 || !event.isPrimary) return;
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, view: current, moved: false };
    suppressClick.current = false;
    // Capture only after movement, so tapping a station keeps its normal click.
  }
  function pointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const start = drag.current;
    if (!start || start.id !== event.pointerId) return;
    const dx = event.clientX-start.x, dy = event.clientY-start.y;
    if (!start.moved && Math.hypot(dx,dy) < 5) return;
    start.moved = true; suppressClick.current = true;
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true); setHovered('');
    setView({ ...start.view, x: start.view.x-dx/scale, y: start.view.y-dy/scale });
  }
  function pointerUp() { drag.current = null; setDragging(false); }

  // Reserve space for each label. This keeps central interchanges readable at
  // every zoom level without covering the network in overlapping station names.
  const labels: { station: Station; anchor: 'start' | 'end'; x: number; y: number; width: number }[] = [];
  const boxes: { left: number; right: number; top: number; bottom: number }[] = [];
  const labelCandidates = [...activeStations].sort((a,b) => {
    const rank = (s: Station) => s.id === selected ? 0 : s.id === hovered ? 1 : interchanges.has(s.id) ? 2 : termini.has(s.id) ? 3 : 4;
    return rank(a)-rank(b) || a.name.localeCompare(b.name);
  });
  for (const point of labelCandidates) {
    const priority = point.id === selected || point.id === hovered;
    if (!priority && !showNames && activeStations.length > 65 && lineFilter === 'all' && zoom < 1.65 && !termini.has(point.id) && !interchanges.has(point.id)) continue;
    const px = (point.x-current.x)*scale, py = (point.y-current.y)*scale;
    if (px < 0 || px > size.width || py < 0 || py > size.height) continue;
    const anchor = px > size.width*.76 ? 'end' : 'start';
    const width = Math.min(230, point.name.length*6.2+12);
    const x = px+(anchor === 'start' ? 9 : -9), y = py < 32 ? py+21 : py-10;
    const box = { left: anchor === 'start' ? x-3 : x-width, right: anchor === 'start' ? x+width : x+3, top: y-13, bottom: y+5 };
    if (!priority && boxes.some(b => box.left < b.right+8 && box.right > b.left-8 && box.top < b.bottom+6 && box.bottom > b.top-6)) continue;
    labels.push({station:point, anchor, x:point.x+(anchor === 'start' ? 9 : -9)/scale, y:point.y+(py < 32 ? 21 : -10)/scale, width});
    boxes.push(box);
  }

  return <section className="network-explorer" aria-label="Interactive metro network">
    <h1 className="sr-only">Metro map</h1>
    <div className="explorer-shell">
      <div className="explorer-toolbar"><div className="explorer-operators" role="group" aria-label="Map network filter">{[['all','Entire network'],['dmrc','Delhi Metro'],['nmrc','Noida Metro']].map(([id,label]) => <button key={id} aria-pressed={operator===id} className={operator===id ? 'is-active' : ''} onClick={() => {setOperator(id);setLineFilter('all');setView(null);}}>{operator===id && <Check size={13}/>} {label}</button>)}</div><label className="explorer-label-toggle"><input type="checkbox" checked={showNames} onChange={e=>setShowNames(e.target.checked)}/>Station names</label></div>
      <div className="explorer-lines" role="group" aria-label="Map line filter"><button aria-pressed={lineFilter==='all'} className={lineFilter==='all' ? 'is-active' : ''} onClick={()=>{setLineFilter('all');setView(null);}}>All lines</button>{families.map(line => <button key={family(line)} aria-pressed={lineFilter===family(line)} className={lineFilter===family(line) ? 'is-active' : ''} style={{'--map-line':line.color} as React.CSSProperties} onClick={()=>{setLineFilter(family(line));setView(null);}}><i/>{nameOf(line)}</button>)}</div>
      <div className="explorer-body">
        <div className="explorer-map" ref={frame}>
          <div className="explorer-map-caption"><span><i/>{lineFilter==='all' ? operator==='all' ? 'Delhi + Noida' : operator==='dmrc' ? 'Delhi Metro' : 'Noida Metro' : nameOf(activeLines[0])}</span><span>{activeStations.length} stations</span></div>
          <svg ref={svg} className={dragging ? 'is-dragging' : ''} viewBox={`${current.x} ${current.y} ${current.width} ${current.height}`} role="group" aria-label="Metro network map. Select stations with the station search or map markers." tabIndex={0}
            onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp} onLostPointerCapture={pointerUp}
            onDoubleClick={event=>{ const matrix=svg.current?.getScreenCTM(); if(!matrix)return; const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());zoomAt(1.5,point);}}
            onKeyDown={event=>{if(event.target!==event.currentTarget)return; if(['+','=','-','0','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key))event.preventDefault();if(['+','='].includes(event.key))zoomAt(1.35);else if(event.key==='-')zoomAt(1/1.35);else if(event.key==='0')setView(null);else if(event.key.startsWith('Arrow'))setView(v=>{const before=v??base;return{...before,x:before.x+(event.key==='ArrowLeft' ? -1 : event.key==='ArrowRight' ? 1 : 0)*before.width*.08,y:before.y+(event.key==='ArrowUp' ? -1 : event.key==='ArrowDown' ? 1 : 0)*before.height*.08};});}}>
            <title>Delhi and Noida Metro station network</title>
            <g className="explorer-tracks">{activeLines.map(line=><polyline key={line.id} points={line.station_ids.map(id=>stationMap.get(id)).filter((s):s is Station=>Boolean(s)).map(s=>`${s.x},${s.y}`).join(' ')} fill="none" stroke={line.color} strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>)}</g>
            <g>{activeStations.map(point=>{
              const active=point.id===selected, interchange=interchanges.has(point.id);
              const color=network.lines.find(l=>l.station_ids.includes(point.id))?.color ?? '#1c6e79';
              return <g key={point.id} className={`explorer-station ${active?'is-selected':''}`} role="button" aria-label={`Select ${point.name} station`} aria-pressed={active} tabIndex={active?0:-1}
                onPointerEnter={()=>!dragging&&setHovered(point.id)} onPointerLeave={()=>setHovered('')} onFocus={()=>setHovered(point.id)} onBlur={()=>setHovered('')}
                onClick={event=>{event.stopPropagation();if(!suppressClick.current)onSelect(point.id);}}
                onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect(point.id);}}}>
                <title>{point.name}{interchange?' · Interchange':''}</title>
                {active&&<circle cx={point.x} cy={point.y} r={12/scale} fill="#188e8530"/>}
                <circle className="station-hit-area" cx={point.x} cy={point.y} r={10/scale} fill="transparent"/>
                <circle cx={point.x} cy={point.y} r={(active?5:interchange?4.1:2.65)/scale} fill={active?'#0c766c':'white'} stroke={active?'white':interchange?'#173c4d':color} strokeWidth={active?2:1.5} vectorEffect="non-scaling-stroke" pointerEvents="none"/>
                {interchange&&!active&&<circle cx={point.x} cy={point.y} r={1.4/scale} fill="#173c4d" pointerEvents="none"/>}
              </g>;
            })}</g>
            <g className="explorer-station-labels" pointerEvents="none">{labels.map(({station:point,x,y,anchor,width})=><g key={point.id}>{(point.id===selected||point.id===hovered)&&<rect x={anchor==='start'?x-5/scale:x-(width-5)/scale} y={y-14/scale} width={width/scale} height={20/scale} rx={5/scale} fill={point.id===selected?'#123e4b':'white'}/>}<text x={x} y={y} textAnchor={anchor} fontSize={11/scale} fontWeight={point.id===selected?700:500} className={point.id===selected?'selected-label':point.id===hovered?'hovered-label':''}>{point.name}</text></g>)}</g>
          </svg>
          <div className="explorer-zoom" aria-label="Map controls"><button aria-label="Zoom in" title="Zoom in (+)" onClick={()=>zoomAt(1.4)} disabled={zoom>=6.99}><Plus size={18}/></button><span aria-live="polite" aria-label="Map zoom">{Math.round(zoom*100)}%</span><button aria-label="Zoom out" title="Zoom out (−)" onClick={()=>zoomAt(1/1.4)} disabled={zoom<=1.001}><Minus size={18}/></button><span className="zoom-separator"/><button aria-label="Fit network to view" title="Fit this network (0)" onClick={()=>setView(null)}><Expand size={17}/></button><button aria-label="Reset map filters and view" title="Reset map" onClick={()=>{setOperator('all');setLineFilter('all');setView(null);setShowNames(false);}}><RotateCcw size={16}/></button></div>
          <div className="explorer-map-footer"><span><MousePointer2 size={13}/><span>Drag to explore · Double-click to zoom</span></span><span className="explorer-key"><i/>Station <i className="interchange-key"/>Interchange</span></div>
        </div>
        <aside className="explorer-sidebar" aria-label="Selected station details">
          <div className="explorer-search"><StationPicker label="Find a station" searchLabel="Search map stations" value={selected} onChange={focusStation} stations={network.stations} lines={network.lines}/></div>
          {station ? <>
            <div className="explorer-station-detail"><div className="explorer-station-heading"><span className="explorer-station-icon"><TrainFront size={23}/></span><span className={`explorer-zone zone-${station.zone}`}><i/>{zoneName[station.zone]??station.zone}</span></div><p className="explorer-overline">SELECTED STATION</p><h2>{station.name}</h2><p className="explorer-station-area">{station.area}</p>
              {serving.length>1&&<p className="explorer-interchange"><GitMerge size={14}/>Change between {serving.length} lines here</p>}
              <div className="explorer-serving">{serving.map(line=><span key={family(line)}><i style={{background:line.color}}/>{nameOf(line)}</span>)}</div>
              {!selectedVisible&&<button className="text-button" onClick={()=>focusStation(selected)}><MapPin size={13}/>Show station on map</button>}
              <div className="explorer-actions"><button className="outline" onClick={()=>onFrom(station.id)}><ArrowUpRight size={15}/>Start here</button><button className="primary" onClick={()=>onTo(station.id)}><ArrowDownLeft size={15}/>Go here</button></div>
            </div>
            <div className="explorer-arrivals"><div className="explorer-sidebar-heading"><h3>Station updates</h3><span title={connection==='live'?'Station updates are connected':'Showing saved or unavailable station information'}>{connection==='live'?<Wifi size={14}/>:<WifiOff size={14}/>}</span></div>
              {updates.map((signal,i)=><div className="explorer-community" key={i}><Radio size={15}/><div><strong>{signal.event_type==='delayed'||!signal.event_type ? `${Math.ceil((signal.delay_seconds??0)/60)} min reported extra wait` : `Train ${signal.event_type==='crowded'?'platform reported crowded':signal.event_type}`}</strong><p>{signal.confirmations} accounts agree · {Math.max(0,Math.floor((now-Date.parse(signal.last_observed_at))/1000))}s ago</p></div></div>)}
              {stationArrivals.length ? stationArrivals.map(arrival=><div className="explorer-arrival" key={arrival.id}><div><strong>{arrival.train_code}</strong><span>{arrival.source==='schedule'?'Scheduled service':'Predicted arrival'}</span></div><b>{connection==='live'?`${Math.max(0,Math.ceil((Date.parse(arrival.arrival_at)-now)/60000))} min`:'Saved'}</b></div>) : <div className="explorer-arrival-empty"><span><Clock3 size={17}/></span><div><strong>Arrival times aren’t available yet</strong><p>You can still plan your journey using published travel-time estimates.</p></div></div>}
            </div>
            {primaryLine&&neighbours.length>0&&<div className="explorer-neighbours"><h3>On the {nameOf(primaryLine)}</h3>{neighbours.map(point=><button key={point.id} onClick={()=>focusStation(point.id)}><span><i style={{background:primaryLine.color}}/>{point.name}</span><ArrowUpRight size={14}/></button>)}</div>}
          </> : <div className="explorer-pick-station"><MapPin size={30}/><h2>Choose your next stop</h2><p>Select any station on the map or search by name.</p></div>}
        </aside>
      </div>
      <div className="explorer-note"><MapPin size={13}/><span>Indicative network layout. Route details include walking and interchange information.</span></div>
    </div>
  </section>;
}
