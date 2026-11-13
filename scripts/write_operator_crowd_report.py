"""Create panel and paper artifacts from the verified combined experiment."""
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/operator-crowd-100-users'


def main():
    result=json.loads((OUT/'combined-results.json').read_text())
    audit=json.loads((OUT/'operator-provenance-audit.json').read_text())
    assert json.loads((OUT/'verification.json').read_text())['all_checks_passed']
    rows=result['observations'];phases=list(dict.fromkeys(r['phase'] for r in rows));cohorts=list(dict.fromkeys(r['cohort'] for r in rows))
    unique=[next(r for r in rows if r['phase']==p and r['cohort']==c) for p in phases for c in cohorts]
    phase_labels=['Initial static','Boundary agreement','After boundary','Evidence expired','Fresh recovery']
    scope=('We evaluated a software-only passenger journey estimator using the stored DMRC and NMRC indicative travel times plus synthetic crowd reports. '
        'The run used 100 simulated accounts on one computer, not 100 recruited commuters. The output is a planned journey duration and a community-reported station delay; '
        'no individual real train position or next-train arrival was established.')
    protocol=('Four cohorts of 25 accounts queried a DMRC Blue Line underground-to-surface sequence, the reverse boundary direction, and NMRC Aqua Line journeys in both directions. '
        'The script changed query origins to represent progress; geography came from configured segments. Five phases covered static operation, boundary agreement, '
        'surface/underground separation, natural report expiry and fresh-report recovery. Each of four reporting waves released 100 authenticated HTTP clients together while 100 journey WebSockets were open. '
        'Accounts and revocable sessions were provisioned before measurement. Registration, browser rendering, mobile radio, cell-tower matching, hardware and ML inference were outside this test.')
    policy=('Reports required a station-consistent location and at least three distinct accounts with compatible delay values. Live evidence expired after 30 seconds. '
        'Three of each five accounts supplied nearby synthetic GPS reports with delays centered on the scenario value; one supplied an upload 45 seconds old and one supplied a distant coordinate. '
        'In phases without usable location evidence, all reports for that cohort omitted location and the static baseline remained active. '
        'The current implementation permits qualified phone evidence in any zone; this experiment does not assert that underground always disables crowdsourcing.')
    provenance=(f"The frozen 8 October 2026 catalogue contains {audit['stations']} stations, {audit['ordered_line_paths']} ordered line paths and {audit['segment_records']} segment records "
        '(261 DMRC and 20 NMRC). All 281 time values matched their archived public operator responses with zero transcription mismatches. '
        'DMRC times vary by segment; every stored NMRC adjacent segment is 120 seconds. These are indicative travel-time estimates, not measured arrivals or a dated train schedule. '
        f"The audit retained {len(audit['review_flags'])} unusual values for operator review without changing them. Transfer walking times are application estimates, and NMRC coordinates come from a historical OTD mirror.")
    metrics=[['Metric','Observed result'],['Simulated accounts / concurrent journey sockets','100 / 100'],
        ['Distinct cohort and phase conditions','20'],['Checked client journey updates',f"{result['passed_journey_updates']} / {result['journey_updates_checked']} passed"],
        ['Static / crowd-adjusted journey updates',f"{result['static_updates']} / {result['crowd_updates']}"],
        ['Unique reports / acknowledged',f"{result['unique_report_deliveries']} / {len(result['acks'])}"],
        ['Validated / historical / rejected',' / '.join(str(result['processing_outcomes'].get(k,0)) for k in ['validated','historical','rejected'])],
        ['Explicit duplicate retries','3 duplicates; zero additional stored observations'],
        ['Natural-expiry static fallback','100 / 100 clients'],['Journey arithmetic residual','0 seconds against injected-policy reference']]
    latency=[['Measured interval','Samples','p50 s','p95 s']]
    for title,key in [('HTTP acknowledgement','http_ack_latency'),('Receipt to worker outcome','receipt_to_processing_latency'),
        ('Observation to client journey read','observation_to_matching_journey_ws_latency')]:
        v=result[key];latency.append([title,str(v['n']),f"{v['p50_ms']/1000:.3f}",f"{v['p95_ms']/1000:.3f}"])
    outcomes=(f"All 400 unique reports were durably acknowledged and their worker outcomes matched the fixture labels: {result['processing_outcomes']['validated']} validated, "
        f"{result['processing_outcomes']['historical']} historical and {result['processing_outcomes']['rejected']} rejected. "
        f"All 500 checked journey updates matched expected context, selected evidence scope and duration arithmetic. There were 250 static and 250 crowd-adjusted updates. "
        'These 500 deliveries repeat 20 cohort/phase conditions; they are not 500 independent correctness scenarios. '
        'After live evidence expired without new reports, all 100 connections returned to the static baseline. '
        'Fresh reports restored crowd overlays for the three eligible cohorts, and duplicate resubmission created no additional observation. No phone report created an identified train.')
    latency_text=(f"In the completed run, HTTP acknowledgement p95 was {result['http_ack_latency']['p95_ms']/1000:.3f} s and "
        f"observation-to-client journey-read p95 was {result['observation_to_matching_journey_ws_latency']['p95_ms']/1000:.3f} s. "
        'The latter includes a per-wave worker-completion barrier in the client harness. These are single-run Windows loopback observations with PostgreSQL, not Internet or browser latency. '
        f"The completed run recorded {result['transport_errors_before_retry']} transport errors before retry. The initial run, retained in attempts/initial-transport-failure, "
        'had two unacknowledged ReadError requests and stored only 398 reports despite correct journey outputs. The harness was then changed to retry transport errors at most twice, '
        'using the same durable event ID and retaining attempt counts. HTTP errors and normal API rate limits were not bypassed.')
    limits=('The zero arithmetic residual verifies the rule journey duration = stored segment-time sum + accepted boarding delay. '
        'It is not an ETA MAE of zero against actual trains. No independent field arrivals were available, so field MAE, RMSE, tracking accuracy and real commuter benefits remain unmeasured. '
        'Reporters share scripted station coordinates and correlated injected delays; this does not test sophisticated collusion or prove independent people. '
        'The four routes cover selected Blue Line and Aqua Line fixtures, not every origin/destination or platform. Station-level zones need platform-specific review at multi-line interchanges. '
        'Transition coverage here means a configured geographic boundary and report qualification, not the separate identified-train handover/dead-reckoning algorithm. '
        'Prophet and Random Forest were not invoked, and results from the earlier separate synthetic model experiment must not be merged into this run.')
    conclusion=('The software combined traceable operator travel-time estimates with qualified crowd delay reports, maintained a static estimate when usable evidence was absent, '
        'and recovered after fresh reports arrived in this controlled 100-account run. This supports a supervised beta demonstration. '
        'A commuter pilot with consented reports, reviewed station geography and independently timestamped arrivals is needed to establish field ETA improvements.')
    caption=(OUT/'figure_10_caption.txt').read_text().strip()
    def md_table(table):
        return '\n'.join(['| '+' | '.join(table[0])+' |','| '+' | '.join(['---']*len(table[0]))+' |',*['| '+' | '.join(r)+' |' for r in table[1:]]])
    paper='\n\n'.join(['# Experimental validation of operator timings and crowdsourced delays',scope,'## Data and experimental method',provenance,protocol,policy,
        '## Results',outcomes,md_table(metrics),latency_text,md_table(latency),'![Figure 10](figure_10_operator_crowd.png)',caption,
        '## Interpretation and limitations',limits,conclusion,
        '## Sources','Frozen catalogue: `operator-network-snapshot.json`; segment-level public URLs, source values and hashes: `operator-baseline-segments.csv`. '
        'NMRC explicitly describes route travel times as indicative in its [journey planner](https://www.nmrcnoida.com/Passenger-Information/Journey-Planner-and-Fares). '
        'DMRC archived responses use `route[].path_time`; no API next-departure timestamp was used.'])+'\n'
    (OUT/'research_results_section.md').write_text(paper,encoding='utf-8')
    sources_dir=OUT/'reproduction/scripts';sources_dir.mkdir(parents=True,exist_ok=True)
    for name in ['audit_operator_baseline.py','test_operator_crowd_100.py','verify_operator_crowd.py','plot_operator_crowd.py','write_operator_crowd_report.py']:
        shutil.copy2(ROOT/'scripts'/name,sources_dir/name)
    csv_write=__import__('audit_operator_baseline').write_csv
    csv_write(OUT/'cohort-phase-summary.csv',unique)
    example_rows=[r for r in unique if r['phase']=='boundary_agreement']
    example_table=[['Journey','Operator sum s','Crowd delay s','Result s']]
    names={'DMRC underground to surface':'Mandi House to Yamuna Bank','DMRC surface to underground':'Supreme Court to Rajiv Chowk',
           'NMRC outbound':'Sector 51 to Sector 101','NMRC inbound':'Sector 101 to Sector 51'}
    example_table += [[names[r['cohort']],str(r['baseline_seconds']),str(r['actual_delay_seconds']),str(r['actual_journey_seconds'])] for r in example_rows]
    phase_table=[['Phase','DMRC U to S','DMRC S to U','NMRC both ways']]
    for i,p in enumerate(phases):
        vals=[next(r for r in unique if r['phase']==p and r['cohort']==c) for c in cohorts]
        phase_table.append([phase_labels[i],*[r['actual_context']+' / '+('crowd' if r['actual_source']=='crowd' else 'static') for r in vals[:2]],
            'surface / '+('crowd' if vals[2]['actual_source']=='crowd' else 'static')])
    # Plain research section with deliberate page breaks for review and insertion.
    from docx import Document
    from docx.shared import Inches,Pt,RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    document=Document();section=document.sections[0]
    section.page_width=Inches(8.27);section.page_height=Inches(11.69)
    section.top_margin=section.bottom_margin=Inches(.7);section.left_margin=section.right_margin=Inches(.75)
    for name in ['Normal','Title','Subtitle','Heading 1','Heading 2']:
        style=document.styles[name];style.font.name='Calibri';style.font.color.rgb=RGBColor(0,0,0)
    normal=document.styles['Normal'];normal.font.size=Pt(10.5);normal.paragraph_format.space_after=Pt(6)
    normal.paragraph_format.line_spacing=1.08
    document.styles['Title'].font.size=Pt(22);document.styles['Heading 1'].font.size=Pt(14)
    document.styles['Heading 1'].paragraph_format.space_before=Pt(10)
    footer=section.footer.paragraphs[0];footer.alignment=2
    footer.add_run('FindMyMetro  |  100 simulated accounts  |  ')
    fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');footer._p.append(fld)
    def para(text):document.add_paragraph(text)
    def heading(text):document.add_heading(text,level=1)
    def table(data,widths):
        t=document.add_table(rows=1,cols=len(data[0]));t.style='Table Grid';t.autofit=False
        for i,w in enumerate(widths):t.columns[i].width=Inches(w)
        for i,cell in enumerate(t.rows[0].cells):cell.text=data[0][i]
        for row in data[1:]:
            for cell,value in zip(t.add_row().cells,row):cell.text=value
        for row in t.rows:
            for i,cell in enumerate(row.cells):
                cell.width=Inches(widths[i])
                for p in cell.paragraphs:
                    p.paragraph_format.space_after=Pt(4)
                    for run in p.runs:run.font.size=Pt(9)
            trPr=row._tr.get_or_add_trPr();trPr.append(OxmlElement('w:cantSplit'))
        # Neutral header fill and readable black text.
        for cell in t.rows[0].cells:
            shd=OxmlElement('w:shd');shd.set(qn('w:fill'),'EDEDED');cell._tc.get_or_add_tcPr().append(shd)
            for p in cell.paragraphs:
                for run in p.runs:run.bold=True;run.font.color.rgb=RGBColor(0,0,0)
        para('')
    document.add_paragraph('FindMyMetro combined software evaluation',style='Title')
    para('Operator timing data and crowdsourced delay validation  |  4 November 2026')
    para(scope)
    heading('Operator data and provenance');para(provenance)
    heading('Experimental method');para(protocol);para(policy)
    heading('Context and evidence selection');table(phase_table,[1.45,1.65,1.65,1.98])
    document.add_page_break()
    heading('Measured results');para(outcomes);table(metrics,[3.4,3.33])
    heading('Measured latency');table(latency,[3.3,.65,1.39,1.39]);para(latency_text)
    heading('Worked examples at the boundary phase');table(example_table,[3.35,1.1,1.1,1.18])
    para('The baseline is independently recomputed from the stored adjacent segments for the returned physical route. The crowd delay is added once at the origin boarding point. No train-specific arrival is inferred.')
    document.add_page_break()
    heading('Figure 10 combined operator and crowd evaluation')
    document.add_picture(str(OUT/'figure_10_operator_crowd.png'),width=Inches(6.73))
    para(caption)
    heading('Reading the experiment');para('Panel a shows the selected evidence path as the query crosses configured zones. The reverse DMRC cohort returns to static timing after entering the underground segment without verified location evidence. NMRC stays in surface context throughout. All cohorts return to static when reports expire. Panel b compares the baseline and adjusted estimate for the same origin at each phase; it is not a measured train trajectory.')
    para('Panel c accounts for all submitted reports, including rejected and historical evidence. Panel d shows measured client delays, including retries and the processing barrier. Values are observations from one machine and workload, not population estimates or service guarantees.')
    document.add_page_break()
    heading('Discussion and research claims');para(limits);para(conclusion)
    heading('Reproduce the test');para('From the project folder in PowerShell, use the application Python environment and configured local PostgreSQL installation. The runner creates its own random database, migrates it, starts an API and worker on port 8021, runs the experiment and deletes only its own database. Normal passenger services are not stopped. Port 8021 must be free.')
    for command in [r'..\.venv\Scripts\python.exe scripts\test_operator_crowd_100.py',r'..\.venv\Scripts\python.exe scripts\verify_operator_crowd.py']:
        p=document.add_paragraph();run=p.add_run(command);run.font.name='Consolas';run.font.size=Pt(9)
    para('Each run regenerates observation timestamps. Reposting the exported CSV unchanged later will produce historical reports. Archive the output folder before rerunning if the measured run must remain unchanged.')
    heading('Evidence files');para('The pack includes the complete frozen network, 281 segment records with operator URLs and hashes, 280 unique source responses, 100 synthetic participant profiles, 400 report inputs and worker outcomes, 500 journey checks, 20 representative full WebSocket snapshots, HTTP acknowledgements, the initial failed run, the independent verifier and reproduction scripts. It contains no passenger database, session cookies or passwords.')
    heading('Sources');para('DMRC public passenger API archived on 8 October 2026: backend.delhimetrorail.com/api/v2/en/; adjacent route path_time values. NMRC StationList and Passenger Information Journey Planner and Fares: www.nmrcnoida.com. The current NMRC planner describes its travel times as indicative. Full segment URLs and SHA256 hashes are provided in operator-baseline-segments.csv.')
    for root in [document._element, document.styles.element]:
        for border in root.findall('.//'+qn('w:pBdr')):
            border.getparent().remove(border)
    document.save(OUT/'FindMyMetro_Combined_Test_Results.docx')
    # An entirely offline viewer: no upload, sign-in, live API or CDN dependency.
    payload=json.dumps({'result':result,'audit':audit,'phase_labels':phase_labels,'phases':phases,'cohorts':cohorts,'rows':rows,'unique':unique},ensure_ascii=False).replace('</','<\\/')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FindMyMetro combined test evidence</title>
<style>:root{font:16px system-ui;color:#123148;background:#f1f6f8}*{box-sizing:border-box}body{margin:0}main{max-width:1200px;margin:auto;padding:32px 24px}h1{font-size:clamp(26px,4vw,40px);margin:14px 0}h2{font-size:23px}.tag{background:#dae9f1;padding:6px 12px;border-radius:20px;font-size:13px;display:inline-block}.card{background:white;border:1px solid #d5e1e9;border-radius:16px;padding:24px;margin:22px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.stats div{border-left:3px solid #1c7f83;padding-left:16px}.stats strong{display:block;font-size:28px}.muted{color:#506777;line-height:1.6}select,button{font:inherit;padding:10px 14px;border:1px solid #b6cbd8;border-radius:8px;background:white;color:inherit;margin:4px}button{cursor:pointer}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;border-bottom:1px solid #e0e9ee;padding:12px;white-space:nowrap}th{background:#edf4f7}a{color:#086a7e}img{width:100%;height:auto}.pill{padding:4px 8px;border-radius:20px;background:#deefea}.static{background:#ebedf0}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}code{background:#eef3f5;overflow-wrap:anywhere}p{line-height:1.6}@media(max-width:650px){main{padding:20px 12px}.card{padding:16px}.stats{grid-template-columns:1fr 1fr}td,th{padding:10px;font-size:13px}}</style>
<main><span class="tag">Experimental evidence · 4 November 2026 · software only</span><h1>Operator timings + crowdsourced delays</h1><p class="muted">A frozen DMRC/NMRC baseline, 100 simulated accounts and the actual API, processing worker and journey WebSockets. This page replays saved test results offline.</p>
<section class="card stats"><div><strong>281 / 281</strong>source timing records match</div><div><strong>100</strong>concurrent journey clients</div><div><strong id="reports"></strong>synthetic reports processed</div><div><strong id="checks"></strong>client journey checks passed</div></section>
<section class="card"><h2>Replay the context and source changes</h2><p>Choose a phase to inspect the returned journey estimates. Origins advance by a script; these are not physical train positions. Each row represents 25 client updates.</p><div class="controls"><label for="phase">Phase</label><select id="phase"></select><button id="previous">Previous</button><button id="next">Next phase</button></div><div class="scroll"><table><thead><tr><th>Journey cohort</th><th>Context</th><th>Evidence</th><th>Operator sum</th><th>Crowd delay</th><th>Result</th></tr></thead><tbody id="summary"></tbody></table></div><p id="phase-note" class="muted"></p></section>
<section class="card"><h2>Figure 10</h2><img src="figure_10_operator_crowd.svg" alt="Four measured experiment panels: context source matrix, example journey durations, report outcomes, and latency distributions"><p class="muted">All values come from this combined run. Static values are indicative operator route travel times. No field arrival error or machine learning accuracy is claimed.</p><a href="figure_10_operator_crowd.pdf">Vector figure PDF</a> · <a href="figure_10_operator_crowd.png">600 dpi PNG</a></section>
<section class="card"><h2>Inspect all 100 client records for a phase</h2><label for="cohort">Journey cohort</label><select id="cohort"><option value="all">All cohorts</option></select><div class="scroll"><table><thead><tr><th>Simulated user</th><th>Cohort</th><th>Expected source</th><th>Actual source</th><th>Expected s</th><th>Actual s</th><th>Check</th></tr></thead><tbody id="details"></tbody></table></div></section>
<section class="card"><h2>Data and paper files</h2><p><a href="operator-baseline-segments.csv">Operator segment timing dataset CSV</a> · <a href="operator-stations.csv">Station dataset CSV</a> · <a href="operator-network-snapshot.json">Complete frozen network JSON</a></p><p><a href="crowd-reports.csv">Synthetic crowdsourcing dataset CSV</a> · <a href="simulated-participants.csv">100 participant profiles CSV</a> · <a href="journey-context-results.csv">All 500 journey checks CSV</a> · <a href="cohort-phase-summary.csv">20 distinct conditions CSV</a></p><p><a href="http-acknowledgements.csv">HTTP measurements CSV</a> · <a href="operator-provenance-audit.json">Source audit and review flags</a> · <a href="combined-results.json">Complete results JSON</a> · <a href="verification.json">Independent verification</a></p><p><a href="FindMyMetro_Combined_Test_Results.docx">Paper and panel report Word</a> · <a href="FindMyMetro_Combined_Test_Results.pdf">Report PDF</a> · <a href="research_results_section.md">Insertable research results text</a></p></section>
<section class="card"><h2>What the experiment establishes</h2><p>It checks the baseline plus accepted station delay, location validation, report freshness, duplicate delivery, source selection at configured boundaries and recovery after expiry. Underground falls back to static when verified phone evidence is absent. The current code can still accept qualified reports underground.</p><p>It does not measure actual train arrivals, individual live train tracking, cell-tower accuracy, browser performance or Prophet/Random Forest inference. There are 20 distinct fixture conditions and 500 repeated client deliveries, not 500 independent real-world trials.</p><p id="transport" class="muted"></p><p class="muted">NMRC coordinates are from a historical mirror; station-level zones and unusual operator timing values need review. The full provenance audit retains these limitations.</p></section></main>
<script>const D=__DATA__;const phase=document.getElementById('phase'),cohort=document.getElementById('cohort');const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));D.phases.forEach((p,i)=>phase.add(new Option(D.phase_labels[i],p)));D.cohorts.forEach(c=>cohort.add(new Option(c,c)));document.getElementById('reports').textContent=D.result.unique_report_deliveries;document.getElementById('checks').textContent=D.result.passed_journey_updates+' / '+D.result.expected_journey_updates;document.getElementById('transport').textContent='The initial run had two transport failures and stored 398 of 400 reports. It is preserved in attempts/initial-transport-failure. The completed run uses bounded retries with the same event IDs and recorded '+D.result.transport_errors_before_retry+' transport errors before retry. No API limits were relaxed.';function render(){const p=phase.value;document.getElementById('summary').innerHTML=D.unique.filter(r=>r.phase===p).map(r=>`<tr><td>${esc(r.cohort)}</td><td>${esc(r.actual_context)}</td><td><span class="pill ${r.actual_source==='schedule'?'static':''}">${r.actual_source==='schedule'?'Static baseline':'Crowd agreement'}</span></td><td>${r.baseline_seconds} s</td><td>+${r.actual_delay_seconds} s</td><td><b>${r.actual_journey_seconds} s</b></td></tr>`).join('');document.getElementById('phase-note').textContent=p==='evidence_expired'?'No new reports were sent. The test waited for real wall-clock expiry; all 100 clients returned to static timing.':'Freshness, independent-account agreement and location evidence determine whether a station delay can be added once.';document.getElementById('details').innerHTML=D.rows.filter(r=>r.phase===p&&(cohort.value==='all'||r.cohort===cohort.value)).map(r=>`<tr><td>${r.participant}</td><td>${esc(r.cohort)}</td><td>${r.expected_source}</td><td>${r.actual_source}</td><td>${r.expected_journey_seconds}</td><td>${r.actual_journey_seconds}</td><td>${r.passed?'PASS':'FAIL'}</td></tr>`).join('');}phase.onchange=cohort.onchange=render;document.getElementById('next').onclick=()=>{phase.selectedIndex=(phase.selectedIndex+1)%D.phases.length;render()};document.getElementById('previous').onclick=()=>{phase.selectedIndex=(phase.selectedIndex+D.phases.length-1)%D.phases.length;render()};render();</script></html>'''.replace('__DATA__',payload)
    page=page.replace('.scroll{overflow:auto}', '.scroll{overflow:auto}.scroll:has(#details){max-height:400px}')
    from operator_crowd_delay_view import augment_delay_reports
    page=augment_delay_reports(page,OUT)
    (OUT/'panel-demo.html').write_text(page,encoding='utf-8')
    readme=f'''# FindMyMetro combined operator and crowd experiment

Open `panel-demo.html` in a browser. It works offline and displays saved results, not a live passenger feed.

The Crowdsourced delay reports section includes recorded 6, 8 and 10 minute agreement examples, a filterable log of all 400 submitted reports and a delay-to-journey summary CSV. Filter by phase, worker outcome and operator. These are views of the completed experiment; no new passenger reports or measurements were created.

## What is real and what is synthetic

- Real source records: the frozen operator catalogue imported on 8 October 2026, with 281 segment records checked against 280 archived public responses.
- Synthetic: 100 accounts, coordinates used in submitted reports, delay values, report timing, and scripted query-origin progression.
- Measured: actual TCP requests to FastAPI, PostgreSQL worker outcomes and 100 concurrent journey WebSockets on Windows loopback.
- Not measured: real train arrivals, field ETA accuracy, native cell-tower matching, mobile radio, browser rendering or ML inference.

## Quick panel demonstration

1. Open `panel-demo.html`; show the initial operator baseline.
2. Select Boundary agreement; point out DMRC transition and the NMRC surface cohorts.
3. Select After boundary; show DMRC underground returning to static with no verified phone location.
4. Select Evidence expired; all 100 clients return to the static baseline without new reports.
5. Select Fresh recovery; surface estimates regain the crowd overlay.
6. Open the two CSV datasets, one archived source response and the 500 expected-versus-actual journey records.

## Reproduce against the complete local project

From the find_my_metro directory in PowerShell:

```powershell
..\\.venv\\Scripts\\python.exe scripts\\test_operator_crowd_100.py
..\\.venv\\Scripts\\python.exe scripts\\verify_operator_crowd.py
```

Requires the application's Python dependencies, configured PostgreSQL installation and source response archives in `.local/research/timings`. The application private `.env` is read only to create a separate random test database. It is never included in this pack. The runner binds 127.0.0.1:8021, creates 100 synthetic accounts, starts its own worker, uses normal rate limits and removes its own test database. Registration/auth load and hardened runtime-role permissions are outside the experiment. Archive this folder before rerunning to preserve this measured run.

Each run creates fresh timestamps. The exported reports preserve the original measured timestamps and will be historical if posted unchanged later.

## Evidence and interpretation

`operator-baseline-segments.csv` includes exact source values, public URLs, snapshot date and hashes. `operator-provenance-audit.json` flags unusually short/long values without silently correcting them. Walking times are estimates; NMRC coordinates are historical; station-level zones require platform review. The current app permits qualified crowd evidence underground; static fallback here occurs because location evidence is missing.

`crowd-reports.jsonl` and `.csv` join every injected report to the worker outcome. `journey-context-results.csv` contains 500 client records across 20 distinct cohort/phase conditions. `journey-snapshots.jsonl` retains one full snapshot per condition. `http-acknowledgements.csv` retains attempt counts and transport errors. `verification.json` recomputes source hashes, counts, arithmetic and latency quantiles from exported evidence.

The initial run is retained in `attempts/initial-transport-failure`: 398 reports were stored after two transport errors. The completed run uses event-ID-safe bounded retries. A successful retry is not counted as a new contributor or unique report. The completed run recorded {result['transport_errors_before_retry']} transport errors before retry.

The full experiment took {result['wall_seconds']:.2f} seconds excluding setup. All {len(result['acceptance'])} acceptance checks passed. These are software validation results, not a recruited 100-person field study or evidence of measured train ETA MAE. Previous synthetic ML results in `artifacts/paper-100-users` are a separate experiment and must stay separately labelled.
'''
    (OUT/'README.md').write_text(readme,encoding='utf-8')
    print('Created offline panel viewer, research section and four-page Word report.')


if __name__=='__main__':main()
