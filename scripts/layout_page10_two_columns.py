"""Place separately authored Figure 10(a-d) charts on a two-column page 10.

Plots reuse the recorded experiment without changing any measurements. All other
manuscript pages, including the corrected diagrams and mentor name, are retained.
"""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import re
import shutil
import zipfile

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

import add_results_to_paper as paper

fitz = paper.fitz
ROOT = paper.ROOT
MAIN = ROOT / 'output/pdf/rashi_project_conference_revision.pdf'
DATA = ROOT / 'artifacts/operator-crowd-100-users/combined-results.json'
OUT = ROOT / 'output/pdf/FindMyMetro_Figure_10_Panels'
QA = ROOT / 'tmp/pdfs/page10-two-columns'
ARCHIVE = ROOT / 'output/pdf/FindMyMetro_Figure_10_Panels.zip'
W = paper.WIDTH
X = {'left':paper.LEFT, 'right':paper.RIGHT}
TOP, BOTTOM = 53.35, 718.85
CAPTIONS = {
    'a': 'Fig. 10(a). Selected source and configured context for four cohorts over five phases, with 25 simulated clients per cell. U, T and S denote underground, transition and surface. Static denotes the operator baseline.',
    'b': 'Fig. 10(b). Remaining journey duration during the scripted DMRC query sequence. Origins change from Rajiv Chowk to Mandi House and Supreme Court; the destination remains Yamuna Bank. This is not an observed train trajectory.',
    'c': 'Fig. 10(c). Worker outcomes for 400 unique synthetic reports: 150 validated, 50 historical and 200 rejected. Validated means eligible for account agreement, rather than independently verified train truth.',
    'd': 'Fig. 10(d). Empirical loopback latency distributions for 400 HTTP acknowledgements and 250 crowd updates. Observation-to-journey-read latency includes the per-wave worker-completion barrier.',
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def export_panel(key):
    # Retain the existing vector curves, font sizes, markers and measured values.
    # Delete other panels before cropping, rather than merely hiding their text
    # inside a clipped form object.
    source = fitz.open(paper.TMP/'paper-figure-10.pdf')
    regions = {'a':(0,0,261,214), 'b':(261,0,515.52,214),
               'c':(0,214,261,442.8), 'd':(261,214,515.52,442.8)}
    clip = fitz.Rect(regions[key]) & source[0].rect
    doc = fitz.open()
    doc.insert_pdf(source,from_page=0,to_page=0)
    pg = doc[0]
    pw,ph = pg.rect.width,pg.rect.height
    outside = [(0,0,pw,clip.y0),(0,clip.y1,pw,ph),
               (0,clip.y0,clip.x0,clip.y1),(clip.x1,clip.y0,pw,clip.y1)]
    for box in outside:
        rect = fitz.Rect(box)
        if not rect.is_empty:pg.add_redact_annot(rect,fill=(1,1,1))
    pg.apply_redactions(images=2,graphics=2)
    pg.set_cropbox(clip)
    doc.set_metadata({'title':f'Figure 10({key})','author':'Rashi Gupta, Navdeep Pundir, Arna Gupta, Dr. Laxmi Kant Sagar'})
    doc.save(OUT/f'figure_10{key}.pdf',garbage=4,deflate=True)
    doc.close()
    doc = fitz.open(OUT/f'figure_10{key}.pdf')
    pg = doc[0]
    pg.get_pixmap(matrix=fitz.Matrix(300/72,300/72)).save(OUT/f'figure_10{key}.png')
    (OUT/f'figure_10{key}.svg').write_text(pg.get_svg_image(),encoding='utf-8')
    text = pg.get_text()
    for other in 'abcd':
        assert (f'({other})' in text) == (other==key), f'Panel {key} contains another panel title'
    height = W*clip.height/clip.width
    doc.close()
    source.close()
    return height


def make_page(heights):
    """Separate column cursors enforce reading order a, b, then c, d."""
    buf = BytesIO()
    c = Canvas(buf,pagesize=(612,792))
    c.setFont('Times-Roman',8)
    c.drawCentredString(306,37,'10')
    cursor = {'left':TOP, 'right':TOP}
    placements = []
    text_boxes = []
    def para(column, text, style, after=6):
        flow = Paragraph(text,style)
        _,height = flow.wrap(W,792)
        top = cursor[column]
        assert top+height <= BOTTOM, f'Column {column} text overflow: {top+height}'
        flow.drawOn(c,X[column],792-top-height)
        text_boxes.append({'column':column,'text':text,'bbox':[X[column],top,X[column]+W,top+height]})
        cursor[column] += height+after
    def chart(column, key):
        top = cursor[column]
        height = heights[key]
        placements.append({'panel':key,'column':column,'bbox':[X[column],top,X[column]+W,top+height]})
        cursor[column] += height+5
        para(column,CAPTIONS[key],paper.CAP,after=12)
    para('left','VI. RESULTS AND DISCUSSION',paper.SECTION,after=8)
    para('left','A. Measured Software Behavior',paper.SUB,after=5)
    para('left','Figures 10(a)-10(d) report software validation with frozen DMRC/NMRC indicative times and synthetic reports. '
         'The 500 client records repeat 20 conditions, rather than 500 independent field scenarios. '
         'Field train ETA error and hybrid-model accuracy are not established.',paper.BODY)
    chart('left','a')
    chart('left','b')
    para('right','Figures 10(c) and 10(d) summarize report processing and local delivery for the completed workload.',paper.BODY)
    chart('right','c')
    chart('right','d')
    para('right','The static estimate remains available without usable evidence. Fresh agreement adds a short-lived boarding delay once. '
         'The reverse DMRC underground query uses static timing without verified phone evidence. All four cohorts return to static after expiry.',paper.BODY,after=0)
    c.save()
    doc = fitz.open(stream=buf.getvalue(),filetype='pdf')
    for pos in placements:
        plot = fitz.open(OUT/f'figure_10{pos["panel"]}.pdf')
        doc[0].show_pdf_page(fitz.Rect(pos['bbox']),plot,0)
        plot.close()
    doc.save(QA/'page10.pdf',garbage=4,deflate=True)
    doc.close()
    return {'columns':2,'column_width_pt':W,'column_gap_pt':paper.RIGHT-paper.LEFT-W,
            'chart_placements':placements,'text_boxes':text_boxes,'column_bottom_y':cursor}


def main():
    QA.mkdir(parents=True,exist_ok=True)
    OUT.mkdir(parents=True,exist_ok=True)
    backup = QA/'before-page10-change.pdf'
    if not backup.exists():shutil.copy2(MAIN,backup)
    evidence_hash = sha(DATA)
    r = json.loads(DATA.read_text())
    assert len(r['observations'])==500 and len(r['acks'])==400
    assert r['processing_outcomes']=={'rejected':200,'validated':150,'historical':50}
    heights = {key:export_panel(key) for key in 'abcd'}
    layout = make_page(heights)
    before = fitz.open(backup)
    revised = fitz.open(backup)
    revised.delete_page(9)
    page10 = fitz.open(QA/'page10.pdf')
    revised.insert_pdf(page10,start_at=9)
    revised.set_metadata(before.metadata)
    revised.save(QA/'updated-paper.pdf',garbage=4,deflate=True)
    revised.close()
    saved = fitz.open(QA/'updated-paper.pdf')
    assert len(saved)==len(before)==12
    unchanged = []
    for i in range(12):
        if i==9:continue
        assert before[i].get_pixmap().samples==saved[i].get_pixmap().samples, f'Unexpected edit on page {i+1}'
        unchanged.append(i+1)
    text = '\n'.join(pg.get_text() for pg in saved)
    assert text.count('Dr. Laxmi Kant Sagar')==2
    assert 'Real-Time Metro Train Arrival Prediction' in saved[0].get_text()
    assert not re.search(r'https?://|www\.',text)
    for key in 'abcd':assert f'Fig. 10({key}).' in saved[9].get_text()
    assert 'Fig. 10. Combined' not in saved[9].get_text()
    saved[9].get_pixmap(matrix=fitz.Matrix(1.7,1.7)).save(QA/'page-10.png')
    saved.close()
    before.close()
    shutil.copy2(QA/'updated-paper.pdf',MAIN)
    assert sha(DATA)==evidence_hash
    (OUT/'captions.txt').write_text('\n\n'.join(CAPTIONS.values())+'\n',encoding='utf-8')
    with zipfile.ZipFile(ARCHIVE,'w',zipfile.ZIP_DEFLATED) as z:
        for file in sorted(OUT.iterdir()):z.write(file,f'Figure_10_Panels/{file.name}')
    with zipfile.ZipFile(ARCHIVE) as z:assert z.testzip() is None
    report = {'pages':12,'only_page_10_changed':True,'unchanged_pages':unchanged,
              'figure_panels':['10(a)','10(b)','10(c)','10(d)'],
              'mentor_name_preserved':True,'original_measurements_unchanged':True,
              'evidence_sha256':evidence_hash,'output_sha256':sha(MAIN),'layout':layout}
    (QA/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    record = ROOT/'output/pdf/rashi_project_conference_verification.json'
    prior = json.loads(record.read_text(encoding='utf-8-sig'))
    prior['output_pdf_sha256'] = sha(MAIN)
    prior['latest_page10_two_column_revision'] = report
    record.write_text(json.dumps(prior,indent=2),encoding='utf-8')
    print(json.dumps({'pdf':str(MAIN),'pages':12,'panel_labels':report['figure_panels'],
                      'column_bottom_y':layout['column_bottom_y'],'other_pages_unchanged':True},indent=2))


if __name__=='__main__':main()
