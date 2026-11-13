"""Author an insertable scientific results section from measured JSON only.

Run with the bundled document runtime; no model training or database access.
"""
import csv
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/paper-100-users'


def main():
    model=json.loads((OUT/'model-results.json').read_text())
    load=json.loads((OUT/'load-results.json').read_text())
    verification=json.loads((OUT/'verification.json').read_text())
    assert verification['all_checks_passed']
    agg=model['aggregate']
    from collections import Counter
    champions=Counter(run['validation_champion'] for run in model['runs'])
    paired=next(item for item in model['comparisons'] if item['baseline']=='prophet')
    adjusted_max=max(item['p_holm'] for item in model['comparisons'])
    names={'schedule':'Schedule baseline','historical':'Historical ratio baseline','prophet':'Prophet baseline','hybrid':'Prophet and Random Forest'}
    def measure(key,metric):
        x=agg[key][metric]
        return f"{x['mean']:.2f} [{x['ci95'][0]:.2f}, {x['ci95'][1]:.2f}]"
    rows=[[names[k],measure(k,'mae_seconds'),measure(k,'rmse_seconds')] for k in names]
    stats=load['http_ack_latency'];ws=load['observation_to_websocket_latency'];validation=load['receipt_to_validation_latency'];quorum=load['quorum_to_websocket_latency']
    latency_rows=[['Report acknowledgement',f"{stats['p50_ms']/1000:.3f}",f"{stats['p95_ms']/1000:.3f}"],
                  ['Receipt to validation',f"{validation['p50_ms']/1000:.3f}",f"{validation['p95_ms']/1000:.3f}"],
                  ['Observation to WebSocket receipt',f"{ws['p50_ms']/1000:.3f}",f"{ws['p95_ms']/1000:.3f}"],
                  ['Quorum to WebSocket receipt',f"{quorum['p50_ms']/1000:.3f}",f"{quorum['p95_ms']/1000:.3f}"]]
    decrease=(agg['schedule']['mae_seconds']['mean']-agg['hybrid']['mae_seconds']['mean'])/agg['schedule']['mae_seconds']['mean']*100
    season_decrease=(agg['prophet']['mae_seconds']['mean']-agg['hybrid']['mae_seconds']['mean'])/agg['prophet']['mae_seconds']['mean']*100
    caption=('Fig. 10. Held-out ETA prediction error for four predictor components on synthetic trajectories with 100 simulated user identities per run. '
        'Bars show mean per-run MAE and RMSE over 30 independent seeds; error bars are 95% bootstrap confidence intervals obtained by resampling complete runs. '
        'Each run includes 100 test journeys and six queries per journey. This is a predictor-component comparison, not a comparison of the source-routing policies B1-B4 or ablations A1-A2.')
    sections=[
      ('Experimental configuration',[
       'We conducted two separate software experiments on 3 November 2026: a synthetic ETA predictor comparison and an authenticated crowdsourcing workload with 100 concurrent simulated accounts. No human participants, physical phones, station sensors or measured DMRC/NMRC arrival records were used. The accuracy experiment evaluates candidate predictor components; the workload experiment evaluates the existing report API, processing worker and WebSocket output. They do not constitute an integrated field trial of the complete source-routing architecture.',
       'The accuracy experiment used 30 pre-specified seeds, 3101-3130. Each seed generated 500 six-segment journeys for 100 fictional user identities, with five chronological journeys per identity. The corridor used assumed 120-second segment times and 25-second station dwell times, daily variation, journey-level congestion, independently sampled segment and dwell noise, and occasional unobserved holds. These are simulation assumptions rather than verified per-station operator times. Each journey supplied six prediction instants and one consistent final-arrival ground truth. Current movement speed was noisy; future holds and travel-time innovations were excluded from input features.',
       'Complete journeys were split chronologically into 300 training, 100 validation and 100 test journeys. Earlier outcome cutoffs preceded later prediction times. Models saw only training history, and no user identifiers were supplied as features. The same 100 identities occur across time partitions, so the experiment assesses later journeys rather than generalization to unseen people. There were 600 held-out queries per run, or 18,000 across 30 runs. Uncertainty was estimated from 5,000 bootstrap resamples of complete runs, avoiding treatment of within-journey queries as independent replicates.']),
      ('ETA prediction results',[
       f"Figure 10 compares a schedule baseline, a training-history ratio baseline, Prophet, and Prophet with a Random Forest residual correction. Prophet used daily seasonality; the forest used 40 trees, maximum depth seven and a minimum of four samples per leaf. These settings were fixed before the 30-seed run. The hybrid attained mean MAE {agg['hybrid']['mae_seconds']['mean']:.2f} s and mean RMSE {agg['hybrid']['rmse_seconds']['mean']:.2f} s. The schedule baseline recorded {agg['schedule']['mae_seconds']['mean']:.2f} s MAE and {agg['schedule']['rmse_seconds']['mean']:.2f} s RMSE. Thus the reduction in mean MAE relative to schedule was {decrease:.2f}%; relative to Prophet it was {season_decrease:.2f}%. These are simulation-specific component results.",
       f"The hybrid met its validation gate in {model['validation_acceptance_runs']} of 30 runs: lower validation MAE and no greater validation RMSE than the strongest of the three baselines. Validation selected Prophet in {champions['prophet']} runs and the historical baseline in {champions['historical']}. Test queries were evaluated after selection. Across seeds, two-sided paired Wilcoxon tests comparing hybrid MAE with each baseline gave Holm-adjusted p values no greater than {adjusted_max:.2e}. The paired MAE advantage over Prophet was {paired['mean_mae_difference_seconds']:.2f} s, with a 95% bootstrap interval of {paired['ci95'][0]:.2f}-{paired['ci95'][1]:.2f} s. This statistical result describes repeated draws from the specified generator and does not establish effectiveness on real metro operations."]),
      ('Crowdsourcing workload with 100 concurrent accounts',[
       'The workload used the actual FastAPI service and processing worker in separate subprocesses, an isolated SQLite WAL database and loopback TCP connections on a Windows workstation with 12 logical CPUs and Python 3.12.14. One hundred distinct test accounts were provisioned before timing, with sessions generated by the application session issuer. Registration and password-hashing throughput were not tested. One hundred asynchronous HTTP clients and 100 simultaneous station WebSocket subscriptions remained active over five report waves. Each wave released 100 submissions together. The deployed application uses PostgreSQL; the SQLite workload is a separate local validation configuration.',
       f"Across 20 Aqua Line station groups, each wave contained three consistent, accurately located reports, one 45-second-old upload and one deliberately off-station position per group. All {load['successful_acknowledgements']} of 500 unique submissions received durable acknowledgements with zero HTTP errors. Worker outcomes matched all injected labels: 300 validated, 100 historical and 100 rejected. All 500 expected client-wave notifications were received across 100 subscribers; the notifications are correlated within each station group and are not 500 independent quorum events. Three additional retry requests returned duplicate acknowledgements. The ledger retained 60 awards, consistent with its five-minute repeat-contribution cooldown. No community signals remained after the final observation lifetime expired.",
       f"Table VIII reports observed latency from this single local workload. Report-acknowledgement p95 was {stats['p95_ms']/1000:.3f} s. The p95 interval from the common synthetic observation timestamp to WebSocket receipt was {ws['p95_ms']/1000:.3f} s, and quorum-to-receipt p95 was {quorum['p95_ms']/1000:.3f} s. Receipt was recorded by the Python clients; browser rendering, Internet transport and device acquisition were not measured. The observed notification interval is below the proposed 30-second threshold only for this loopback receipt measurement. Report acknowledgement exceeded the earlier 500-ms REST objective; GET latency and sustained production capacity require separate measurements."]),
      ('Scope and limitations',[
       'The hybrid model was evaluated offline on simulated trajectories; the workload server used static timing plus validated station-delay overlays and did not invoke that hybrid model. Consequently, the two experiments cannot establish complete hybrid ETA latency under 100 users. The generator provides idealized accepted-position information and a stable relationship between current movement and future segment times. Real tunnels, unexpected operating changes, correlated reporting errors and unverified identities can violate these assumptions. A reported synthetic accuracy improvement must not be described as measured Delhi/Noida prediction accuracy.',
       'Figure 10 replaces the planned chart with measured predictor-component results. The feed/crowd routing baselines B1-B4, equal-trust and no-validation ablations A1-A2, and the S1-S7 coverage/outage scenarios remain unevaluated by this experiment. Tracking continuity, handover delay, switching frequency and ETA discontinuity are not reported as measured results. The API workload applies the implemented three-account, under-30-second station-report policy; it does not validate the paper\'s proposed two-account handover rule or five-minute crowd threshold. Field ground truth, a representative PostgreSQL load run and the complete routing-policy comparison are required before claiming the paper\'s full evaluation is complete.'])]
    md=['# Results and discussion','',*sum(([f'## {title}','',*sum(([p,''] for p in paragraphs),[])] for title,paragraphs in sections),[])]
    # Insert data tables into the relevant section for copy/paste.
    prediction_table='| Predictor | MAE seconds [95% CI] | RMSE seconds [95% CI] |\n|---|---:|---:|\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)
    latency_table='| Interval | p50 seconds | p95 seconds |\n|---|---:|---:|\n'+'\n'.join('| '+' | '.join(r)+' |' for r in latency_rows)
    text='\n'.join(md)
    text=text.replace('## ETA prediction results','![Figure 10](figure_10.png)\n\n'+caption+'\n\n## ETA prediction results',1)
    text=text.replace('## Crowdsourcing workload with 100 concurrent accounts','Table VII. Synthetic held-out model results; intervals are run-level bootstrap intervals.\n\n'+prediction_table+'\n\n## Crowdsourcing workload with 100 concurrent accounts',1)
    text=text.replace('## Scope and limitations','Table VIII. Single-run loopback workload latencies; 500 samples per interval.\n\n'+latency_table+'\n\n## Scope and limitations',1)
    (OUT/'results_section.md').write_text(text,encoding='utf-8')
    (OUT/'figure_10_caption.txt').write_text(caption+'\n',encoding='utf-8')
    with (OUT/'model-metrics.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.writer(file);writer.writerow(['model','mae_seconds','mae_ci_low','mae_ci_high','rmse_seconds','rmse_ci_low','rmse_ci_high'])
        for name in names:writer.writerow([name,agg[name]['mae_seconds']['mean'],*agg[name]['mae_seconds']['ci95'],agg[name]['rmse_seconds']['mean'],*agg[name]['rmse_seconds']['ci95']])
    # Word section, deliberately plain for insertion into a university paper.
    from docx import Document
    from docx.shared import Inches,Pt,RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc=Document();sec=doc.sections[0];sec.page_width=Inches(8.5);sec.page_height=Inches(11)
    sec.top_margin=sec.bottom_margin=Inches(.72);sec.left_margin=sec.right_margin=Inches(.75)
    normal=doc.styles['Normal'];normal.font.name='Times New Roman';normal.font.size=Pt(11)
    normal.paragraph_format.space_after=Pt(7);normal.paragraph_format.line_spacing=1.1
    for style in ['Title','Heading 1','Heading 2']:
        doc.styles[style].font.name='Times New Roman';doc.styles[style].font.color.rgb=RGBColor(0,0,0)
        doc.styles[style].font.size=Pt(17 if style=='Title' else 12)
    # Remove decorative rules inherited from the bundled Word template.
    for border in list(doc.styles.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    for style in ['Normal','Title','Heading 1','Heading 2']:
        fonts=doc.styles[style].element.get_or_add_rPr().get_or_add_rFonts()
        fonts.set(qn('w:ascii'),'Times New Roman');fonts.set(qn('w:hAnsi'),'Times New Roman')
        for theme in ['asciiTheme','hAnsiTheme']:
            if qn('w:'+theme) in fonts.attrib:del fonts.attrib[qn('w:'+theme)]
    doc.add_paragraph('Results and discussion',style='Title')
    date=doc.add_paragraph('FindMyMetro simulation study with 100 users   |   3 November 2026')
    for run in date.runs:run.font.size=Pt(9);run.font.color.rgb=RGBColor.from_string('555555')
    def table(headers,values,widths):
        tbl=doc.add_table(rows=1,cols=len(headers));tbl.alignment=WD_TABLE_ALIGNMENT.CENTER;tbl.autofit=False
        properties=tbl._tbl.tblPr;borders=OxmlElement('w:tblBorders')
        for edge in ['top','left','bottom','right','insideH','insideV']:
            border=OxmlElement('w:'+edge);border.set(qn('w:val'),'single');border.set(qn('w:sz'),'4');border.set(qn('w:color'),'D9D9D9');borders.append(border)
        properties.append(borders)
        for i,label in enumerate(headers):tbl.rows[0].cells[i].text=label
        for values_row in values:
            cells=tbl.add_row().cells
            for i,value in enumerate(values_row):cells[i].text=str(value)
        for row_index,row in enumerate(tbl.rows):
            for index,cell in enumerate(row.cells):
                cell.width=Inches(widths[index]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                shading=OxmlElement('w:shd');shading.set(qn('w:fill'),'183C4D' if row_index==0 else 'F3F6F7' if row_index%2==0 else 'FFFFFF');cell._tc.get_or_add_tcPr().append(shading)
                margins=OxmlElement('w:tcMar')
                for side in ['top','bottom','left','right']:
                    margin=OxmlElement('w:'+side);margin.set(qn('w:w'),'85');margin.set(qn('w:type'),'dxa');margins.append(margin)
                cell._tc.get_or_add_tcPr().append(margins)
                for para in cell.paragraphs:
                    para.paragraph_format.space_after=Pt(0);para.paragraph_format.line_spacing=1.1
                    para.alignment=WD_ALIGN_PARAGRAPH.LEFT if index==0 else WD_ALIGN_PARAGRAPH.CENTER
                    for run in para.runs:
                        run.font.size=Pt(10);run.bold=row_index==0
                        if row_index==0:run.font.color.rgb=RGBColor(255,255,255)
        repeat=OxmlElement('w:tblHeader');tbl.rows[0]._tr.get_or_add_trPr().append(repeat)
        for row in tbl.rows:
            cannot=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(cannot)
        return tbl
    for section_index,(title,paragraphs) in enumerate(sections):
        doc.add_heading(title,level=1)
        for p in paragraphs:doc.add_paragraph(p)
        if section_index==0:
            p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next=True
            p.add_run().add_picture(str(OUT/'figure_10.png'),width=Inches(6.0))
            p=doc.add_paragraph(caption)
            p.paragraph_format.keep_together=True;p.paragraph_format.line_spacing=1
            p.paragraph_format.space_after=Pt(0)
            for run in p.runs:run.font.size=Pt(9)
            doc.add_page_break()
        elif section_index==1:
            p=doc.add_paragraph('Table VII  Synthetic held out prediction results');p.paragraph_format.keep_with_next=True
            table(['Predictor','MAE seconds [95% CI]','RMSE seconds [95% CI]'],rows,[2.4,2.3,2.3])
            doc.add_paragraph('Means are calculated across 30 complete runs. Each run contains 100 held-out journeys.',style='Normal')
        elif section_index==2:
            p=doc.add_paragraph('Table VIII  Local workload latency');p.paragraph_format.keep_with_next=True
            table(['Interval','p50 seconds','p95 seconds'],latency_rows,[3.8,1.6,1.6])
            doc.add_paragraph('Each interval has 500 observations from one workload run. No browser render timing is included.')
    doc.core_properties.title='FindMyMetro simulation results with 100 users'
    doc.core_properties.subject='Measured synthetic predictor accuracy and concurrent crowdsourcing workload'
    doc.core_properties.author='FindMyMetro Project'
    doc.save(OUT/'results_section.docx')
    def latex_escape(value):
        return value.replace('\\','\\textbackslash{}').replace('%',r'\%').replace('_',r'\_').replace('&',r'\&').replace('^',r'\textasciicircum{}')
    latex=['% Insertion fragment. Requires graphicx. Update Section V to match this measured scope.',r'\section{Results and Discussion}']
    for index,(title,paragraphs) in enumerate(sections):
        latex.append(r'\subsection{'+title+'}')
        latex.extend(latex_escape(p)+'\n' for p in paragraphs)
        if index==0:
            latex.extend([r'\begin{figure*}[t]',r'\centering',r'\includegraphics[width=0.88\textwidth]{figure_10.pdf}',r'\caption{'+latex_escape(caption.split('Fig. 10. ',1)[1])+'}',r'\label{fig:eta-components}',r'\end{figure*}'])
        if index in [1,2]:
            labels=['Predictor',r'MAE (s), 95\% CI',r'RMSE (s), 95\% CI'] if index==1 else ['Interval','p50 (s)','p95 (s)']
            caption_table='Synthetic held-out predictor metrics' if index==1 else 'Local workload latency'
            latex.extend([r'\begin{table*}[t]',r'\centering',r'\caption{'+caption_table+'}',r'\begin{tabular}{lcc}',r'\hline',' & '.join(labels)+r' \\',r'\hline'])
            latex.extend(' & '.join(latex_escape(v) for v in row)+r' \\' for row in (rows if index==1 else latency_rows))
            latex.extend([r'\hline',r'\end{tabular}',r'\end{table*}'])
    (OUT/'results_section.tex').write_text('\n'.join(latex)+'\n',encoding='utf-8')
    readme='''# Figure 10 and the 100 user experiment

Completed 3 November 2026. All accounts, trajectories, report positions and outcomes are simulated. No passenger database was opened, no hardware was involved and nothing was deployed or pushed.

## Deliverables

- `figure_10.pdf`: vector figure for the paper; `figure_10.png`: 600 dpi raster; `figure_10.svg`: editable vector.
- `figure_10_caption.txt`: exact caption stating the experiment scope and uncertainty method.
- `results_section.docx`: editable results/discussion section with figure and tables.
- `results_section.md`, `results_section.tex`: Markdown and LaTeX insertion text.
- `model-results.json`, `model-protocol.json`, `heldout-predictions.jsonl`, `example-history.jsonl`: model protocol, measured metrics and reproducible evidence.
- `load-results.json`, `load-submitted-reports.jsonl`: measured HTTP/WebSocket workload and injected report labels. Session cookies, CSRF values and passwords are omitted.
- `verification.json`: independent recomputation of the 18,000 prediction errors and 500 request/update records.

## Required manuscript alignment

Replace the Figure 10 placeholder with this actual predictor-component chart and its supplied caption. It compares schedule, historical ratio, Prophet and Prophet plus Random Forest. These are not the paper's planned feed/crowd routing baselines B1-B4 or ablations A1-A2. Do not claim those experiments have been run. Update Section V to describe the actual 30-seed model protocol and the separate single-run 100-client workload. Retain S1-S7 and router ablations only as planned work unless separately measured.

The exact schema settings used by the passenger report API are three independent accounts and freshness under 30 seconds. The paper's five-minute/two-account handover description is a separate proposed policy and was not exercised. Source selection, handover continuity and source failure improvements are not measured by this figure. The original PDF is unchanged; correct its previously identified mismatched diagram placements separately using the source manuscript.

The model candidate is trained and measured offline. The concurrent server used static timing plus the real community delay overlay, not this learned model. The experiments do not establish learned-model inference capacity under 100 users. The output model is experimental and is not installed in the passenger app. The synthetic corridor assumes 120-second segments; this is not a claim about an official universal DMRC per-station duration or a supplied GTFS feed.

## Reproduction

Run from the repository folder. Model libraries must match `backend/requirements-ml.lock.txt`; the existing ML environment path is recorded privately in `.local/ml-runtime.json`.

```powershell
# ML environment (Prophet, scikit-learn, pandas, scipy, matplotlib)
& (Get-Content .local/ml-runtime.json -Raw | ConvertFrom-Json).python -m scripts.paper_model_experiment

# Application environment (FastAPI, httpx, websockets, SQLAlchemy)
..\\.venv\\Scripts\\python.exe -m scripts.paper_user_load
..\\.venv\\Scripts\\python.exe -m scripts.verify_paper_experiment
```

The workload creates a new database under `.local/paper-100-users/<random-id>/`, starts only its own API on 127.0.0.1:8020 and its own worker, and stops these child processes at the end. It refuses an occupied test port. It does not stop or send fake reports to the passenger app. SQLite results should not be relabelled as PostgreSQL production results. Setup enrollment is outside timed traffic; sign-up/Argon2 throughput and 100 browser rendering sessions are unmeasured.

Model predictions are deterministic within a compatible library build and seed. Measured workload latency varies with machine conditions. The 30 model seeds are separate from the single five-wave load run. Statistical intervals and Wilcoxon tests concern the model runs only, not repeated real users or workload independence. 100 distinct synthetic identities are reused across seeds; 3,000 held-out journeys across seeds do not represent 3,000 people.
'''
    (OUT/'README.md').write_text(readme,encoding='utf-8')
    print(json.dumps({'document':str(OUT/'results_section.docx'),'figure':str(OUT/'figure_10.pdf'),'model_rows':len(rows),'latency_rows':len(latency_rows)},indent=2))


if __name__=='__main__':main()
