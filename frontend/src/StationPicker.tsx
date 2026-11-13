import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, MapPin, Search } from 'lucide-react';
import type { Line, Station } from './types';

export function StationPicker({ label, value, onChange, stations, lines, searchLabel }: { label: string; value: string; onChange: (id: string) => void; stations: Station[]; lines: Line[]; searchLabel?: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const selected = stations.find(s => s.id === value);
  const accessibleLabel = label.toLowerCase().endsWith('station') ? label : `${label} station`;
  const words=query.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().split(/\s+/);
  const matches = stations.filter(s => { const text=`${s.name} ${s.id} ${s.area}`.toLowerCase().replace(/[^a-z0-9]+/g,' '); return words.every(word => text.includes(word)); }).sort((a,b) => a.name.localeCompare(b.name));
  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const close = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  function choose(id: string) { onChange(id); setOpen(false); }
  const identifier = `station-${label.toLowerCase().replaceAll(' ', '-')}`;
  useEffect(() => { if (open) document.getElementById(`${identifier}-${active}`)?.scrollIntoView({block:'nearest'}); },[active,open]);
  return <div className="station-picker" ref={root}>
    <span className="field-label">{label.toUpperCase()}</span>
    <button type="button" className="station-select" aria-label={accessibleLabel} aria-haspopup="listbox" aria-expanded={open} onClick={() => { setQuery(''); setActive(0); setOpen(!open); }}><MapPin size={17}/><span>{selected?.name || 'Select a station'}</span><ChevronDown size={16}/></button>
    {open && <div className="station-popover"><div className="station-search"><Search size={17}/><input ref={search} role="combobox" aria-label={searchLabel ?? `Search ${label.toLowerCase()} station`} aria-expanded="true" aria-controls={identifier} aria-activedescendant={matches[active] ? `${identifier}-${active}` : undefined} placeholder="Search station or sector…" value={query} onChange={e => { setQuery(e.target.value); setActive(0); }} onKeyDown={e => {
      if (e.key === 'Escape') setOpen(false);
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive(Math.min(active + 1, matches.length - 1)); }
      if (e.key === 'ArrowUp') { e.preventDefault(); setActive(Math.max(0, active - 1)); }
      if (e.key === 'Enter' && matches[active]) { e.preventDefault(); choose(matches[active].id); }
    }}/></div><div className="station-options" id={identifier} role="listbox" aria-label={`${label} stations`}>{matches.map((s,i) => <button type="button" role="option" id={`${identifier}-${i}`} aria-selected={s.id === value} className={i === active ? 'option-active' : ''} key={s.id} onClick={() => choose(s.id)}><span><strong>{s.name}</strong><small>{[...new Set(lines.filter(l => s.line_ids.includes(l.id)).map(l => l.name.replace(' · Inderlok branch','')))].join(' · ')}</small></span>{s.id === value && <Check size={16}/>}</button>)}{!matches.length && <p>No station matches that search.</p>}</div><small className="picker-count">{matches.length} stations · Delhi + Noida</small></div>}
  </div>;
}

