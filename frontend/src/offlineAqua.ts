import type { JourneySnapshot, Network, Preference, RouteStep } from './types';

export function offlineAqua(network: Network | null, origin: string, destination: string, preference: Preference, now=Date.now()): JourneySnapshot | null {
  const line=network?.lines.find(l=>l.operator_id==='nmrc' && l.station_ids.includes(origin) && l.station_ids.includes(destination));
  if (!network || !line?.segments || origin===destination) return null;
  const first=line.station_ids.indexOf(origin), last=line.station_ids.indexOf(destination), increment=first<last ? 1 : -1;
  const steps: RouteStep[]=[];
  let duration=0,distance=0;
  for(let i=first;i!==last;i+=increment) {
    const segment=line.segments[increment===1 ? i : i-1];
    if (!segment || !Number.isFinite(segment.seconds) || segment.seconds<=0) return null;
    steps.push({kind:'ride',from_station_id:line.station_ids[i],to_station_id:line.station_ids[i+increment],
      line_id:line.id,family_id:line.family_id,context:segment.zone,seconds:segment.seconds,
      wait_seconds:0,delay_seconds:0,source:'schedule',departure_at:new Date(now+duration*1000).toISOString(),
      arrival_at:new Date(now+(duration+segment.seconds)*1000).toISOString()});
    duration+=segment.seconds;distance+=segment.metres;
  }
  return {origin,destination,preference,network_version:network.version,generated_at:new Date(now).toISOString(),snapshot_version:0,reason:null,
    timing_note:'Offline Aqua Line estimate from the saved operator catalogue. Ordinary boarding wait, security and access are additional. No live delay is included.',
    routes:[{id:`offline-${origin}-${destination}`,steps,duration_seconds:duration,distance_metres:distance,
      walking_metres:0,station_count:steps.length+1,transfers:0,source:'schedule',delay_seconds:0,
      recommendations:['fastest','fewest_changes','least_walking','shortest_distance'],
      arrival_at:new Date(now+duration*1000).toISOString(),source_statuses:[]}]};
}
