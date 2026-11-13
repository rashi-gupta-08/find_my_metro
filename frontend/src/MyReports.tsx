import { Clock3, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from './api';
import type { Network } from './types';
import type { SurfaceReportController } from './useSurfaceReports';

const outcomes: Record<string,string>={queued:'Processing',validated:'Checked',confirmed:'Agreement confirmed',awaiting_agreement:'Awaiting agreement',expired:'Expired',historical:'Historical report',rejected:'Rejected',dead_letter:'Processing failed',not_in_current_agreement:'Superseded or outside current agreement'};
const reasons: Record<string,string>={outside_station_proximity:'Location was more than 250 metres from the station.',location_evidence_required:'A usable location fix or reviewed cell match is required.',unverified_cell_location:'Cell readings could not be matched accurately to this station.',stale_surface_report:'This report was too old to affect current delays.',future_timestamp:'Check the time on your device.',inactive_contributor:'The contributor account is unavailable.',station_line_mismatch:'The station and line do not match.'};
export function MyReports({network,controller,now}: {network: Network;controller: SurfaceReportController;now: number}) {
  const [rewards,setRewards]=useState<{points:number;validated_contributions:number;badges:string[];award_policy:string}|null>(null);
  useEffect(()=>{let active=true; void api.contributions().then(value=>{if(active)setRewards(value);}).catch(()=>{});return()=>{active=false;};},[controller.reports]);
  const name=(id:string)=>network.stations.find(station=>station.id===id)?.name ?? id;
  return <section className="section my-reports" aria-label="My reports"><div className="section-heading"><div><h2>My reports</h2><p>Private processing outcomes and current agreement.</p></div><button className="text-button" onClick={controller.refresh}><RefreshCw size={13}/>Refresh reports</button></div>
    {rewards && <div className="panel contribution-summary"><strong>{rewards.points} contribution points</strong><p>{rewards.validated_contributions} confirmed contributions · {rewards.badges.join(" · ") || "Your first badge awaits"}</p><p className="small muted">{rewards.award_policy}</p></div>}
    {!controller.historyAvailable && <p className="small muted">Report status is unavailable. Reconnect to refresh; queued reports stay on this device.</p>}
    {controller.queue.length>0 && <div className="panel queue-notice"><span>{controller.queue.length} report(s) waiting to upload</span><button className="outline" disabled={controller.busy} onClick={controller.retry}>Retry upload</button></div>}
    {controller.reports.length ? <div className="report-history">{controller.reports.map(report => {
      const age=Math.max(0,Math.floor((now-Date.parse(report.observed_at))/1000));
      const outcome=age>=(report.live_ttl_seconds ?? 30) && ['confirmed','awaiting_agreement','not_in_current_agreement','validated'].includes(report.outcome) ? 'expired' : report.outcome;
      return <article className="panel report-outcome" key={report.event_id}><div><ShieldCheck size={17}/><strong>{name(report.station_id)}</strong><span className="pill">{outcomes[outcome] ?? outcome}</span></div><p>{report.event_type && report.event_type!=='delayed' ? report.event_type : `${Math.round(report.delay_seconds/60)} min reported extra wait`} · {report.direction}</p><p className="small muted"><Clock3 size={12}/>{age}s since observation{['confirmed','awaiting_agreement'].includes(outcome) && ` · ${report.confirmations}/${report.required_confirmations} accounts agree`}</p>{reasons[report.reason] && <p>{reasons[report.reason]}</p>}</article>;
    })}</div> : controller.historyAvailable && <div className="panel no-alerts">You have not submitted a station report yet.</div>}
  </section>;
}
