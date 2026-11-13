import { useEffect, useRef, useState } from 'react';
import { api, ApiError, readStored, saveStored } from './api';
import type { Account } from './api';
import type { ReportOutcome, SurfaceReport } from './types';

const recent = (reports: SurfaceReport[]) => reports.filter(report => Number.isFinite(Date.parse(report.observed_at)) && Date.now()-Date.parse(report.observed_at)>=-5000 && Date.now()-Date.parse(report.observed_at)<86400000).slice(-100);
export function useSurfaceReports(user: Account | null) {
  const owner = user?.id ?? '';
  const [pending,setPending] = useState<{owner: string; reports: SurfaceReport[]}>({owner:'',reports:[]});
  const [history,setHistory] = useState<{owner: string; reports: ReportOutcome[]}>({owner:'',reports:[]});
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState('');
  const [historyAvailable,setHistoryAvailable] = useState(false);
  const activeOwner = useRef(owner); activeOwner.current = owner;
  const running = useRef(false);
  const queue = pending.owner===owner ? pending.reports : [];
  const reports = history.owner===owner ? history.reports : [];
  const queueRef = useRef(queue); queueRef.current = queue;
  const key = `metro-surface-queue:${owner}`;
  useEffect(() => {
    setPending({owner,reports:owner ? recent(readStored<SurfaceReport[]>(key,[])) : []});
    setHistory({owner,reports:[]}); setMessage(''); setHistoryAvailable(false); setBusy(false);
  },[owner,key]);
  useEffect(() => { if (owner && pending.owner===owner) saveStored(key,recent(pending.reports)); },[pending,owner,key]);
  async function refresh() {
    if (!owner || !navigator.onLine) { setHistoryAvailable(false); return; }
    try { const next=await api.mySurfaceReports(); if(activeOwner.current===owner) { setHistory({owner,reports:next.reports}); setHistoryAvailable(true); } }
    catch (problem) { if(activeOwner.current===owner) {setHistoryAvailable(false);if(problem instanceof ApiError && problem.status===401)window.dispatchEvent(new Event('metro-session-expired'));} }
  }
  async function upload(batch: SurfaceReport[]) {
    if (!owner || running.current || !batch.length) return;
    running.current=true; setBusy(true);
    try {
      const result=await api.submitSurface(batch);
      if(activeOwner.current!==owner) return;
      const settled=new Set(result.acknowledgements.filter(ack => ['queued','duplicate','rejected','conflict'].includes(ack.status)).map(ack => ack.client_event_id));
      setPending(current => current.owner===owner ? {...current,reports:recent(current.reports.filter(report=>!settled.has(report.event_id)))} : current);
      const rejected=result.acknowledgements.find(ack=>['rejected','conflict'].includes(ack.status));
      setMessage(rejected ? `Upload ${rejected.status}: ${(rejected.reason ?? 'event conflict').replaceAll('_',' ')}` : 'Report saved. Check My reports for GPS validation and agreement.');
      await refresh();
    } catch(problem) {
      if(activeOwner.current!==owner) return;
      if (!(problem instanceof ApiError) || [429,503].includes(problem.status)) {
        setPending(current=>({owner,reports:recent([...(current.owner===owner ? current.reports : []),...batch.filter(report=>!current.reports.some(saved=>saved.event_id===report.event_id))])}));
        setMessage('Saved locally. Upload retries automatically while this app is open. Reports keep their original time.');
      } else {setMessage((problem as Error).message);if(problem.status===401)window.dispatchEvent(new Event('metro-session-expired'));}
    } finally { running.current=false; if(activeOwner.current===owner) setBusy(false); }
  }
  useEffect(() => {
    if(!owner) return;
    void refresh();
    const retry=()=>{ if(navigator.onLine && queueRef.current.length) void upload(recent(queueRef.current)); void refresh(); };
    const refreshTimer=setInterval(()=>void refresh(),5000);
    const retryTimer=setInterval(retry,15000);
    const pruneTimer=setInterval(()=>setPending(current=>current.owner===owner ? {...current,reports:recent(current.reports)} : current),60000);
    window.addEventListener('online',retry);
    return ()=>{clearInterval(refreshTimer);clearInterval(retryTimer);clearInterval(pruneTimer);window.removeEventListener('online',retry);};
  },[owner]);
  return {queue,reports,busy,message,setMessage,historyAvailable,refresh,send:(report: SurfaceReport)=>upload([report]),retry:()=>upload(recent(queueRef.current))};
}
export type SurfaceReportController = ReturnType<typeof useSurfaceReports>;
