"""Integrate measured software results into the supplied IEEE-style PDF.

Preserves original design pages, replaces the unfinished evaluation tail, updates
the abstract, and retains an explicit boundary between proposed and tested work.
"""
from pathlib import Path
import hashlib
import html
from io import BytesIO
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT/'.local/paper-revision'
sys.path.append(str(TMP/'pdf-edit-deps'))
import pymupdf as fitz
from reportlab.lib.enums import TA_CENTER,TA_JUSTIFY,TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate,Frame,PageTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,NextPageTemplate,KeepTogether,Flowable

SOURCE=Path('C:/Users/dell/Downloads/rashi_project.pdf')
OUT=ROOT/'output/pdf'
FINAL=OUT/'rashi_project_with_results.pdf'
EVIDENCE=ROOT/'artifacts/operator-crowd-100-users'
LEFT,RIGHT,WIDTH=48.964,311.978,251.06
BODY=ParagraphStyle('PaperBody',fontName='Times-Roman',fontSize=9.96,leading=11.95,alignment=TA_JUSTIFY,spaceAfter=6,firstLineIndent=9.96)
SUB=ParagraphStyle('PaperSubsection',parent=BODY,fontName='Times-Italic',firstLineIndent=0,spaceBefore=6,spaceAfter=5,keepWithNext=True)
SECTION=ParagraphStyle('PaperSection',parent=BODY,alignment=TA_CENTER,firstLineIndent=0,spaceBefore=8,spaceAfter=8,keepWithNext=True)
CAP=ParagraphStyle('PaperCaption',fontName='Times-Roman',fontSize=8,leading=9.6,alignment=TA_LEFT,spaceAfter=9)
TABLETEXT=ParagraphStyle('PaperTableText',fontName='Times-Roman',fontSize=8.1,leading=9.2,alignment=TA_LEFT)
REF=ParagraphStyle('PaperReference',fontName='Times-Roman',fontSize=8,leading=9.3,leftIndent=13,firstLineIndent=-13,spaceAfter=3)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def p(text,style=BODY):return Paragraph(text,style)


def data():
    r=json.loads((EVIDENCE/'combined-results.json').read_text())
    a=json.loads((EVIDENCE/'operator-provenance-audit.json').read_text())
    assert all(r['acceptance'].values())
    assert json.loads((EVIDENCE/'verification.json').read_text())['all_checks_passed']
    m=json.loads((EVIDENCE/'evidence-manifest.json').read_text())
    for item in m['files']:
        path=EVIDENCE/item['path']
        if sha(path)!=item['sha256']:raise ValueError('Changed evidence '+item['path'])
    return r,a


def table(title,rows,widths):
    heading=Paragraph(title,ParagraphStyle('TableHeading',parent=CAP,alignment=TA_CENTER,spaceBefore=7,spaceAfter=4))
    cells=[[p(html.escape(str(v)),TABLETEXT) for v in row] for row in rows]
    t=Table(cells,colWidths=widths,hAlign='CENTER',repeatRows=1)
    t.setStyle(TableStyle([('LINEABOVE',(0,0),(-1,0),.7,(0,0,0)),('LINEBELOW',(0,0),(-1,0),.5,(0,0,0)),
        ('LINEBELOW',(0,-1),(-1,-1),.7,(0,0,0)),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
        ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    return KeepTogether([heading,t,Spacer(1,8)])


class Harness(Flowable):
    def __init__(self):Flowable.__init__(self);self.width=WIDTH;self.height=139
    def draw(self):
        c=self.canv
        boxes=[('100 fixture accounts','4 waves, 400 synthetic reports'),('Actual API and worker','HTTP, PostgreSQL, validation'),
               ('100 journey WebSockets','Operator baseline plus crowd delay'),('Saved evidence and verifier','500 client checks, 20 conditions')]
        for i,(title,note) in enumerate(boxes):
            y=109-i*35;c.setLineWidth(.5);c.roundRect(12,y,227,29,3)
            c.setFont('Times-Bold',8.6);c.drawCentredString(WIDTH/2,y+18,title)
            c.setFont('Times-Roman',7.8);c.drawCentredString(WIDTH/2,y+7,note)
            if i<3:
                c.line(WIDTH/2,y,WIDTH/2,y-6);c.line(WIDTH/2,y-6,WIDTH/2-2,y-3);c.line(WIDTH/2,y-6,WIDTH/2+2,y-3)


class PDFPageFigure(Flowable):
    """Reserve paper space and later overlay the figure as vector PDF content."""
    positions=[]
    def __init__(self,width,height):Flowable.__init__(self);self.width=width;self.height=height
    def draw(self):
        x,y=self.canv.absolutePosition(0,0)
        self.positions.append({'page':self.canv.getPageNumber()-1,'x':x,'y':y,'width':self.width,'height':self.height})


class OriginalEquation(PDFPageFigure):
    positions=[]


def overlay_paragraph(page,rect,text,style):
    rect=fitz.Rect(rect);story=p(text,style)
    width,height=story.wrap(rect.width,rect.height)
    if height>rect.height:raise ValueError(f'Text does not fit: {height} > {rect.height}')
    stream=BytesIO();c=Canvas(stream,pagesize=(612,792))
    story.drawOn(c,rect.x0,792-rect.y0-height);c.save()
    donor=fitz.open(stream=stream.getvalue(),filetype='pdf')
    page.show_pdf_page(page.rect,donor,0,overlay=True)


def revised_front(original):
    doc=fitz.open();doc.insert_pdf(original,from_page=0,to_page=7)
    first=doc[0]
    reference=first.search_for('VI-B')[0]
    reference_baseline=next(span['origin'][1] for block in original[0].get_text('dict')['blocks'] if block['type']==0
        for line in block['lines'] for span in line['spans'] if 'VI-B' in span['text'])
    # True redaction removes obsolete text rather than hiding it under a box.
    first.add_redact_annot(fitz.Rect(48.4,206.5,300.6,506.4),fill=(1,1,1))
    first.add_redact_annot(fitz.Rect(311.4,492.5,563.6,575.0),fill=(1,1,1))
    first.add_redact_annot(reference,fill=(1,1,1))
    first.apply_redactions(images=0,graphics=0)
    first.insert_text((reference.x0,reference_baseline),'VI-F',fontname='tiro',fontsize=9.9626)
    abstract=('Abstract&#8212;Metro journey information must remain available when observations vary in coverage and quality. '
        'This paper presents FindMyMetro, a proposed software architecture that separates acquisition, context determination, dynamic trust, backend switching and prediction. '
        'Its general design includes bounded transition arbitration and candidate statistical and machine-learning predictors. '
        'We report a controlled validation of the current passenger implementation using frozen DMRC/NMRC indicative travel times and synthetic crowdsourced station-delay reports. '
        'The operator catalogue contains 265 stations and 281 segment records, all of which match their archived source time values. '
        'With 100 simulated authenticated accounts and 100 concurrent journey WebSockets, all 400 report outcomes and 500 client journey checks across 20 distinct conditions matched injected expectations. '
        'All 100 clients returned to static timing after evidence expiry. The p95 report acknowledgement and crowd observation-to-journey-read latencies were 1.531 s and 4.548 s in one PostgreSQL loopback run. '
        'These measurements establish software behavior, not field train-arrival accuracy. Individual train tracking, the broader router baselines and the hybrid predictor remain separate evaluation tasks.'
        '<br/><br/>Index Terms&#8212;metro ETA prediction; context-aware routing; dynamic trust; crowdsourcing; backend switching; transition arbitration; real-time transportation; machine learning')
    abstract_style=ParagraphStyle('Abstract',fontName='Times-Bold',fontSize=8.96,leading=10.1,alignment=TA_JUSTIFY)
    overlay_paragraph(first,(48.964,207.0,300.024,505.9),abstract,abstract_style)
    intro=('The work is purely software. An external feed is an optional stream of timestamped train events; its acquisition is outside scope. '
        'The completed validation combines stored operator travel times with synthetic passenger reports. '
        'The broader train-trajectory routing comparison remains planned. The contributions are:')
    intro_style=ParagraphStyle('IntroductionPatch',parent=BODY,spaceAfter=0,leading=11.6)
    overlay_paragraph(first,(311.978,492.9,563.036,575.0),intro,intro_style)
    last=doc[7]
    last.add_redact_annot(fitz.Rect(48.4,628.5,300.6,721),fill=(1,1,1))
    last.add_redact_annot(fitz.Rect(311.4,474.3,563.6,721),fill=(1,1,1))
    last.apply_redactions(images=0,graphics=0)
    bridge=('For the measured passenger implementation, the durable queue and cache are provided by PostgreSQL jobs and deadline-aware application snapshots. '
        'The active pipeline uses indicative operator timings and qualified station-service reports. Section V describes the completed experiment; Section VI reports its measured results and evaluation limits.')
    bridge_style=ParagraphStyle('ImplementationBridge',parent=BODY,fontSize=9.4,leading=10.9,firstLineIndent=0)
    overlay_paragraph(last,(48.964,629.5,300.024,719),bridge,bridge_style)
    profile=('<i>Measured software profile.</i> The local application uses a React/TypeScript web interface, FastAPI/Python, Pydantic request contracts, '
        'SQLAlchemy/Alembic, PostgreSQL and a processing worker. NetworkX generates bounded route alternatives, and REST/WebSockets publish versioned journey snapshots. '
        'No hardware, external live-train feed, Kafka or Redis was active in the completed workload.<br/><br/>'
        'The geographic labels underground, transition and surface describe configured route sections. They are distinct from the feed-covered, crowd-only and handover regimes '
        'in the general design. A validated phone position does not establish a train identity. The measured implementation adds an accepted station-service delay at boarding '
        'once, while unqualified or expired evidence leaves the static baseline active.<br/><br/>'
        'The general arbitration algorithms and Prophet/Random Forest candidates remain proposed. This experiment evaluates the passenger baseline/report path; '
        'train-level handover and hybrid inference require separate tests.')
    overlay_paragraph(last,(311.978,475.0,563.036,719),profile,ParagraphStyle('Profile',parent=BODY,firstLineIndent=0))
    return doc


def make_tail(original,r,a,*,conference=False,reference_overrides=None):
    tail=TMP/('conference-paper-tail.pdf' if conference else 'new-paper-tail.pdf')
    frames=[Frame(LEFT,73.15,WIDTH,665.5,id='left',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0),
            Frame(RIGHT,73.15,WIDTH,665.5,id='right',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)]
    wide=[Frame(LEFT,73.15,514.072,665.5,id='wide',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)]
    def footer(canvas,doc):
        canvas.setFont('Times-Roman',8);canvas.drawCentredString(306,37,str(doc.page+8))
    document=BaseDocTemplate(str(tail),pagesize=(612,792),leftMargin=LEFT,rightMargin=LEFT,topMargin=53.35,bottomMargin=73.15,
        title='FindMyMetro measured software evaluation',author='Rashi Gupta, Navdeep Pundir, Arna Gupta, Dr. Laxmi Kant Sagar')
    document.addPageTemplates([PageTemplate('columns',frames,onPage=footer),PageTemplate('figure',wide,onPage=footer)])
    s=[]
    def section(title):s.append(p(title,SECTION))
    def sub(title):s.append(p(title,SUB))
    def paragraph(text):s.append(p(text))
    section('V. EXPERIMENTAL DESIGN')
    sub('A. Completed Software Validation')
    paragraph('We evaluated the operator-baseline and crowd-report path on 4 November 2026. The workload used 100 simulated authenticated accounts on one Windows computer, '
        'not recruited commuters. It ran the actual FastAPI service, processing worker and PostgreSQL 16 database over loopback TCP. Hardware and operator live-train feeds were disabled. '
        'The measured pipeline did not invoke Prophet or Random Forest. Figure 9 shows the executed workload.')
    s.append(Harness());s.append(p('Fig. 9. Executed software workload. The frozen operator catalogue supplies the route baseline. Synthetic reports are processed through the actual API and worker; outputs and outcomes are saved for independent verification.',CAP))
    sub('B. Operator Baseline and Provenance')
    paragraph('The frozen catalogue, imported on 8 October 2026, contains 265 stations, 14 ordered line paths and 281 segment records: 261 DMRC and 20 NMRC. '
        'All 281 stored times match 280 archived public source responses [24], [25]. DMRC adjacent-segment times vary; all 20 stored NMRC adjacent segments are 120 s. '
        'These are indicative route travel times, not measured arrivals or dated next-train departures. Walking/transfer values are application estimates.')
    paragraph('The audit retains two 2-second values and one 720-second value for operator review; these flagged segments lie outside the selected Blue/Aqua workload routes. '
        'NMRC coordinates originate from a historical mirror. Configured station-level zones require platform-specific review at interchanges.')
    sub('C. Cohorts and Scripted Context Progression')
    paragraph('Four cohorts of 25 accounts queried a DMRC Blue Line underground-to-surface sequence, its reverse boundary direction, and the NMRC Aqua Line in both directions. '
        'Origins changed by script rather than observed train motion. Five phases produced 20 distinct cohort/phase conditions and 500 repeated client journey checks (Table V). '
        'NMRC remained in surface context. Each eligible cohort included nearby reports, 45-second-old uploads and distant GPS reports; missing-location phases withheld location evidence.')
    s.append(table('TABLE V<br/>EXECUTED CONTEXT AND SOURCE CONDITIONS',[
        ['Phase','DMRC U to S','DMRC S to U','Aqua'],['Initial','U / static','S / static','S / static'],
        ['Boundary','T / crowd','T / crowd','S / crowd'],['After','S / crowd','U / static','S / crowd'],
        ['Expiry','S / static','U / static','S / static'],['Recovery','S / crowd','U / static','S / crowd']],[49,68,68,66]))
    paragraph('U, T and S denote configured underground, transition and surface segments. Boundary context here is a geographic classification and report-qualification check. '
        'It does not constitute a measured train-level arbitration or bounded-motion handover. Current code permits qualified reports in any zone; underground uses static timing in this workload because verified location evidence is absent.')
    sub('D. Report Rules and Measurement Protocol')
    paragraph('A live report must be younger than 30 s, have suitable location evidence, and match its station, ordered line, direction and type. Nearby GPS fixtures use 10 m accuracy; '
        'the implemented proximity limit is 250 m. A delay group requires at least three distinct active accounts with compatible values within a 60 s band. Duplicate IDs and repeated reports by one account do not increase independent agreement.')
    paragraph('Four waves each released 100 authenticated report clients while 100 journey WebSockets were connected. The expiry phase sent no new reports and waited for real-time expiry. '
        'Accounts and sessions were provisioned before measurement. Recorded intervals are client HTTP acknowledgement, server receipt-to-worker outcome, and observation-to-client journey read. '
        'The last interval includes a per-wave worker-completion barrier. This is one descriptive local workload, without repeated-seed confidence intervals or significance tests.')
    sub('E. Broader Comparison Protocol')
    paragraph('The previously proposed B1 schedule-only, B2 crowd-only, B3 fixed-priority and B4 no-arbitration comparison, and A1 equal-trust and A2 no-validation ablations, remain future evaluation. '
        'The feed-outage, sparse-crowd and train-handover scenarios S1-S7 are not established by this passenger workload. No GTFS train trajectory, field arrival ground truth or full router comparison is inferred from the results below.')
    s.extend([NextPageTemplate('figure'),PageBreak()])
    section('VI. RESULTS AND DISCUSSION')
    s.append(p('A. Measured Software Behavior',SUB))
    paragraph('Figure 10 reports the completed operator-baseline/crowd experiment. It replaces the planned ETA-error comparison with measured source-selection, processing and delivery results. '
        'The 500 client records repeat 20 conditions and are not 500 independent field scenarios.')
    s.append(Spacer(1,5));s.append(PDFPageFigure(514.072,441.5));s.append(Spacer(1,6))
    s.append(p('Fig. 10. Combined software validation using frozen DMRC/NMRC indicative times and synthetic crowd reports. '
        '(a) Selected source and configured context for four cohorts over five phases, with 25 clients per cell. U, T and S denote underground, transition and surface. '
        '(b) Remaining journey duration as the scripted DMRC origin changes from Rajiv Chowk to Mandi House and Supreme Court, with destination Yamuna Bank. '
        '(c) Outcomes for 400 unique reports. (d) Empirical loopback latency distributions. The study measures software behavior and delivery, without establishing field train ETA error or hybrid-model accuracy.',CAP))
    paragraph('A source-labelled static estimate remains available when usable evidence is absent or stale. Fresh agreement adds a short-lived station delay at boarding once. '
        'In the reverse DMRC sequence, the underground query returns to static timing when verified phone evidence is unavailable. All four cohorts return to static after expiry.')
    s.extend([NextPageTemplate('columns'),PageBreak()])
    sub('B. Report Outcomes and Journey Checks')
    paragraph('All 400 unique report inputs received durable acknowledgements. The worker produced 150 validated reports, 50 historical uploads and 200 rejections, matching injected labels (Table VI). '
        'The rejected set comprises 150 missing-location reports and 50 distant-GPS reports. Validated means eligible for account agreement, not independently verified train truth.')
    s.append(table('TABLE VI<br/>COMPLETED WORKLOAD OUTCOMES',[
        ['Measure','Observed value'],['Simulated accounts / concurrent sockets','100 / 100'],['Distinct cohort/phase conditions','20'],
        ['Unique reports','400'],['Validated / historical / rejected','150 / 50 / 200'],['Passing client journey checks','500 / 500'],
        ['Static / crowd-adjusted updates','250 / 250'],['Expiry static fallbacks','100 / 100'],['Duplicate retries recognized','3 / 3'],
        ['Maximum duration-rule residual','0 s (injected reference)']],[157,94]))
    paragraph('All 500 client records matched expected configured context, selected evidence scope and journey arithmetic. Three explicit duplicate retries created no extra observations. '
        'The software created no phone-derived train identity. All 11 recorded acceptance conditions passed, and an independent verifier recomputed hashes, counts, duration sums and latency quantiles from exported evidence.')
    sub('C. Measured Delivery Latency')
    paragraph('Table VII reports the completed-run latency distribution. HTTP p95 is 1.531 s for report POST acknowledgements, not route GET response time. '
        'Crowd observation-to-client journey-read p95 is 4.548 s and includes the harness completion barrier. The maximum recorded crowd update latency is 4.591 s in this run. '
        'Browser rendering, Internet/mobile transport and login/registration throughput were not measured.')
    s.append(table('TABLE VII<br/>SINGLE-RUN LOOPBACK LATENCY',[
        ['Interval','n','p50 s','p95 s'],['Report acknowledgement','400','0.930','1.531'],['Receipt to worker outcome','400','0.523','0.988'],
        ['Observation to journey read','250','2.468','4.548']],[136,29,43,43]))
    paragraph('An initial run stored 398 of 400 reports after two transport ReadError failures, despite correct available journey outputs. That evidence is retained. '
        'The completed run used at most three attempts for transport failures, with the same durable event ID and bounded backoff. It recorded zero transport errors and kept normal API limits. '
        'The results therefore establish the completed fixture workload, rather than a claim of error-free networking in general.')
    sub('D. Worked Delay Examples')
    paragraph('For Mandi House to Yamuna Bank, the baseline sum is 405 s. The fixture establishes a 360 s extra wait, and the returned duration is 765 s (12 min 45 s). '
        'The accepted delay is added once at boarding. Historical and rejected reports cannot qualify for that live overlay. Table VIII shows three recorded examples.')
    s.append(table('TABLE VIII<br/>BASELINE PLUS ACCEPTED DELAY',[
        ['Journey','Base s','Delay s','Result s'],['Mandi House to Yamuna Bank','405','360','765'],
        ['Supreme Court to Yamuna Bank','288','480','768'],['NMRC Sector 51 to Sector 101','360','600','960']],[128,41,41,41]))
    sub('E. Interpretation and Threats to Validity')
    paragraph('The zero duration residual tests the known injected rule, not real ETA MAE. Actual-train arrival timestamps are unavailable, so field MAE, RMSE, positioning accuracy '
        'and commuter time savings remain unmeasured. A 100-account software workload is not a 100-person field trial. Report coordinates and delays are scripted and correlated, '
        'and separate accounts do not prove independent people or resistance to collusion.')
    paragraph('The executed scope covers selected Blue Line and Aqua Line fixtures, not every origin/destination, platform or closure. Station-level zone assignments and unusual operator timings '
        'need review. Walking estimates and historical NMRC coordinates add uncertainty to field use. One local PostgreSQL run supplies descriptive p50/p95 values, '
        'without confidence intervals or a paired policy comparison. The separate earlier synthetic ML experiment is not merged into these measurements.')
    sub('F. Proposed Continuity and Error-Bound Analysis')
    paragraph('The general design in Section IV specifies a bounded predicted state during source handover, followed by explicit fallback. This analytical design is separate '
        'from the static/report workload measured here. If the initial position error is at most &#949;<sub>0</sub> and speed error is at most &#949;<sub>v</sub>, '
        'the proposed bound is:')
    s.append(OriginalEquation(WIDTH,22))
    paragraph('The analytical interval limit is the permitted position error minus the initial error, divided by a positive speed-error bound. '
        'Values of 10 m initial error, 1 m/s speed error and 100 m tolerance give 90 s. These illustrative assumptions are not measured field bounds. '
        'Static-estimate availability differs from verified live-tracking continuity.')
    sub('G. Remaining Comparative and Field Evaluation')
    paragraph('The broader design should be evaluated on identical timestamped journeys for B1-B4 and A1-A2, with explicit tests of source outages, sparse or conflicting reports, '
        'delayed boundary messages and handover without either source. Repeated independent seeds and held-out complete journeys are needed before reporting confidence intervals '
        'or paired significance tests. Clock-age interpretation must distinguish observation time, receipt time and transport delay. '
        'A consented field pilot needs reviewed geography and independently timestamped train arrivals.')
    sub('H. Privacy and Data Access')
    paragraph('This experiment uses only synthetic account and location fixtures in an isolated database. No commuters were recruited, and passenger databases were not opened. '
        'The test database was removed after measurement. Shared evidence excludes passwords and session tokens. A real pilot must establish informed consent, data minimization, '
        'retention/deletion procedures and appropriate protection for location-derived data. No field cell-fingerprint accuracy or consent process is inferred from this synthetic run.')
    if conference:
        paragraph('The evaluation records retain original observation, receipt and processing timestamps, source decisions and journey outputs for reproducibility. '
            'The operator catalogue was archived on 8 October 2026, and the completed workload ran on 4 November 2026. '
            'Replaying the workload requires fresh observation timestamps so that the historical records do not incorrectly qualify as live evidence.')
    else:
        paragraph('Supplementary software-test materials include the frozen network, operator-baseline-segments.csv with source URLs and hashes, 400 report payloads and outcomes, '
            '500 expected/actual journey records, 20 representative snapshots, latency records, the initial failed run and reproducibility scripts. '
            'The catalogue snapshot is dated 8 October and the completed run 4 November 2026. Original timestamps are retained; a fresh replay must generate current observation times.')
    section('VII. CONCLUSION AND FUTURE WORK')
    paragraph('FindMyMetro separates acquisition, context-aware source selection and prediction in a software architecture. The current passenger implementation combines stored '
        'DMRC/NMRC indicative travel times with qualified community station delays and an explicit static fallback. '
        'In a controlled 100-account workload, 400 report outcomes and 500 journey checks across 20 conditions matched expected behavior, and all 100 clients returned to static timing after expiry. '
        'The observed p95 report acknowledgement and crowd journey-read latencies were 1.531 s and 4.548 s in one local PostgreSQL run.')
    paragraph('These results support software-level functional and integration validation. They do not establish field train-arrival accuracy, individual live train tracking, '
        'the full proposed trust/arbitration comparison or a deployed hybrid model. Future work will review operator/geographic data, obtain consented reports and independent arrival ground truth, '
        'compare routing policies on identical journeys, calibrate confidence and evaluate candidate predictors without leakage.')
    section('ACKNOWLEDGMENT')
    paragraph('The authors thank Dr. Laxmi Kant Sagar for supervision and guidance throughout the project.')
    section('REFERENCES')
    text=original[9].get_text()+original[10].get_text()
    text=text.split('REFERENCES',1)[1]
    references=re.findall(r'\[(\d+)\]\s*(.*?)(?=\[\d+\]|\Z)',text,re.S)
    if len(references)!=23:raise ValueError('Original reference extraction failed')
    reference_style=ParagraphStyle('ConferenceReference',parent=REF,leading=9.0,spaceAfter=1.0) if conference else REF
    for number,value in references:
        value=re.sub(r'-\s*\n\s*','',value);value=re.sub(r'\s+',' ',value).strip()
        if reference_overrides and int(number) in reference_overrides:
            value=reference_overrides[int(number)]
        s.append(p('['+number+'] '+html.escape(value),reference_style))
    if conference:
        s.append(p('[24] Delhi Metro Rail Corporation, "Passenger journey-planning data," indicative adjacent-station travel-time records, archived Oct. 8, 2026.',reference_style))
        s.append(p('[25] Noida Metro Rail Corporation, "Journey Planner and Fares," indicative adjacent-station travel-time records, archived Oct. 8, 2026.',reference_style))
    else:
        s.append(p('[24] Delhi Metro Rail Corporation, "Public passenger journey-planning API," adjacent route path_time responses archived 8 Oct. 2026. '
            'Available: https://backend.delhimetrorail.com/api/v2/en/ (source URLs and hashes in supplementary segment data).',REF))
        s.append(p('[25] Noida Metro Rail Corporation, "Journey Planner and Fares," adjacent-segment responses archived 8 Oct. 2026. '
            'Available: https://www.nmrcnoida.com/Passenger-Information/Journey-Planner-and-Fares. Travel times are indicative.',REF))
    document.build(s)
    donor=fitz.open(tail);figure=fitz.open(TMP/'paper-figure-10.pdf')
    for pos in PDFPageFigure.positions:
        page=donor[pos['page']]
        target=fitz.Rect(pos['x'],792-pos['y']-pos['height'],pos['x']+pos['width'],792-pos['y'])
        page.show_pdf_page(target,figure,0,keep_proportion=True)
    # Remove text outside the equation before copying it. A PDF clip alone
    # retains the entire original page in a Form XObject, which would expose
    # obsolete evaluation text to extractors even though it is not visible.
    equation=fitz.open();equation.insert_pdf(original,from_page=8,to_page=8)
    equation_page=equation[0]
    for rect in [(0,0,612,700),(0,721,612,792),(0,700,311.978,721),(563.6,700,612,721)]:
        equation_page.add_redact_annot(fitz.Rect(rect),fill=(1,1,1))
    equation_page.apply_redactions(images=0,graphics=0)
    equation_page.set_cropbox(fitz.Rect(311.978,700,563.6,721))
    for pos in OriginalEquation.positions:
        page=donor[pos['page']]
        target=fitz.Rect(pos['x'],792-pos['y']-pos['height'],pos['x']+pos['width'],792-pos['y'])
        page.show_pdf_page(target,equation,0,keep_proportion=True)
    assembled=TMP/('conference-tail-with-figure.pdf' if conference else 'tail-with-figure.pdf')
    donor.save(assembled,garbage=3,deflate=True)
    return fitz.open(assembled)


def main():
    OUT.mkdir(parents=True,exist_ok=True);r,a=data();source_hash=sha(SOURCE)
    original=fitz.open(SOURCE)
    revised=revised_front(original);tail=make_tail(original,r,a);revised.insert_pdf(tail)
    revised.set_metadata({**original.metadata,'title':'Context-Aware Trust-Based Data Source Routing for Continuous Real-Time Metro Train Arrival Prediction',
        'subject':'Revised with measured operator-baseline and synthetic crowdsourcing software results; 4 November 2026 workload',
        'keywords':'FindMyMetro, software validation, operator travel times, synthetic crowdsourcing, 100 accounts'})
    revised.save(FINAL,garbage=4,deflate=True)
    saved=fitz.open(FINAL);text='\n'.join(page.get_text() for page in saved)
    assert 'INSERT IMAGE HERE' not in text
    assert 'Result Reporting Plan' not in text
    for expected in ['400','500','1.531','4.548','20 distinct','100 simulated','765','REFERENCES']:
        assert expected in text,expected
    assert sha(SOURCE)==source_hash
    preserved=[]
    for n in range(1,7):
        before=original[n].get_pixmap(matrix=fitz.Matrix(1,1)).samples
        after=saved[n].get_pixmap(matrix=fitz.Matrix(1,1)).samples
        preserved.append(before==after)
    assert all(preserved)
    for i,page in enumerate(saved):
        page.get_pixmap(matrix=fitz.Matrix(1.1,1.1)).save(TMP/f'revised-{i+1}.png')
    (OUT/'rashi_project_results_changes.md').write_text('''# Research paper result integration

The original Downloads/rashi_project.pdf is preserved. The revised copy integrates the measured 4 November 2026 operator-baseline and synthetic crowdsourcing workload.

## Changes

- Updated the abstract and introductory evaluation scope with the measured results and their limits.
- Preserved the original title, author block and the main architecture/method pages. Original pages 2 through 7 are visually identical in automated raster comparison.
- Added an implementation-profile distinction between the proposed train-level architecture and the measured passenger baseline/report path.
- Replaced the unfinished evaluation tail with the executed methods, measured outcome/latency tables, worked delay examples, a paper-sized vector Figure 10, discussion, limitations and an updated conclusion.
- Replaced Figure 9 with the executed software workload diagram. Removed the empty Figure 10 placeholder and future-only results paragraph.
- Kept the broader B1-B4/A1-A2/S1-S7 comparison explicitly unmeasured. No field MAE/RMSE, individual-train tracking, native cell positioning or hybrid-model result was invented.
- Retained the original 23 bibliography entries and added DMRC/NMRC data-source entries 24 and 25. Existing bibliography and design figures 1-8 were not independently corrected or revalidated by this result insertion. Their pre-existing figure/content alignment still warrants review before publication.

The completed run used 100 simulated accounts, not recruited human participants. The synthetic reports and source data remain available in the evaluation evidence pack. This revision does not merge results from the separate earlier synthetic ML benchmark.
''',encoding='utf-8')
    report={'source_pdf_sha256':source_hash,'revised_pdf_sha256':sha(FINAL),'source_unchanged':True,
        'revised_pages':len(saved),'original_pages_2_to_7_visual_identity':preserved,'placeholder_removed':True,
        'result_values_match_saved_experiment':True,'all_pages_rendered_for_visual_review':True,
        'paper_figure_is_vector':True,'physical_participants':0,'simulated_accounts':100}
    (TMP/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'file':str(FINAL),'pages':len(saved),'source_preserved':True,'unchanged_design_pages_verified':all(preserved)},indent=2))


if __name__=='__main__':main()
