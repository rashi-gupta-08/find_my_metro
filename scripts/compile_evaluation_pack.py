"""Compile a local evaluation handover from measured evidence, without new trials."""
import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'artifacts/operator-crowd-100-users'
OUT=ROOT/'artifacts/evaluation-panel'
COMPILED_DATE='6 November 2026'


def read_json(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def csv_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def collect():
    result=read_json(EVIDENCE/'combined-results.json');audit=read_json(EVIDENCE/'operator-provenance-audit.json')
    assert all(result['acceptance'].values())
    assert read_json(EVIDENCE/'verification.json')['all_checks_passed']
    manifest=read_json(EVIDENCE/'evidence-manifest.json')
    bad=[r['path'] for r in manifest['files'] if not (EVIDENCE/r['path']).exists() or sha(EVIDENCE/r['path'])!=r['sha256']]
    if bad:raise ValueError('Original evidence changed: '+str(bad))
    raw=[json.loads(line) for line in (EVIDENCE/'crowd-reports.jsonl').read_text().splitlines()]
    assert len(raw)==400 and Counter(r['actual_processing'] for r in raw)==result['processing_outcomes']
    assert len(result['observations'])==500 and all(r['passed'] for r in result['observations'])
    return result,audit,raw


def important_metrics(result,audit):
    entries=[
        ('Catalogue stations',audit['stations'],'stations','Frozen operator catalogue; not a claim of complete current coverage','operator-provenance-audit.json'),
        ('Ordered line paths',audit['ordered_line_paths'],'paths','Branches may share a physical segment','operator-provenance-audit.json'),
        ('Operator segment values matched',audit['verified_against_archived_source'],'of 281','Source transcription audit, not measured train-arrival accuracy','operator-baseline-segments.csv'),
        ('Unique archived operator responses',audit['unique_source_responses'],'responses','One archived response can support more than one stored line path','operator-provenance-audit.json'),
        ('Unusual timing values requiring review',len(audit['review_flags']),'records','Two 2-second records and one 720-second record retained as supplied','operator-provenance-audit.json'),
        ('Simulated authenticated accounts',100,'accounts','No human commuters recruited; fixture provisioning precedes measurement','combined-results.json'),
        ('Concurrent journey WebSocket clients',100,'connections','One local API and worker using a fresh PostgreSQL test database','combined-results.json'),
        ('Distinct cohort and phase conditions',20,'conditions','Four cohorts across five phases','combined-results.json'),
        ('Journey updates matching expectations',500,'of 500','Repeated client deliveries across 20 conditions, not independent field trials','journey-context-results.csv'),
        ('Static baseline updates',250,'updates','Includes missing-location and expired-evidence fallback','journey-context-results.csv'),
        ('Crowd adjusted updates',250,'updates','Accepted station delay added once at boarding','journey-context-results.csv'),
        ('Unique submitted reports',400,'reports','Four reporting waves; expiry phase sends no reports','crowd-reports.jsonl'),
        ('Reports validated',150,'reports','Eligible for agreement, not operator-verified truth','crowd-reports.jsonl'),
        ('Historical uploads',50,'reports','45-second-old fixture uploads exceed the live lifetime','crowd-reports.jsonl'),
        ('Reports rejected',200,'reports','150 missing-location and 50 distant-GPS reports','crowd-reports.jsonl'),
        ('Natural expiry fallback',100,'of 100 clients','Fresh evidence expires after 30 seconds; all connections return to static','combined-results.json'),
        ('Duplicate retries recognized',3,'of 3','No additional stored observations','combined-results.json'),
        ('HTTP acknowledgement p95',round(result['http_ack_latency']['p95_ms']/1000,3),'seconds','400 report acknowledgements; not route GET latency','combined-results.json'),
        ('Worker processing p95',round(result['receipt_to_processing_latency']['p95_ms']/1000,3),'seconds','Receipt to recorded worker outcome, 400 reports','combined-results.json'),
        ('Journey update p95',round(result['observation_to_matching_journey_ws_latency']['p95_ms']/1000,3),'seconds','250 crowd updates; includes the harness worker-completion barrier','combined-results.json'),
        ('Maximum journey arithmetic residual',0,'seconds','Against injected-policy reference only; field ETA MAE unavailable','journey-context-results.csv'),
        ('Combined acceptance checks passed',len(result['acceptance']),'of 11','Recorded acceptance conditions for the completed run','combined-results.json')]
    return [{'metric':m,'value':v,'unit':u,'meaning':n,'evidence_file':s} for m,v,u,n,s in entries]


def architecture():
    # Local SVG, using only components active in the combined experiment.
    def box(x,y,w,h,title,lines,fill='#f4f7fa'):
        content=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{fill}" stroke="#8ca3b5"/>'
        content+=f'<text x="{x+18}" y="{y+31}" class="title">{html.escape(title)}</text>'
        for i,line in enumerate(lines):content+=f'<text x="{x+18}" y="{y+58+i*23}" class="body">{html.escape(line)}</text>'
        return content
    def arrow(points):return f'<polyline points="{points}" fill="none" stroke="#49667d" stroke-width="2.5" marker-end="url(#a)"/>'
    svg='''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="760" viewBox="0 0 1440 760"><defs><marker id="a" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9" fill="#49667d"/></marker></defs><style>text{font-family:Arial,sans-serif;fill:#17344b}.title{font-weight:700;font-size:22px}.body{font-size:18px}.note{font-size:17px;fill:#405a70}</style><rect width="1440" height="760" fill="white"/><text x="32" y="38" font-size="27" font-weight="700">FindMyMetro software architecture</text>'''
    svg+=box(32,80,348,116,'Operator baseline',['DMRC and NMRC archived times','Versioned stations and segments'])
    svg+=box(32,252,348,116,'Passenger web app',['React and TypeScript','Route queries and foreground reports'])
    svg+=box(438,252,348,116,'FastAPI gateway',['Sessions, CSRF and rate limits','Schema checks and durable receipt'])
    svg+=box(844,252,348,116,'PostgreSQL and worker',['Queued events and audit history','Location, age and agreement checks'])
    svg+=box(844,80,348,116,'Context and confirmed reports',['Configured zone at boarding','Static or qualified station delay'])
    svg+=box(438,80,348,116,'NetworkX journey planner',['Bounded route alternatives','Baseline plus boarding delay once'])
    svg+=box(438,430,348,116,'REST and journey WebSockets',['Versioned route snapshots','Source, age and delay information'])
    svg+=box(32,430,348,116,'Passenger result',['Duration and route suggestions','Alerts and clear freshness labels'])
    svg+=arrow('380,138 438,138')+arrow('844,138 786,138')
    svg+=arrow('380,310 438,310')+arrow('786,310 844,310')+arrow('1018,252 1018,196')
    svg+=arrow('612,252 612,196')+arrow('612,368 612,430')+arrow('438,488 380,488')
    svg+='<text x="813" y="476" class="note">Confirmed reports expire after 30 seconds.</text><text x="813" y="505" class="note">Missing usable evidence leaves static timing active.</text>'
    svg+='<rect x="32" y="604" width="1376" height="116" rx="12" fill="#f1f3f5"/><text x="52" y="638" class="title">Scope of the measured software run</text><text x="52" y="668" class="body">100 simulated accounts, operator travel-time snapshot, synthetic station delay reports and actual loopback API delivery.</text><text x="52" y="698" class="note">Hardware is disabled. ML training is separate. Individual train tracking and field arrival accuracy remain unmeasured.</text></svg>'
    (OUT/'software-architecture.svg').write_text(svg,encoding='utf-8')


def results_text(result,audit):
    return f'''# Results for the paper and evaluation

## Experimental setup

We evaluated the software on 4 November 2026 using 100 simulated authenticated accounts on one Windows computer. The baseline was the frozen DMRC/NMRC catalogue imported on 8 October 2026. The catalogue contains {audit['stations']} stations, {audit['ordered_line_paths']} ordered line paths and {audit['segment_records']} segment records. All 281 stored time values matched 280 archived public operator responses. This verifies transcription of indicative operator travel times. It does not validate current service coverage or actual train arrivals.

Four cohorts of 25 accounts represented a DMRC Blue Line query moving from underground to surface, the reverse direction, and two NMRC Aqua Line directions. Query origins advanced by script. Five phases covered initial static timing, qualified boundary reports, surface and underground source selection, natural evidence expiry, and fresh-report recovery. There were 20 distinct cohort/phase conditions and 500 repeated client journey updates. Four reporting waves each released 100 HTTP clients while 100 journey WebSocket clients were connected. The actual API and processing worker used a fresh PostgreSQL test database.

## Measured results

All 400 unique reports received durable acknowledgements. Processing produced 150 validated reports, 50 historical uploads and 200 rejections, matching the injected labels. The rejections comprised 150 missing-location reports and 50 reports outside station proximity. All 500 journey updates matched the expected configured context, source scope and duration arithmetic. There were 250 static and 250 crowd-adjusted updates. After reports expired, all 100 connections returned to static timing. Three explicit duplicate retries created no additional stored observations. All 11 combined acceptance checks passed.

HTTP acknowledgement p50/p95 was {result['http_ack_latency']['p50_ms']/1000:.3f}/{result['http_ack_latency']['p95_ms']/1000:.3f} seconds over 400 acknowledgements. Receipt-to-worker-outcome p50/p95 was {result['receipt_to_processing_latency']['p50_ms']/1000:.3f}/{result['receipt_to_processing_latency']['p95_ms']/1000:.3f} seconds over 400 reports. Observation-to-client-journey-read p50/p95 was {result['observation_to_matching_journey_ws_latency']['p50_ms']/1000:.3f}/{result['observation_to_matching_journey_ws_latency']['p95_ms']/1000:.3f} seconds over 250 crowd-adjusted updates. The latter includes a per-wave worker-completion barrier. These are descriptive results from one local workload, with correlated clients sharing four routes.

For a worked example, the stored Mandi House to Yamuna Bank baseline was 405 seconds. Fresh compatible reports established an injected 360-second extra wait. The returned journey duration was 765 seconds, or 12 minutes 45 seconds. Historical and rejected reports did not qualify for the live delay. The delay was counted once at boarding.

## Interpretation

The experiment validates the software composition of traceable indicative operator times and qualified station-delay evidence, including static fallback and recovery. The zero-second arithmetic residual refers to the known injected-policy reference, not train ETA MAE. Actual train arrival timestamps were unavailable, so field MAE, RMSE, tracking accuracy and commuter time savings are unmeasured. The current app permits qualified reports underground when location evidence exists. The underground fallback tested here reflects missing verified phone evidence. The boundary experiment does not evaluate the separate identified-train handover/dead-reckoning engine, native cell-tower positioning or Prophet/Random Forest inference.

The first run stored 398 reports after two transport ReadError failures. That evidence is retained in the full archive. The completed run used bounded retries with the same event ID, recorded zero transport errors, and preserved normal API limits. A future pilot needs consented commuter reports, reviewed station/platform context and independently timestamped train arrivals before claiming field ETA improvement.

## Figure to use

Use `figure_10_operator_crowd.pdf` or the 600 dpi PNG from this pack. Its panels show source/context selection, baseline versus crowd-adjusted durations, report outcomes and measured latency. The earlier synthetic ML model comparison is a separate experiment and must retain its own methods and label.
'''


def build_source_archive():
    files=[]
    for folder in ['backend','frontend','scripts','mobile']:
        for p in (ROOT/folder).rglob('*'):
            if not p.is_file():continue
            relative=p.relative_to(ROOT)
            if any(part in {'node_modules','dist','build','.dart_tool','.gradle','.idea','__pycache__','.git','.venv'} for part in relative.parts):continue
            if p.suffix.lower() not in {'.py','.txt','.json','.ts','.tsx','.css','.html','.svg','.mjs','.cjs','.ps1','.dart','.kt','.kts','.yaml','.yml','.xml','.properties','.sh','.webmanifest','.lock','.md'} and p.name not in {'Dockerfile','gradlew','gradlew.bat'}:continue
            if p.name in {'local.properties','key.properties','google-services.json'} or 'tsbuildinfo' in p.name:continue
            if p.name.endswith('.env') or p.suffix in {'.jks','.keystore','.db','.log'}:continue
            files.append(p)
    for name in ['data/operator-network.json','.env.example','.gitignore','.dockerignore','README.md','LICENSE','alembic.ini',
                 'compose.yaml','compose.production.yaml','hardware/postgres-init.sh','hardware/nginx.conf','SOFTWARE_RUN.md','SOFTWARE_COMPLETE.md',
                 'BACKEND_INTEGRATION.md','docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md']:
        if (ROOT/name).is_file():files.append(ROOT/name)
    # Public beta fixtures support the included backend tests.
    for p in (ROOT/'data/beta/crowdsourcing').glob('*'):
        if p.is_file() and p.suffix in {'.json','.csv','.md'}:files.append(p)
    files=sorted(set(files))
    records=[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]
    (OUT/'project-source-manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    readme='''# FindMyMetro software source for evaluation

This is a source review archive, with React/TypeScript web code, FastAPI/Python backend, PostgreSQL migrations, tests, public operator catalogue, reproduction scripts and optional Flutter/Android source. Generated builds, installed dependencies, accounts, report databases, .env secrets and session cookies are excluded. Hardware is disabled. Two files under the legacy hardware directory provide database-role/container setup, not station sensors.

On the original development computer, run scripts/start.ps1 from the original project folder to start the passenger web app at http://localhost:5173. It uses the existing private configuration. Do not overwrite that .env with .env.example.

On another computer, install Node, Python and the required database/container tools, create new private configuration from .env.example and follow the repository startup documentation. This archive is not an installed executable or a credentialed copy of the workstation. Optional Android builds require a configured Android SDK and device.

The evaluation pack contains the frozen test inputs and measured results. Running test_operator_crowd_100.py requires the full local configuration and cached public timing responses. Never replay generated reports against the passenger database. Dates in the completed experiment are preserved, so unchanged reports will be historical if reposted later.

The active passenger app uses indicative operator timing plus qualified community station delays. Legacy identified-trip and hardware adapters remain in backend source for regression history and are disabled in the passenger profile. Prophet/Random Forest candidate research is separate from the measured combined report workload.
'''
    archive=OUT/'FindMyMetro_Project_Source.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for p in files:z.write(p,'find_my_metro/'+p.relative_to(ROOT).as_posix())
        z.writestr('READ_PROJECT_FIRST.md',readme)
        z.writestr('source-manifest.json',json.dumps(records,indent=2))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    return records


def prepare():
    OUT.mkdir(parents=True,exist_ok=True);result,audit,raw=collect()
    metrics=important_metrics(result,audit)
    write_csv(OUT/'important-results.csv',metrics)
    (OUT/'results_for_paper.md').write_text(results_text(result,audit),encoding='utf-8')
    original=OUT/'recorded-demo';original.mkdir(exist_ok=True)
    for p in EVIDENCE.iterdir():
        if p.is_file() and p.suffix in {'.html','.json','.jsonl','.csv','.svg','.png','.pdf','.txt','.md','.docx'}:
            if p.name in {'evidence-manifest.json','source-code-fingerprints.json'}:continue
            shutil.copy2(p,original/p.name)
    for folder in ['operator-source-responses','attempts']:
        shutil.copytree(EVIDENCE/folder,original/folder,dirs_exist_ok=True)
    shutil.copy2(EVIDENCE/'FindMyMetro_Operator_Crowd_100_User_Evidence.zip',OUT/'Full_100_User_Evidence.zip')
    architecture()
    dataset={'result':result,'audit':audit,'reports':raw,'baseline':csv_rows(EVIDENCE/'operator-baseline-segments.csv'),
        'metrics':metrics,'compiled_date':COMPILED_DATE}
    (OUT/'workbook-data.json').write_text(json.dumps(dataset,ensure_ascii=False),encoding='utf-8')
    records=build_source_archive()
    (OUT/'compilation-verification.json').write_text(json.dumps({'compiled_for_date':'2026-11-06','measured_run_date':'2026-11-04',
        'source_evidence_manifest_matches':True,'input_files_verified':len(read_json(EVIDENCE/'evidence-manifest.json')['files']),
        'all_recorded_acceptance_pass':True,'project_source_files':len(records),'no_new_trial_claimed':True},indent=2)+'\n')
    make_index(result,audit,metrics)
    make_markdown(result,audit)
    print('Prepared evaluation landing page, results, datasets, architecture and project source archive.')


def make_index(result,audit,metrics):
    cells=''.join(f'<tr><td>{html.escape(r["metric"])}</td><td><b>{r["value"]} {html.escape(r["unit"])}</b></td><td>{html.escape(r["meaning"])}</td></tr>' for r in metrics)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FindMyMetro evaluation panel pack</title><style>
*{box-sizing:border-box}body{margin:0;background:#f0f5f8;color:#17344b;font:16px system-ui;line-height:1.6}main{max-width:1160px;margin:auto;padding:40px 22px}h1{font-size:clamp(29px,5vw,46px);line-height:1.15;margin:14px 0}h2{font-size:24px}h3{font-size:18px}a{color:#07687b}.card{background:white;border:1px solid #d3e0e9;border-radius:15px;padding:24px;margin:22px 0}.muted{color:#526a7d}.badge{font-size:13px;background:#dbeaf0;border-radius:20px;padding:6px 12px;display:inline-block}.buttons{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0}.button{display:inline-block;background:#13364b;color:white;padding:12px 18px;border-radius:9px;text-decoration:none}.secondary{background:white;color:#13364b;border:1px solid #9bb4c5}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.stats b{font-size:30px;display:block}.stats div{border-left:3px solid #168087;padding-left:15px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px;text-align:left;border-bottom:1px solid #dce5ec;vertical-align:top}th{background:#edf4f7}td:first-child{min-width:185px}img{width:100%;height:auto}li{margin:10px 0}code{background:#eef3f6;padding:3px 5px;overflow-wrap:anywhere}.files{display:grid;grid-template-columns:1fr 1fr;gap:14px}.files a{display:block}details{margin:12px 0;padding:14px;border:1px solid #dce5ec;border-radius:9px}summary{cursor:pointer;font-weight:650}@media(max-width:650px){main{padding:22px 12px}.card{padding:16px}.stats{grid-template-columns:1fr 1fr}.files{grid-template-columns:1fr}td{min-width:160px}}
</style><main><span class="badge">Evaluation handover compiled 6 November 2026</span><h1>FindMyMetro project and results</h1><p class="muted">A route-planning web application that combines stored DMRC/NMRC indicative travel times with qualified crowdsourced station-delay reports. The recorded experiment ran on 4 November 2026.</p>
<div class="buttons"><a class="button" href="recorded-demo/panel-demo.html">Open recorded 100-account demonstration</a><a class="button secondary" href="FindMyMetro_Evaluation_Guide.pdf">Read evaluation guide PDF</a><a class="button secondary" href="FindMyMetro_Evaluation_Data.xlsx">Open results workbook</a></div>
<section class="card stats"><div><b>281 / 281</b>operator timing records match sources</div><div><b>100</b>simulated concurrent journey clients</div><div><b>400</b>report outcomes match injected labels</div><div><b>500 / 500</b>journey update checks pass</div></section>
<section class="card"><h2>What to show your panel</h2><ol><li><b>Explain the passenger problem.</b> Stored route times help plan a journey, but they do not show a newly reported station delay. Usable phone evidence may also be absent underground.</li><li><b>Show the web project.</b> Select source and destination and compare fastest, fewest-change, least-walking and shortest-distance suggestions. The search returns bounded alternatives.</li><li><b>Trace one operator timing record.</b> Open the baseline CSV and its archived source in the full evidence pack. Explain that DMRC times vary by segment, while all 20 stored Aqua segments are two minutes.</li><li><b>Demonstrate a delay.</b> Use the Mandi House example: 405 seconds of baseline plus a 360-second accepted extra wait produces 765 seconds.</li><li><b>Replay source selection and expiry.</b> Show the DMRC underground/surface boundary in both directions and NMRC surface journeys. All 100 clients return to static timing when evidence expires.</li><li><b>Present measured results.</b> Use the table below and Figure 10. Describe 100 simulated accounts, 20 distinct fixture conditions and 500 repeated client deliveries.</li><li><b>Explain the next research step.</b> Actual train timestamps are needed to evaluate field ETA MAE/RMSE and commuter benefit.</li></ol></section>
<section class="card"><h2>Current software architecture</h2><img src="software-architecture.svg" alt="React web app and operator catalogue connect through FastAPI, PostgreSQL validation worker and NetworkX route planner to versioned REST and WebSocket outputs"><p>The static operator sum remains available in every geographic context. Valid reports establish short-lived station-service evidence. The current code permits qualified reports underground when verified location evidence exists.</p></section>
<section class="card"><h2>Important measured results</h2><p class="muted">Frozen catalogue imported 8 October 2026. Measured workload 4 November 2026. p95 means 95% of observations were at or below the reported latency in this run.</p><div class="scroll"><table><thead><tr><th>Metric</th><th>Result</th><th>Interpretation</th></tr></thead><tbody>__METRICS__</tbody></table></div><p><a href="important-results.csv">Download key results CSV</a> · <a href="results_for_paper.md">Open research results text</a></p></section>
<section class="card"><h2>Delay report example</h2><div class="scroll"><table><thead><tr><th>Recorded example</th><th>Operator baseline</th><th>Accepted delay</th><th>Returned duration</th></tr></thead><tbody><tr><td>Mandi House to Yamuna Bank</td><td>6 min 45 s</td><td>6 min</td><td>12 min 45 s</td></tr><tr><td>Supreme Court to Yamuna Bank</td><td>4 min 48 s</td><td>8 min</td><td>12 min 48 s</td></tr><tr><td>NMRC Sector 51 to Sector 101</td><td>6 min</td><td>10 min</td><td>16 min</td></tr></tbody></table></div><p>Examples are synthetic. The group median establishes an extra boarding wait. Three distinct accounts are the minimum, reports must be younger than 30 seconds, and compatible delay values must fit a 60-second band.</p><a href="recorded-demo/panel-demo.html#delay-reports">Inspect validated, historical and rejected reports</a></section>
<section class="card"><h2>Figure 10 for the result section</h2><img src="recorded-demo/figure_10_operator_crowd.svg" alt="Measured source selection, journey duration, report processing and latency results"><p><a href="recorded-demo/figure_10_operator_crowd.pdf">Vector PDF</a> · <a href="recorded-demo/figure_10_operator_crowd.png">600 dpi PNG</a> · <a href="recorded-demo/figure_10_caption.txt">Figure caption</a></p></section>
<section class="card"><h2>Project and evidence files</h2><div class="files"><div><h3>Presentation and project</h3><a href="FindMyMetro_Evaluation_Guide.pdf">Six-page presentation and viva guide PDF</a><a href="FindMyMetro_Evaluation_Guide.docx">Editable guide Word</a><a href="FindMyMetro_Evaluation_Data.xlsx">Results and datasets workbook</a><a href="presentation_outline.md">Eleven-slide presentation outline</a><a href="FindMyMetro_Project_Source.zip">Clean project source ZIP</a></div><div><h3>Original test evidence</h3><a href="recorded-demo/operator-baseline-segments.csv">281 operator timing records CSV</a><a href="recorded-demo/crowd-reports.csv">400 synthetic reports CSV</a><a href="recorded-demo/journey-context-results.csv">500 expected versus actual updates CSV</a><a href="recorded-demo/cohort-phase-summary.csv">20 distinct conditions CSV</a><a href="Full_100_User_Evidence.zip">Full test evidence and archived sources ZIP</a></div></div></section>
<section class="card"><h2>Likely viva questions</h2>
<details><summary>What is the main contribution?</summary><p>We combine traceable indicative operator timings with validated community station-delay evidence, keep static estimates available when evidence is missing or stale, and expose the active source and data age.</p></details>
<details><summary>Did 100 real people test this?</summary><p>No human participants were recruited. The workload used 100 simulated authenticated accounts and 100 concurrent journey WebSockets on one computer.</p></details>
<details><summary>Is a zero arithmetic error a zero ETA error?</summary><p>The software matched the injected baseline-plus-delay rule. Actual train arrivals were unavailable, so field ETA MAE and RMSE are unmeasured.</p></details>
<details><summary>What happens underground?</summary><p>The configured route zone identifies underground sections. Without verified phone location evidence, static timing remains active. Current code can accept a qualified report underground, and the field cell-fingerprint map remains empty.</p></details>
<details><summary>Which models produced these results?</summary><p>The measured passenger run used static operator timings and a qualified crowd-delay overlay. Prophet and Random Forest are separate research candidates and were not invoked in this workload.</p></details>
<details><summary>What data still needs review?</summary><p>The operator audit flags two 2-second segment records and one 720-second record. The catalogue is a frozen snapshot, station-level zones need platform-specific checks, and walking distances and transfer times are estimates.</p></details>
</section><section class="card"><h2>Run on the development computer</h2><p>From the original project folder, run <code>.\\scripts\\start.ps1</code>, then open <a href="http://localhost:5173/">localhost:5173</a>. Existing services and private configuration should be preserved. The offline recorded demonstration works without the backend.</p><p>For a fresh test, archive the existing results first and run <code>..\\.venv\\Scripts\\python.exe scripts\\test_operator_crowd_100.py</code>. It creates fresh timestamps and its own test database. Unchanged November 4 reports would now be historical.</p><p class="muted">The clean source archive excludes installed dependencies, .env credentials, personal accounts and databases. A new machine requires its own setup. Nothing in this handover claims a public production launch or actual live train positioning.</p></section></main></html>'''.replace('__METRICS__',cells)
    page=page.replace('<a href="FindMyMetro_Project_Source.zip">Clean project source ZIP</a>',
        '<a href="FindMyMetro_Project_Source.zip">Clean project source ZIP</a><a href="technology_and_code_map.md">Technology choices and code map</a>')
    (OUT/'START_HERE.html').write_text(page,encoding='utf-8')


def make_markdown(result,audit):
    outline=[('Project and problem','FindMyMetro uses indicative operator route times and qualified station-delay reports. Explain why a static journey estimate alone misses a newly reported extra wait.'),
        ('Current system and limitations','Operator journey planners supply the baseline. Phone evidence can be missing or stale. The current project does not have an identified real-train location feed.'),
        ('Software solution','Select stations and preference, generate bounded routes, qualify reports, add accepted delay once at boarding, show source/age, and fall back on expiry.'),
        ('Requirements and measurable rules','Show three-account quorum, 30-second lifetime, 250 m station proximity and 60-second delay spread. These are implemented configuration choices.'),
        ('Architecture and technology','Use software-architecture.svg. React/TypeScript, FastAPI/Python, Pydantic, SQLAlchemy/Alembic, PostgreSQL, NetworkX and REST/WebSockets are active.'),
        ('Data provenance','265 stations, 14 ordered paths, 281 segment records checked against 280 archived responses. Explain indicative timing, estimated walking and flagged source values.'),
        ('Context and crowd validation','Demonstrate underground baseline without usable evidence, boundary qualification, surface crowd delay and expiry. Accurate crowd reports are permitted in any configured zone.'),
        ('Worked delay example','Mandi House to Yamuna Bank: 405 s baseline + 360 s accepted delay = 765 s. Show the underlying report validation outcomes.'),
        ('Experiment design','100 simulated accounts, four 25-account cohorts, five phases, 20 distinct conditions, four reporting waves, PostgreSQL and real loopback HTTP/WebSockets.'),
        ('Results and Figure 10','400 report outcomes match labels, 500/500 journey checks, 100/100 expiry fallback. HTTP p95 1.531 s and crowd journey read p95 4.548 s in one local run.'),
        ('Conclusion and future validation','The software composes traceable static timings and qualified delays. Field ETA accuracy, individual train positioning and trained production ML remain unevaluated. Collect consented reports and independent train arrival timestamps next.')]
    text='# Eleven slide presentation outline\n\nUse the first nine slides for the design story and demonstration, then present measured results and limitations. Suggested total: 8 to 10 minutes.\n\n'
    for i,(title,body) in enumerate(outline,1):text+=f'## Slide {i} {title}\n\n{body}\n\n'
    text+='## Closing explanation\n\nOur problem is that indicative route times do not include a newly reported metro station delay, and usable phone evidence can disappear underground. We use stored DMRC/NMRC segment timings as the baseline, validate community reports and add the accepted boarding delay once. React provides the web interface, FastAPI and PostgreSQL handle reliable reports, NetworkX compares routes, and WebSockets distribute source-labelled updates. The completed experiment used 100 simulated accounts and checked software behavior, while actual train ETA accuracy remains a field-evaluation task.\n'
    (OUT/'presentation_outline.md').write_text(text,encoding='utf-8')
    (OUT/'README.md').write_text('''# FindMyMetro evaluation handover

Start with START_HERE.html. Read the evaluation guide, use the results workbook and open recorded-demo/panel-demo.html to show the measured experiment without a backend. Full_100_User_Evidence.zip retains the archived operator responses, original reports, initial failed run and reproduction code. FindMyMetro_Project_Source.zip is a clean source review archive. The original working project stays in its existing location with private configuration intact.

Compiled for 6 November 2026 from the completed 4 November 2026 combined experiment. No new 100-user trial was performed for this compilation. The operator snapshot is dated 8 October 2026. Report timestamps are retained as research evidence and must not be presented as current passenger reports.

The key results are 281/281 timing transcriptions matched, 100 simulated concurrent journey clients, 400 worker outcomes matching injected labels, 500/500 checked client journey updates across 20 distinct conditions, and 100/100 static fallbacks after expiry. Field arrival accuracy is unmeasured. The implemented passenger source selection is qualified station-service evidence, not a phone-created individual train track.

The workbook preserves source data and calculates counts and duration residuals. It is an evidence snapshot, not a new model-training or accuracy experiment. Source code and evidence checksums are in the manifests. No passwords, private .env file, passenger database or session tokens are included.
''',encoding='utf-8')
    (OUT/'technology_and_code_map.md').write_text('''# Technology choices and implementation evidence

| Active technology | Problem it solves | Why it fits this project | Alternative and tradeoff | Main implementation |
|---|---|---|---|---|
| React and TypeScript | Source/destination selection, route comparison and reporting | Reuses the web interface and gives typed client contracts | A native-only client would need separate platform builds | frontend/src/App.tsx, JourneyResults.tsx, SurfaceReportDialog.tsx |
| FastAPI and Pydantic | HTTP/WebSocket handling and input contracts | Keeps acquisition, rules and route calculations in the Python application | Other web frameworks can serve the same contracts but would need a different integration | backend/app/main.py, surface_reports.py |
| PostgreSQL | Durable observations, account sessions, outcomes and audit history | Supports the worker's transaction and advisory-lock design | SQLite is useful in isolated functional tests; the combined 100-account run used PostgreSQL | backend/app/models.py, db.py, worker.py |
| SQLAlchemy and Alembic | Structured data access and schema changes | Separates database models from repeatable migration history | Ad hoc SQL/schema edits make upgrades harder to reproduce | backend/app/models.py, backend/migrations |
| NetworkX | Multi-objective comparisons over the stored metro graph | Uses the project's own station topology and weighted ride/transfer edges | An external directions API would introduce another network and data dependency | backend/app/journey_planner.py |
| REST and WebSockets | Initial retrieval and connected journey updates | REST and the socket share the versioned snapshot contract | Polling alone would repeatedly fetch unchanged results | backend/app/main.py journey_snapshot and /ws/journeys |
| Foreground browser location | Evidence that a report was submitted near its claimed station | Works with the existing web report form and explicit location permission | Continuous background tracking needs a different consent and mobile execution design | frontend/src/useSurfaceReports.ts, backend/app/surface_reports.py |

## Software boundaries to explain

The current passenger planner takes configured zone context and qualified station-service delay signals. It does not treat a raw phone position as an identified train. Unconfirmed, rejected and expired reports cannot add a live delay. A route's boarding delay is added once.

The legacy identified-trip engines remain in backend/app/engines.py and the separate software-validation feed. Their WSN names and handover tests do not mean hardware was connected in the combined operator/crowd experiment. Hardware is disabled for the passenger profile.

Prophet and scikit-learn Random Forest are separate candidate-model work. Redis, Kafka, Firebase background delivery and a reviewed field cell-fingerprint dataset were not used by the measured combined run. The clean project archive retains optional Flutter/Android source, but this handover focuses on the web app.
''',encoding='utf-8')


def document():
    from docx import Document
    from docx.shared import Inches,Pt,RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    result,audit,_=collect()
    doc=Document();section=doc.sections[0]
    section.page_width=Inches(8.27);section.page_height=Inches(11.69)
    section.top_margin=section.bottom_margin=Inches(.65);section.left_margin=section.right_margin=Inches(.7)
    for name in ['Normal','Title','Subtitle','Heading 1','Heading 2']:
        style=doc.styles[name];style.font.name='Calibri';style.font.color.rgb=RGBColor(0,0,0)
    doc.styles['Normal'].font.size=Pt(10.5);doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    doc.styles['Normal'].paragraph_format.line_spacing=1.05
    doc.styles['Title'].font.size=Pt(23);doc.styles['Heading 1'].font.size=Pt(15)
    doc.styles['Heading 1'].paragraph_format.space_before=Pt(9)
    doc.styles['Heading 2'].font.size=Pt(11.5)
    footer=section.footer.paragraphs[0];footer.alignment=2
    footer.add_run('FindMyMetro evaluation  |  6 November 2026  |  ')
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    def p(text,style=None):return doc.add_paragraph(text,style)
    def h(text):doc.add_heading(text,1)
    def sub(text):doc.add_heading(text,2)
    def table(data,widths):
        t=doc.add_table(rows=1,cols=len(data[0]));t.style='Table Grid';t.autofit=False
        for i,w in enumerate(widths):t.columns[i].width=Inches(w)
        for i,c in enumerate(t.rows[0].cells):c.text=data[0][i]
        for row in data[1:]:
            for cell,value in zip(t.add_row().cells,row):cell.text=str(value)
        for j,row in enumerate(t.rows):
            row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
            for i,cell in enumerate(row.cells):
                cell.width=Inches(widths[i])
                for para in cell.paragraphs:
                    para.paragraph_format.space_after=Pt(4);para.paragraph_format.space_before=Pt(2)
                    for run in para.runs:run.font.size=Pt(9.5);run.font.color.rgb=RGBColor(0,0,0);run.bold=j==0
                if j==0:
                    shd=OxmlElement('w:shd');shd.set(qn('w:fill'),'EEEEEE');cell._tc.get_or_add_tcPr().append(shd)
        p('')
    p('FindMyMetro evaluation guide', 'Title')
    p('Project explanation, demonstration sequence and measured results', 'Subtitle')
    p('Compiled 6 November 2026. Recorded experiment 4 November 2026. Operator snapshot 8 October 2026.')
    h('What the project solves')
    p('A passenger can plan a metro journey using operator travel-time estimates, but those estimates do not include a newly reported station delay. FindMyMetro adds qualified community delay evidence while retaining the static baseline when usable phone evidence is absent or expires.')
    h('The contribution to present')
    p('Show a software-only route planner that combines traceable DMRC/NMRC segment times with validated station-service reports. Explain the source decision and freshness label alongside the journey estimate. No station hardware is required for this demonstration.')
    table([['Implemented capability','What to demonstrate'],['Journey suggestions','Source/destination and fastest, fewest interchanges, least walking or shortest distance preferences. Search returns bounded alternatives.'],['Crowdsourced delays','Authenticated reports, proximity/freshness checks, distinct-account agreement and private processing outcomes.'],['Context and continuity','Configured underground, boundary and surface sections. Static timing remains available without usable evidence.'],['Passenger output','Journey duration, delay/source labels, age and versioned REST/WebSocket updates.']], [2.05,4.82])
    h('Technologies active in this experiment')
    table([['Technology','Purpose'],['React and TypeScript','Web station selection, route results, report forms and source labels.'],['FastAPI and Pydantic','HTTP/WebSocket endpoints, sessions and validated request contracts.'],['SQLAlchemy and Alembic','Durable database access and versioned schema migrations.'],['PostgreSQL and Python worker','Store reports, validate queued events and retain processing outcomes.'],['NetworkX and REST/WebSockets','Compare valid network routes and distribute updated snapshots.']], [2.05,4.82])
    p('Prophet and Random Forest remain separate research candidates. The combined 100-account run used static timing plus qualified community delay overlays. Redis and Kafka were not active dependencies.')
    doc.add_page_break()
    h('How the software components interact')
    doc.add_picture(str(OUT/'software-architecture.png'),width=Inches(6.87))
    p('The operator catalogue supplies the network and baseline seconds. A report passes through the API, durable storage and worker checks. The planner uses a qualified station-delay group at the boarding point and publishes a source-labelled result.')
    h('Source selection in the three geographic contexts')
    table([['Context','Current implemented behavior'],['Underground','Keep operator timings when no verified location evidence is available. A qualified accurately located report may still add a short-lived delay.'],['Transition boundary','Use configured segment geography and report qualification. The combined run does not measure individual-train handover or dead reckoning.'],['Surface','Use fresh compatible station reports after at least three distinct accounts agree. Otherwise retain the static baseline.']], [1.5,5.37])
    h('Rules that make the result reviewable')
    p('A live report must be younger than 30 seconds. The current GPS check requires an accuracy value no worse than 100 m and a submitted position within 250 m of the station. At least three distinct active accounts must agree on station, ordered line, direction and report type, with delay values within a 60-second band. Repeated reports from one account do not add confirmations.')
    p('The 120-second collection setting does not extend the 30-second live lifetime. A fresh group can qualify a delay; a validated individual report alone does not. Crowd delay affects boarding wait once and does not create an identified train.')
    p('Returned journey duration = sum of the returned route segment times + estimated transfer time where present + accepted boarding delay once per boarding. This is an indicative duration. Dated next-train departures, station access and security time are not supplied by the baseline.')
    doc.add_page_break()
    h('Datasets and experimental design')
    table([['Data or workload','Count and meaning'],['Operator catalogue','265 stations, 14 ordered paths and 281 segment records.'],['Timing provenance','261 DMRC and 20 NMRC segment records matched 280 unique archived public responses.'],['Crowd reports','400 synthetic reports from 100 simulated authenticated accounts.'],['Cohorts','Four groups of 25: DMRC underground to surface, reverse boundary direction, NMRC outbound and inbound.'],['Conditions and deliveries','Five phases produce 20 distinct cohort/phase conditions and 500 repeated client journey checks.'],['Execution','Actual local API and worker, PostgreSQL 16, four 100-client HTTP waves and 100 concurrent journey WebSockets.']], [2.0,4.87])
    p('The static catalogue is a frozen operator snapshot. DMRC times vary by segment. All 20 stored NMRC adjacent-segment times are 120 seconds. Walking and transfer values are application estimates. NMRC coordinates use a historical mirror, and station-level zones need platform-specific review.')
    h('Five phases to explain')
    table([['Phase','DMRC underground to surface','DMRC surface to underground','NMRC both directions'],['Initial','Underground / static','Surface / static','Surface / static'],['Boundary agreement','Transition / crowd','Transition / crowd','Surface / crowd'],['After boundary','Surface / crowd','Underground / static','Surface / crowd'],['Evidence expired','Surface / static','Underground / static','Surface / static'],['Fresh recovery','Surface / crowd','Underground / static','Surface / crowd']], [1.42,1.9,1.9,1.65])
    p('Origins advance by a script rather than observed train movement. Missing-location phases withhold location evidence. Eligible groups receive nearby GPS fixtures, stale uploads and distant GPS reports so the worker must distinguish usable from unusable evidence. The expiry phase sends no reports and waits on real wall-clock time.')
    sub('Operator values retained for review')
    p('The source audit flags Majlis Park to Burari at 2 seconds, Madhuban Chowk to Prashant Vihar at 2 seconds, and Janakpuri West to Krishna Park Extension at 720 seconds. They match the archived source values and remain flagged for operator review. They are outside the selected Blue/Aqua workload routes.')
    doc.add_page_break()
    h('Important measured results')
    table([['Result','Observed value'],['Timing transcription audit','281 / 281 segment records match archived sources.'],['Unique reports and outcomes','400 reports: 150 validated, 50 historical, 200 rejected.'],['Rejected-report breakdown','150 missing-location reports and 50 distant GPS reports.'],['Journey checks','500 / 500 match expected source, context and arithmetic across 20 distinct conditions.'],['Static and crowd-adjusted updates','250 static and 250 crowd-adjusted deliveries.'],['Expiry and duplicate handling','100 / 100 clients return to static. All 3 duplicate retries create no additional stored observations.'],['Acceptance gates','All 11 recorded combined acceptance conditions pass.']], [2.25,4.62])
    table([['Measured interval','Samples','p50 seconds','p95 seconds'],['HTTP report acknowledgement',400,'0.929','1.531'],['Receipt to worker outcome',400,'0.523','0.988'],['Observation to client journey read',250,'2.468','4.548']], [3.15,.8,1.46,1.46])
    p('These are descriptive single-run Windows loopback latencies. Journey-read latency includes the harness worker-completion barrier. HTTP acknowledgement is a report POST measurement, not the separate route GET p95 target or browser rendering time.')
    h('Worked result to explain aloud')
    p('For Mandi House to Yamuna Bank, the stored route baseline was 405 seconds. The fixture established a fresh agreed extra wait of 360 seconds. The returned duration was 765 seconds, or 12 minutes 45 seconds. Adding the delay at boarding once prevents it from being charged at every station.')
    sub('Paper ready result paragraph')
    p('In a controlled software evaluation with 100 simulated accounts, 400 report outcomes matched injected validity labels and all 500 checked journey updates matched expected source, configured context and duration arithmetic across 20 distinct conditions. All 100 connections returned to the static baseline after report expiry. The p95 report acknowledgement and crowd observation-to-journey-read latencies were 1.531 s and 4.548 s respectively in one PostgreSQL loopback run. These results validate implemented software behavior. Field ETA MAE and RMSE remain unmeasured because no independent actual-train arrival ground truth was available.')
    p('The earlier initial run lost two report requests to transport errors and stored 398 reports. That run remains in the full evidence archive. The completed run used bounded same-event-ID retry support and recorded zero transport errors. Normal API rate limits remained active.')
    doc.add_page_break()
    h('What to show during the evaluation')
    table([['Time','Action and explanation'],['0 to 1 min','State the passenger problem and the contribution. Show the software architecture.'],['1 to 2 min','Show source/destination selection in the local web app and route preferences. Use the recorded pack if the backend is unavailable.'],['2 to 3 min','Trace one baseline CSV row to an archived operator response. Explain indicative timing and snapshot date.'],['3 to 4 min','Open the recorded delay examples. Show nearby valid reports, a historical upload and a rejected distant location. Explain 405 + 360 = 765 seconds.'],['4 to 5 min','Replay boundary, after-boundary, expiry and recovery phases. Show both DMRC directions and the NMRC surface case.'],['5 to 6 min','Present Figure 10 and the workbook summary. Separate 20 distinct conditions from 500 repeated client deliveries.'],['6 to 7 min','Close with the measured conclusion and the field-data gap. Take questions.']], [.9,5.97])
    h('How to address the evaluation rubric')
    table([['Rubric component','Evidence to show'],['Functional specifications 6 marks','Quantified validation rules, 20 condition table and expected-versus-actual journey records.'],['Framework and SDLC choice 6 marks','Modular pipeline and evidence-led iterations: catalogue audit, rule validation, integration workload and recovery checks. Describe this workflow without inventing a formal Scrum history.'],['Design tools 6 marks','Architecture diagram, API contracts, schema/migrations, versioned source and recorded browser checks.'],['Appropriateness of design 6 marks','Separate observation and receipt times, durable event IDs, worker processing and explicit static fallback.'],['Design and functionality alignment 6 marks','Connect each diagram component to its module and the report or journey evidence it produces.'],['Oral and written communication 10 marks','Use the seven-minute sequence, six-page guide, Figure 10 and a concise result paragraph.'],['Guide assessment 10 marks','Explain implementation choices, limitations, original evidence and the next field-validation step.']], [2.25,4.62])
    p('The rubric is an evidence checklist, not a prediction of marks. Keep old hardware diagrams and unrelated model experiments out of the main software demonstration.')
    doc.add_page_break()
    h('Viva answers and files to keep ready')
    questions=[('What is the innovation?','A traceable operator baseline plus qualified station-service delay evidence, explicit source/freshness and static fallback. Novelty over published work still requires a literature comparison.'),
        ('Was this tested by 100 people?','No human participants were recruited. We used 100 simulated authenticated accounts on one computer, with real local requests, worker processing and WebSocket delivery.'),
        ('Does 500 out of 500 mean perfect ETA accuracy?','It means the outputs matched the fixture policy and duration arithmetic. Actual train arrival times were unavailable, so real ETA error was not measured.'),
        ('How do you predict underground?','Use the configured zone and stored segment times. Missing verified phone evidence leaves static timing active. Qualified underground reports remain allowed by current code.'),
        ('What about cell towers and ML?','The Android collection path and candidate models are separate work. There is no supplied reviewed field cell map, and this workload did not invoke Prophet or Random Forest.'),
        ('What happens if people disagree?','Only a compatible group of distinct accounts can establish a delay. Invalid, stale and unconfirmed evidence cannot add a live journey delay. Accounts do not prove unique people or defeat collusion.'),
        ('What comes next?','Review flagged source times and platform geography, recruit a consented pilot, record independently timestamped arrivals and compare static versus crowd-adjusted field ETA error.')]
    for title,answer in questions:sub(title);p(answer)
    h('Files to open first')
    p('START_HERE.html is the offline handover. The results workbook contains the summary and supporting records. recorded-demo/panel-demo.html replays the experiment. Figure 10 and results_for_paper.md support the paper. Full_100_User_Evidence.zip retains operator responses, raw inputs and the initial failed run. FindMyMetro_Project_Source.zip contains clean project code.')
    sub('Local project startup')
    p('On the original development computer, open PowerShell in the existing find_my_metro folder and run .\\scripts\\start.ps1. Open http://localhost:5173. Preserve the existing private configuration and stored accounts. The offline recorded pack requires neither the API nor a login.')
    p('Reports in the evidence are dated 4 November. Reproduce with fresh timestamps using scripts/test_operator_crowd_100.py in the configured application Python environment. Archive the results folder first. Never submit synthetic reports to the passenger database.')
    for root in [doc._element,doc.styles.element]:
        for border in root.findall('.//'+qn('w:pBdr')):border.getparent().remove(border)
    doc.save(OUT/'FindMyMetro_Evaluation_Guide.docx')
    print('Authored six-page evaluation guide.')


def finish():
    required=['START_HERE.html','FindMyMetro_Evaluation_Guide.docx','FindMyMetro_Evaluation_Guide.pdf',
        'FindMyMetro_Evaluation_Data.xlsx','software-architecture.svg','software-architecture.png',
        'important-results.csv','results_for_paper.md','Full_100_User_Evidence.zip','FindMyMetro_Project_Source.zip']
    for name in required:assert (OUT/name).exists(),name
    # Capture the completed current source, including the handover verifier.
    build_source_archive()
    assert read_json(OUT/'browser-verification.json')['allChecksPassed']
    assert read_json(OUT/'workbook-verification.json')['allChecksPassed']
    # Exclude authoring JSON from the distribution. Source records are already
    # delivered with their measured evidence, CSVs and the workbook.
    target=OUT/'FindMyMetro_Evaluation_Panel_Pack.zip'
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p!=target and p.name not in {'workbook-data.json','pack-manifest.json'})
    manifest={'compiled_date':'2026-11-06','experiment_date':'2026-11-04',
        'files':[{'path':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
    (OUT/'pack-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    files.append(OUT/'pack-manifest.json')
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for p in files:z.write(p,p.relative_to(OUT).as_posix())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for row in manifest['files']:assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
    print(json.dumps({'pack':str(target),'files':len(files),'bytes':target.stat().st_size,'member_hashes_verified':True},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=['prepare','document','finish'])
    {'prepare':prepare,'document':document,'finish':finish}[parser.parse_args().stage]()
