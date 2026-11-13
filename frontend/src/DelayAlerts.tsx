import { useEffect, useRef, useState } from 'react';
import { Bell } from 'lucide-react';
import { readStored, saveStored, sourceName } from './api';
import type { Network, Route } from './types';

export function DelayAlerts({route,network,now,connected}: {route?: Route;network: Network;now: number;connected: boolean}) {
  const [enabled,setEnabled]=useState(()=>readStored('metro-delay-notifications',false));
  const [message,setMessage]=useState('');
  const seen=useRef<string[]>(readStored('metro-delay-notification-ids',[]));
  const alerts=connected ? (route?.source_statuses ?? []).filter(status=>status.source!=='schedule' && status.delay_seconds>=60 && status.valid_until && now<Date.parse(status.valid_until)) : [];
  const stationName=(id?:string)=>network.stations.find(station=>station.id===id)?.name ?? id;
  async function toggle() {
    if(enabled) {setEnabled(false);saveStored('metro-delay-notifications',false);setMessage('Journey notifications disabled.');return;}
    if(!('Notification' in window) || !window.isSecureContext) {setMessage('Browser notifications are unavailable. Delay alerts still appear in your journey.');return;}
    try {
      const permission=await Notification.requestPermission();
      if(permission==='granted') {setEnabled(true);saveStored('metro-delay-notifications',true);setMessage('Notifications enabled while this app is open.');}
      else setMessage('Notification permission was not granted. In-app delay updates remain available.');
    } catch {setMessage('Browser notifications are unavailable. Delay alerts still appear in your journey.');}
  }
  useEffect(()=>{
    if(!enabled || !('Notification' in window) || Notification.permission!=='granted')return;
    for(const alert of alerts) {
      const id=[alert.boarding_station_id,alert.line_id,alert.direction,alert.last_observed_at,alert.delay_seconds].join(':');
      if(seen.current.includes(id))continue;
      seen.current=[...seen.current.slice(-49),id];saveStored('metro-delay-notification-ids',seen.current);
      const title=`Delay at ${stationName(alert.boarding_station_id)}`;
      const options={body:`${Math.ceil(alert.delay_seconds/60)} min extra wait · ${sourceName[alert.source]}`,tag:id,icon:'/icon.svg'};
      void (async()=>{
        try {const worker=await navigator.serviceWorker?.getRegistration();if(worker)await worker.showNotification(title,options);else new Notification(title,options);}catch{setMessage('Browser delivery is unavailable. The delay is shown in the journey.');}
      })();
    }
  },[enabled,route,connected]);
  return <div className="journey-alerts"><button className="outline" aria-pressed={enabled} onClick={toggle}><Bell size={14}/>{enabled ? 'Disable journey notifications' : 'Enable journey delay alerts'}</button><span className="small muted">For the selected route, while the app is open.</span>{message && <p role="status">{message}</p>}{alerts.map((alert,index)=><p className="delay-alert" role="status" key={index}><Bell size={15}/>{stationName(alert.boarding_station_id)} · {Math.ceil(alert.delay_seconds/60)} min extra wait · {sourceName[alert.source]}</p>)}</div>;
}
