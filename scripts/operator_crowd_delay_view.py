"""Add inspectable delay reports to the offline panel using saved evidence only.

This view does not create new reports or change the completed experiment.
"""
import csv
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/operator-crowd-100-users'
START = '<!-- DELAY_REPORT_VIEW_START -->'
END = '<!-- DELAY_REPORT_VIEW_END -->'


def augment_delay_reports(page, output=OUT):
    output = Path(output)
    result = json.loads((output/'combined-results.json').read_text(encoding='utf-8'))
    network = json.loads((output/'operator-network-snapshot.json').read_text(encoding='utf-8'))
    raw = [json.loads(line) for line in (output/'crowd-reports.jsonl').read_text(encoding='utf-8').splitlines()]
    stations = {s['id']:s['name'] for s in network['stations']}
    lines = {l['id']:l for l in network['lines']}
    unique = {}
    for row in result['observations']:
        unique.setdefault((row['phase'],row['cohort']),row)
    summaries = []
    for (phase,cohort), row in unique.items():
        members = [item for item in raw if item['phase']==phase and item['cohort']==cohort]
        summaries.append({'phase':phase,'cohort':cohort,'station_id':row['origin'],'station':stations[row['origin']],
            'destination':stations[row['destination']],'operator':lines[row['line_id']]['operator_id'].upper(),
            'context':row['actual_context'],'source':row['actual_source'],
            'baseline_seconds':row['baseline_seconds'],'accepted_delay_seconds':row['actual_delay_seconds'],
            'journey_seconds':row['actual_journey_seconds'],'confirmations':row['confirmations'],
            'reports_submitted':len(members),
            'validated_reports':sum(item['actual_processing']=='validated' for item in members),
            'historical_reports':sum(item['actual_processing']=='historical' for item in members),
            'rejected_reports':sum(item['actual_processing']=='rejected' for item in members)})
    with (output/'delay-report-summary.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)
    reports=[]
    for item in raw:
        report=item['report']
        reports.append({'phase':item['phase'],'participant':item['participant'],'cohort':item['cohort'],
            'event_id':report['event_id'],'station':stations[report['station_id']],
            'operator':lines[report['line_id']]['operator_id'].upper(),'line':lines[report['line_id']]['name'],
            'direction':report['direction'],'observed_at':report['observed_at'],
            'delay_seconds':report['delay_seconds'],'processing_status':item['actual_processing'],
            'reason':item['reason'],'received_at':item['received_at'],'validated_at':item['validated_at']})
    payload=json.dumps({'reports':reports,'summaries':summaries},ensure_ascii=False).replace('</','<\\/')
    block='''<!-- DELAY_REPORT_VIEW_START -->
<style>
.delay-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:20px 0}
.delay-example{border:1px solid #c9dfe2;border-radius:12px;padding:18px;background:#f7fbfb}
.delay-example h3{font-size:17px;margin:12px 0 6px}.delay-amount{display:block;font-size:29px;font-weight:750;color:#11666b;margin:10px 0}
.delay-math{font-size:14px;line-height:1.8;margin:12px 0}.delay-math b{color:#123148}
.delay-example button{width:100%;margin:8px 0 0;background:#123148;color:white;border-color:#123148}
.delay-filters label{font-size:14px;display:flex;align-items:center;gap:6px}.delay-stats{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.delay-stats span{border-radius:8px;background:#eef4f7;padding:8px 12px;font-size:14px}.delay-stats strong{font-size:17px;margin-right:4px}
.delay-log{max-height:420px;border:1px solid #dde7ed;border-radius:8px}.delay-log th{position:sticky;top:0;z-index:1}
.delay-log td{vertical-align:top}.delay-log small{display:block;color:#536c7c;margin-top:4px;max-width:260px;white-space:normal}
.delay-status{font-size:13px;padding:4px 8px;border-radius:12px;display:inline-block;background:#deefea}
.delay-status.historical{background:#fff0d3;color:#74510a}.delay-status.rejected{background:#fbe5e3;color:#89362e}
.delay-empty{text-align:center;padding:24px;white-space:normal}.delay-time{font-size:12px}
@media(max-width:850px){.delay-cards{grid-template-columns:1fr}.delay-filters label{flex-wrap:wrap}.delay-filters select{max-width:100%}}
</style>
<section class="card" id="delay-reports" aria-labelledby="delay-report-title">
<span class="tag">Recorded synthetic beta reports</span><h2 id="delay-report-title">Crowdsourced delay reports</h2>
<p>Inspect the reports behind the journey updates. These examples show the accepted group delay; individual reports can differ. All times and outcomes come from the completed 100-account experiment.</p>
<div class="delay-cards" id="delay-examples"></div>
<div class="controls delay-filters">
<label for="delay-phase">Report phase <select id="delay-phase"><option value="all">All phases</option></select></label>
<label for="delay-outcome">Outcome <select id="delay-outcome"><option value="all">All outcomes</option><option value="validated">Validated for agreement</option><option value="historical">Historical upload</option><option value="rejected">Rejected</option></select></label>
<label for="delay-operator">Operator <select id="delay-operator"><option value="all">DMRC and NMRC</option><option value="DMRC">DMRC</option><option value="NMRC">NMRC</option></select></label>
</div>
<div class="delay-stats" aria-live="polite"><span><strong id="delay-count">0</strong> reports shown</span><span><strong id="delay-valid">0</strong> validated</span><span><strong id="delay-historical">0</strong> historical</span><span><strong id="delay-rejected">0</strong> rejected</span></div>
<div class="scroll delay-log" tabindex="0" role="region" aria-label="Scrollable delay report log">
<table><thead><tr><th>Observed time IST</th><th>Simulated user</th><th>Station and line</th><th>Reported delay</th><th>Worker outcome</th><th>Validation reason</th><th>Event ID</th></tr></thead><tbody id="delay-log-body"></tbody></table></div>
<p class="muted">Validated reports are eligible for independent-account agreement. Only the confirmed group delay is added to the journey, once at boarding. Historical and rejected reports cannot change the live estimate. Outbound and inbound follow the stored line order.</p>
<p><a href="crowd-reports.csv">Download all 400 delay reports CSV</a> · <a href="delay-report-summary.csv">Download delay and journey summary CSV</a></p>
</section>
<script type="application/json" id="delay-report-data">__DELAY_DATA__</script>
<script>
(()=>{
const data=JSON.parse(document.getElementById('delay-report-data').textContent);
const filterPhase=document.getElementById('delay-phase'),filterOutcome=document.getElementById('delay-outcome'),filterOperator=document.getElementById('delay-operator');
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const phases=[['initial_static','Initial static'],['boundary_agreement','Boundary agreement'],['surface_and_underground','After boundary'],['evidence_expired','Evidence expired'],['fresh_evidence_recovery','Fresh recovery']];
phases.forEach(([value,label])=>filterPhase.add(new Option(label,value)));
const duration=seconds=>{const m=Math.floor(seconds/60),s=seconds%60;return m+' min'+(s?' '+s+' s':'')};
const time=value=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
const reasons={awaiting_independent_agreement:'Location and freshness checks passed',stale_surface_report:'Upload was 45 seconds old; live limit is 30 seconds',outside_station_proximity:'GPS was outside the 250 m station boundary',location_evidence_required:'No verified location supplied; static baseline retained'};
const titles=['DMRC boundary agreement','DMRC surface delay','NMRC surface recovery'];
const features=[['boundary_agreement','DMRC underground to surface'],['surface_and_underground','DMRC underground to surface'],['fresh_evidence_recovery','NMRC outbound']].map(([phase,cohort])=>data.summaries.find(r=>r.phase===phase&&r.cohort===cohort));
document.getElementById('delay-examples').innerHTML=features.map((r,i)=>`<article class="delay-example"><span class="tag">${titles[i]}</span><h3>${escape(r.station)} → ${escape(r.destination)}</h3><span class="delay-amount">+${duration(r.accepted_delay_seconds)}</span><span class="muted">${r.confirmations} simulated accounts in agreement</span><p class="delay-math">Operator baseline <b>${duration(r.baseline_seconds)}</b><br>With accepted delay <b>${duration(r.journey_seconds)}</b></p><button type="button" data-delay-example="${i}">View these reports</button></article>`).join('');
function render(){
const filtered=data.reports.filter(r=>(filterPhase.value==='all'||r.phase===filterPhase.value)&&(filterOutcome.value==='all'||r.processing_status===filterOutcome.value)&&(filterOperator.value==='all'||r.operator===filterOperator.value));
document.getElementById('delay-count').textContent=filtered.length;
document.getElementById('delay-valid').textContent=filtered.filter(r=>r.processing_status==='validated').length;
document.getElementById('delay-historical').textContent=filtered.filter(r=>r.processing_status==='historical').length;
document.getElementById('delay-rejected').textContent=filtered.filter(r=>r.processing_status==='rejected').length;
document.getElementById('delay-log-body').innerHTML=filtered.length?filtered.map(r=>`<tr><td class="delay-time">${escape(time(r.observed_at))}</td><td>User ${r.participant}<small>${escape(r.cohort)}</small></td><td>${escape(r.station)}<small>${escape(r.operator+' · '+r.line+' · '+r.direction)}</small></td><td>+${duration(r.delay_seconds)}</td><td><span class="delay-status ${r.processing_status}">${r.processing_status==='validated'?'Validated':r.processing_status==='historical'?'Historical':'Rejected'}</span></td><td>${escape(reasons[r.reason]||r.reason)}</td><td><code>${escape(r.event_id)}</code></td></tr>`).join(''):`<tr><td colspan="7" class="delay-empty">${filterPhase.value==='evidence_expired'?'No reports were submitted in the expiry phase. All 100 clients returned to static timing when earlier reports expired.':'No delay reports match these filters.'}</td></tr>`;
}
[filterPhase,filterOutcome,filterOperator].forEach(control=>control.addEventListener('change',render));
document.querySelectorAll('[data-delay-example]').forEach(button=>button.addEventListener('click',()=>{
const r=features[Number(button.dataset.delayExample)];filterPhase.value=r.phase;filterOutcome.value='all';filterOperator.value=r.operator;render();
const phase=document.getElementById('phase');phase.value=r.phase;phase.dispatchEvent(new Event('change'));
document.getElementById('delay-log-body').closest('.delay-log').scrollTop=0;
}));render();
})();
</script>
<!-- DELAY_REPORT_VIEW_END -->'''.replace('__DELAY_DATA__',payload)
    if START in page:
        page=re.sub(re.escape(START)+r'.*?'+re.escape(END),lambda _:block,page,flags=re.S)
    else:
        anchor='<section class="card"><h2>Figure 10</h2>'
        if anchor not in page:raise ValueError('Expected panel insertion point missing')
        page=page.replace(anchor,block+'\n'+anchor,1)
    return page


if __name__=='__main__':
    target=OUT/'panel-demo.html'
    target.write_text(augment_delay_reports(target.read_text(encoding='utf-8')),encoding='utf-8')
    print('Added recorded delay cards, a filterable 400-report log and delay summary CSV.')
