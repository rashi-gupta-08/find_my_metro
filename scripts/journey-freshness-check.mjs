import assert from 'node:assert/strict';
import {displayRoute} from '../frontend/src/journeyFreshness.ts';
import {offlineAqua} from '../frontend/src/offlineAqua.ts';
import fs from 'node:fs';

const now=Date.parse('2026-10-16T08:00:30Z');
const route={duration_seconds:900,delay_seconds:300,source:'live_and_schedule',arrival_at:'2026-10-16T08:15:00Z',steps:[
  {seconds:600,delay_seconds:300,wait_seconds:300,source:'crowd',departure_at:'2026-10-16T08:00:00Z',arrival_at:'2026-10-16T08:10:00Z',source_status:{valid_until:'2026-10-16T08:00:30Z'}},
  {seconds:300,delay_seconds:0,wait_seconds:0,source:'schedule',departure_at:'2026-10-16T08:10:00Z',arrival_at:'2026-10-16T08:15:00Z'}]};
assert.equal(displayRoute(route,now-1,true).duration_seconds,900);
for(const [time,connected] of [[now,true],[now-1,false]]){
  const shown=displayRoute(route,time,connected);
  assert.equal(shown.duration_seconds,600);assert.equal(shown.delay_seconds,0);
  assert.equal(shown.source,'schedule');assert.equal(shown.steps[0].arrival_at,shown.steps[1].departure_at);
  assert.equal(shown.arrival_at,'2026-10-16T08:10:00.000Z');
  assert.equal(shown.steps.reduce((n,s)=>n+s.seconds,0),shown.duration_seconds);
}
assert.equal(route.duration_seconds,900,'Saved evidence is retained for audit; display conversion does not overwrite it');
console.log('Client freshness checks passed: expiry, disconnect, coherent times and unchanged saved evidence.');
const network=JSON.parse(fs.readFileSync(new URL('../data/operator-network.json',import.meta.url),'utf8'));
let count=0;
const aqua=network.lines.find(l=>l.operator_id==='nmrc');
for(const origin of aqua.station_ids)for(const destination of aqua.station_ids)if(origin!==destination){
  const snapshot=offlineAqua(network,origin,destination,'fastest',now);
  assert(snapshot && snapshot.routes.length===1);
  const route=snapshot.routes[0];
  assert.equal(route.steps[0].from_station_id,origin);assert.equal(route.steps.at(-1).to_station_id,destination);
  assert.equal(route.steps.reduce((n,s)=>n+s.seconds,0),route.duration_seconds);
  assert.equal(route.delay_seconds,0);assert.equal(route.source,'schedule');count++;
}
assert.equal(offlineAqua(network,'dmrc-rck','nmrc-17','fastest',now),null);
console.log(`Web offline checks passed for ${count} Aqua station pairs; uncovered journeys stay explicit.`);
