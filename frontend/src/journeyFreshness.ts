import type { Route } from './types';

// A lost connection must not leave a past community delay in the displayed total.
// Keep the original evidence metadata so the passenger can still inspect its age.
export function displayRoute(route: Route, now: number, connected: boolean): Route {
  let removed = 0;
  const steps = route.steps.map(step => {
    const expires = step.source_status?.valid_until;
    const stale = !connected || Boolean(expires && now >= Date.parse(expires));
    const delay = stale ? step.delay_seconds ?? 0 : 0;
    const departure = Date.parse(step.departure_at) - removed * 1000;
    removed += delay;
    return delay ? {...step, seconds: Math.max(0, step.seconds-delay), delay_seconds: 0,
      wait_seconds: Math.max(0, step.wait_seconds-delay), source: 'schedule',
      departure_at: new Date(departure).toISOString(),
      arrival_at: new Date(Date.parse(step.arrival_at)-removed*1000).toISOString()}
      : removed ? {...step, departure_at: new Date(departure).toISOString(),
        arrival_at: new Date(Date.parse(step.arrival_at)-removed*1000).toISOString()} : step;
  });
  if (!removed) return route;
  return {...route, steps, duration_seconds: Math.max(0, route.duration_seconds-removed),
    delay_seconds: Math.max(0, (route.delay_seconds ?? 0)-removed),
    source: steps.some(step=>step.source!=='schedule') ? 'live_and_schedule' : 'schedule',
    arrival_at: new Date(Date.parse(route.arrival_at)-removed*1000).toISOString()};
}
