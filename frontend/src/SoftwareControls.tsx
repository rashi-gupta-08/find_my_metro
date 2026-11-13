import { useEffect, useState } from 'react';
import { Play, Radio } from 'lucide-react';

interface Feed { enabled: boolean; scenario: string; scenarios: { id: string; label: string }[] }
export function SoftwareControls({ onReplay }: { onReplay: () => void }) {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [scenario, setScenario] = useState('normal');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let alive = true;
    fetch('/api/v1/software/status').then(async (response) => {
      if (!response.ok) return;
      const data = await response.json();
      if (alive) { setFeed(data); setScenario(data.scenario); }
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!feed) return null;
  async function replay() {
    setBusy(true); setMessage('');
    try {
      const response = await fetch('/api/v1/software/scenario', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario }) });
      if (!response.ok) throw new Error('Could not restart the software feed. Please retry.');
      setFeed(await response.json()); onReplay();
      setMessage('Journey restarted. Incoming events determine the operating mode automatically.');
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="panel software-controls" aria-label="Software input feed">
    <div><p className="eyebrow"><Radio size={14} /> SOFTWARE INPUT FEED</p><h2>Run the context-switching journey</h2>
      <p>Generated sensor and crowd events drive the actual backend. Stations, arrivals and training data are synthetic while hardware is being added.</p></div>
    <div className="software-actions"><label>JOURNEY CONDITION<select aria-label="Software journey condition" value={scenario} onChange={(event) => setScenario(event.target.value)}>{feed.scenarios.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><button className="primary" disabled={busy} onClick={replay}><Play size={15} />{busy ? 'Starting…' : 'Run journey'}</button></div>
    {message && <p role="status">{message}</p>}
  </section>;
}
