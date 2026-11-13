"""Format the result-integrated PDF for scholarly review, preserving originals.

Keeps numbered references, removes raw URLs and local-artifact instructions, and
replaces the compressed literature table without shrinking the body typography.
Unresolved bibliography issues are recorded outside the manuscript.
"""
from io import BytesIO
from pathlib import Path
import hashlib
import html
import json
import re
import sys

import add_results_to_paper as paper

fitz=paper.fitz
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT,TA_CENTER
from reportlab.platypus import Paragraph,Table,TableStyle

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'output/pdf/rashi_project_with_results.pdf'
OUTPUT=ROOT/'output/pdf/rashi_project_conference_revision.pdf'
QA=ROOT/'.local/conference-paper';QA.mkdir(parents=True,exist_ok=True)

# Full, verified titles replace shortened entries. Numbers stay fixed so all
# existing citations continue to refer to the same work. No DOI/URL is invented.
REFERENCES={
1:'H. Wanniarachchi et al., "Real-Time Train Tracking and Time Prediction System for Railway System in Sri Lanka," in Proc. 4th Asian Conf. Innovation in Technology (ASIANCON), 2024, pp. 1-6.',
2:'P. Vitello, R. D. Connors, and F. Viti, "Leveraging Crowdsourced Activity Information for Transit Stations Flow Estimation," IEEE Access, vol. 12, pp. 167518-167529, 2024.',
3:'S. Phon-Amnuaisuk et al., "Non-GPS-based ETA Models Constructed from Historical GPS Data and Traffic Contexts," in Proc. 8th Int. Conf. Business and Industrial Research (ICBIR), 2023, pp. 603-608.',
4:'J.-L. Cong et al., "Subway rail transit monitoring by built-in sensor platform of smartphone," Frontiers of Information Technology & Electronic Engineering, vol. 21, no. 8, pp. 1226-1238, 2020.',
5:'X. Li, A. Cottam, and Y.-J. Wu, "Transit Arrival Time Prediction Using Interaction Networks," IEEE Trans. Intell. Transp. Syst., vol. 24, no. 4, pp. 3833-3844, 2023.',
6:'T. Munkhbayar et al., "Deep Learning-Based Approach for Public Transportation Estimated Time Arrival Prediction," in Proc. Int. Conf. Advanced Machine Learning and Data Science (AMLDS), 2025, pp. 695-702.',
7:'FindMyMetro Project, "Context-Aware Data Source Routing System for Real-Time Metro Train Arrival Prediction," unpublished project specification, 2026.',
10:'W. Y. K. Loy et al., "Design and Prototyping of a Real-Time Location Tracking System for Railway Track Maintenance Personnel," in Proc. 11th Int. Conf. Control, Automation and Robotics (ICCAR), 2025, pp. 465-469.',
11:'Z. Lin et al., "GNN-Based Timing Prediction in Prerouting Stage With Multitask Learning Strategy," IEEE Trans. Comput.-Aided Design Integr. Circuits Syst., vol. 44, no. 8, pp. 3154-3164, 2025.',
13:'L. A. Koehler et al., "Real-Time Integrated Holding and Priority Control Strategy for Transit Systems," IEEE Trans. Intell. Transp. Syst., vol. 20, no. 9, pp. 3459-3469, 2019.',
14:'Z. Wang et al., "Attention-Based Sequence Learning Model for Travel Time Estimation," IEEE Access, vol. 8, pp. 221442-221453, 2020.',
15:'S. Lee and J. Moon, "Efficient Travel Time Estimation Between Geographical Locations Using Derived Nonlinear Spatial Features for Offline VRP Optimization," IEEE Access, vol. 13, pp. 201363-201376, 2025.',
16:'A. Bayati, K.-K. Nguyen, and M. Cheriet, "Gaussian Process Regression Ensemble Model for Network Traffic Prediction," IEEE Access, vol. 8, pp. 176540-176554, 2020.',
17:'X. Wan, H. Ghazzai, and Y. Massoud, "Mobile Crowdsourcing for Intelligent Transportation Systems: Real-Time Navigation in Urban Areas," IEEE Access, vol. 7, pp. 136995-137009, 2019.',
18:'N. Jasika et al., "Dijkstra\'s shortest path algorithm serial and parallel execution performance analysis," in Proc. 35th Int. Convention MIPRO, 2012, pp. 1811-1815.',
20:'M. Heda et al., "RescueRoute: Using Real-Time Traffic Data for Routing Emergency Vehicles," in Proc. IEEE Int. Conf. Web Intelligence and Intelligent Agent Technology (WI-IAT), 2023, pp. 362-366.'}

# These are concise scope comparisons, not invented performance rankings.
LITERATURE=[
['Zhang et al. [8]','Transit simulation and live data','Operational decision support','Transit management'],
['Liu et al. [9]','Traffic-informed route optimisation','Dynamic route selection','Depends on traffic estimates'],
['Loy et al. [10]','BLE/LoRa personnel tracking','Railway staff monitoring','Installed tracking devices'],
['Lin et al. [11]','GNN multitask circuit timing','Circuit-delay prediction','Electronic circuits, not transit'],
['Wang et al. [12]','Distributed MPC for train control','Cooperative control','Control, not passenger ETA'],
['Koehler et al. [13]','Bus holding and signal priority','Headway regulation','Service control'],
['Wanniarachchi et al. [1]','GPS and learning-based train ETA','Tracking and arrival prediction','Operational input required'],
['Cong et al. [4]','Phone inertial-sensor integration','GPS-free tunnel positioning','Position/condition monitoring'],
['Li et al. [5]','Transit ETA with interaction networks','Traffic/dwell interactions','Predictor input quality'],
['Wang et al. [14]','Attention-based travel-time model','Temporal/spatial modelling','Route-duration prediction'],
['Lee and Moon [15]','Spatial features for offline VRP','Offline duration estimation','Offline routing setting'],
['Bayati et al. [16]','GPR ensemble for network traffic','Time-series prediction','Data-network comparator'],
['Vitello et al. [2]','Crowdsourced station activity','Transit flow estimation','Demand, not train arrival'],
['Wan et al. [17]','Crowdsourced navigation and routing','Dynamic navigation','Route-planning setting'],
['Munkhbayar et al. [6]','GPS-based deep-learning bus ETA','Bus arrival prediction','Bus GPS observations'],
['Jasika et al. [18]','Parallel Dijkstra: OpenMP/OpenCL','Shortest-path computation','Algorithmic performance'],
['Liu et al. [19]','GBDT/OLS route-choice modelling','Route-choice inertia','Passenger route behaviour'],
['Heda et al. [20]','Traffic-aware emergency routing','Emergency route selection','External traffic dependency'],
['Phon-Amnuaisuk et al. [3]','Historical GPS and context models','ETA without live GPS','Historical-data dependence']]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def draw_literature(page):
    body=ParagraphStyle('LitCell',fontName='Times-Roman',fontSize=8.0,leading=9.25,alignment=TA_LEFT)
    header=ParagraphStyle('LitHeader',parent=body,fontName='Times-Bold',alignment=TA_CENTER)
    caption=ParagraphStyle('LitCaption',fontName='Times-Roman',fontSize=8.8,leading=10.2,alignment=TA_CENTER)
    widths=[108,162,123,121.072]
    rows=[[Paragraph(label,header) for label in ['Study','Application and method','Main contribution','Comparison scope']]]
    rows += [[Paragraph(html.escape(value),body) for value in row] for row in LITERATURE]
    table=Table(rows,colWidths=widths,hAlign='CENTER')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
        ('TOPPADDING',(0,0),(-1,-1),.6),('BOTTOMPADDING',(0,0),(-1,-1),.6),
        ('TOPPADDING',(0,0),(-1,0),3),('BOTTOMPADDING',(0,0),(-1,0),3),
        ('LINEABOVE',(0,0),(-1,0),.7,(0,0,0)),('LINEBELOW',(0,0),(-1,0),.5,(0,0,0)),
        ('LINEBELOW',(0,-1),(-1,-1),.7,(0,0,0)),
        ('LINEBELOW',(0,1),(-1,-2),.12,(.7,.7,.7))]))
    _,height=table.wrap(sum(widths),255)
    title=Paragraph('TABLE I<br/>COMPARISON OF RELATED WORK',caption)
    _,title_height=title.wrap(sum(widths),40)
    total=title_height+4+height
    if total>251:raise ValueError(f'Literature table exceeds its page region: {total:.2f} pt')
    # True deletion of the old table, keeping the architecture text below it.
    page.add_redact_annot(fitz.Rect(48.4,49.5,563.7,301.5),fill=(1,1,1))
    page.apply_redactions(images=0,graphics=1)
    stream=BytesIO();canvas=Canvas(stream,pagesize=(612,792))
    top=51.0;title.drawOn(canvas,paper.LEFT,792-top-title_height)
    table.drawOn(canvas,paper.LEFT,792-top-total)
    canvas.save();donor=fitz.open(stream=stream.getvalue(),filetype='pdf')
    page.show_pdf_page(page.rect,donor,0,overlay=True)
    return {'font_size_pt':8,'rows':len(LITERATURE),'columns':4,'height_pt':round(total,2),'bottom_y':round(top+total,2)}


def patch_paragraph(page,needle,replacement):
    blocks=page.get_text('dict')['blocks'];match=None
    for block in blocks:
        if block.get('type')!=0:continue
        text=' '.join(span['text'] for line in block['lines'] for span in line['spans'])
        if needle in text:match=block;break
    if match is None:raise ValueError('Paragraph location missing: '+needle)
    rect=fitz.Rect(match['bbox']);rect.x0-=.5;rect.x1+=.5;rect.y0-=.5;rect.y1+=.5
    style=ParagraphStyle('RelatedWorkPatch',parent=paper.BODY,leading=11.8,spaceAfter=0)
    # Use a shorter, source-grounded paragraph so the retained next section
    # cannot be overprinted by a reflow from this local PDF edit.
    flow=Paragraph(replacement,style);_,height=flow.wrap(paper.WIDTH,rect.height)
    if height>rect.height:raise ValueError(f'Related work paragraph does not fit: {height}>{rect.height}')
    page.add_redact_annot(rect,fill=(1,1,1));page.apply_redactions(images=0,graphics=0)
    paper.overlay_paragraph(page,rect,replacement,style)


def main():
    original=fitz.open(paper.SOURCE);current=fitz.open(INPUT);source_hash=sha(INPUT);original_hash=sha(paper.SOURCE)
    result,audit=paper.data()
    revised=fitz.open();revised.insert_pdf(current,from_page=0,to_page=7)
    layout=draw_literature(revised[2])
    patch_paragraph(revised[1],'Table I summarises 19 reviewed studies',
        'Table I compares 19 studies by application, method, contribution and scope. Circuit timing and network-traffic prediction are methodological comparators, '
        'rather than direct evidence of passenger train ETA performance.')
    patch_paragraph(revised[1],'Recurrent and attention-based networks',
        'Arrival and travel-time prediction use recurrent, attention-based and interaction models [1], [5], [6], [14], [15]. '
        'Historical-GPS and traffic-context models also support ETA without live positioning [3]. Gaussian-process ensembles for data-network traffic [16] '
        'are a separate time-series comparator. Our proposed predictor uses seasonal forecasting [21] and a tree-ensemble correction [22], '
        'while source selection determines which observations it accepts.')
    patch_paragraph(revised[1],'The reviewed work gives strong foundations',
        'These studies motivate complementary roles for sensing, prediction, crowdsourcing and route planning. '
        'FindMyMetro investigates context-dependent source selection, quality checks, explicit handover and prediction-input continuity within one workflow. '
        'The present experiment tests the operator-baseline and station-report implementation. A common-data comparison of the full proposed architecture remains future work.')
    tail=paper.make_tail(original,result,audit,conference=True,reference_overrides=REFERENCES)
    revised.insert_pdf(tail)
    for page in revised:
        for link in page.get_links():
            if link.get('uri'):page.delete_link(link)
    revised.set_metadata({**current.metadata,'subject':'Conference-style revision with measured software results and a reformatted literature comparison',
        'keywords':'metro arrival prediction, crowdsourcing, software validation, source selection'})
    revised.save(OUTPUT,garbage=4,deflate=True)
    saved=fitz.open(OUTPUT);text='\n'.join(page.get_text() for page in saved)
    assert not re.search(r'https?://|www\.|[A-Za-z0-9_-]+\.(?:csv|jsonl?|zip|html|py)\b',text), 'Unnecessary URL or local artifact name remains'
    for expected in ['765','500 / 500','1.531','4.548','Phon-Amnuaisuk','100 simulated','COMPARISON OF RELATED WORK']:
        assert expected in text,expected
    assert all(not any(link.get('uri') for link in page.get_links()) for page in saved)
    assert sha(INPUT)==source_hash and sha(paper.SOURCE)==original_hash
    unchanged=[]
    for n in [0,3,4,5,6,7]:
        same=current[n].get_pixmap().samples==saved[n].get_pixmap().samples
        unchanged.append({'page':n+1,'visually_unchanged':same});assert same
    for i,page in enumerate(saved):page.get_pixmap(matrix=fitz.Matrix(1.35,1.35)).save(QA/f'page-{i+1}.png')
    verification={'input_pdf_sha256':source_hash,'original_download_sha256':original_hash,'output_pdf_sha256':sha(OUTPUT),
        'pages':len(saved),'table':layout,'no_raw_urls_or_local_artifact_names':True,'no_external_link_annotations':True,
        'preserved_pages':unchanged,'originals_preserved':True,'completed_100_account_results_retained':True,
        'bibliography_metadata_corrections':sorted(REFERENCES),'full_literature_review_not_claimed':True}
    (paper.OUT/'rashi_project_conference_verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    (paper.OUT/'conference_author_notes.md').write_text('''# Author checks outside the conference manuscript

The conference-style PDF preserves both earlier PDFs. It uses a Times-based two-column layout with numbered citations and a four-column, 19-study literature table in 8-point type. The earlier table used approximately 5-point body type. Raw web addresses, local artifact names, supplementary download instructions and external link annotations are removed from the manuscript. Necessary operator-data references remain as plain bibliography entries.

## Reference issues requiring your source records

Original references [8], [9], [12] and [19] remain incomplete or could not be matched confidently to a primary record. Their supplied entries have been retained rather than inventing years, volumes or pages. Please provide the original publications or complete citation exports before submitting. A search candidate is not proof of identity. The circuit-timing [11] and data-network-traffic [16] works are explicitly distinguished from transit ETA evidence. Consider omitting them if the venue expects only directly relevant transport studies, with corresponding citation renumbering.

Publisher-deposited metadata supplied corrections for the non-GPS ETA author (S. Phon-Amnuaisuk, not X. Li), smartphone sensing author initials, bus ETA author initials, the circuit-timing lead author (Z. Lin), the route-estimation authors, and the emergency-routing author/title. Other confirmed full titles and venue details replace shortened bibliography entries while reference numbers stay stable. The project specification [7] is labelled unpublished; no patent publication number or granted status has been supplied.

## Other original-paper issues outside this formatting request

Several inherited design figures do not match their captions or numbering; for example, the image captioned as the hybrid prediction pipeline shows trust factors. These images were preserved in this formatting revision and require correction before submission. The train-level context and trust architecture is broader than the measured station-service workflow. The results section states that limit, and no field ETA accuracy or 100-person trial is claimed.

The user specified standard formatting rather than a named venue. The current 12-page IEEE-style layout still needs to be checked against the actual conference template, page limit, anonymity rules and bibliography policy. This is a formatting and source-record cleanup, not a guarantee of submission compliance or reference authenticity.
''',encoding='utf-8')
    print(json.dumps({'pdf':str(OUTPUT),'pages':len(saved),'literature_table':layout,'raw_urls_removed':True,'originals_preserved':True},indent=2))


if __name__=='__main__':main()
