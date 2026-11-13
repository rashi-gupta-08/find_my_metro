"""Restore the original diagram order and export figures 1-10 separately.

No observations, measured results, or design diagrams are invented. Figures 1-8
come from the supplied paper, figure 9 from its measured workload flowable, and
figure 10 from the existing recorded-data vector chart.
"""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import re
import shutil
import zipfile

import add_results_to_paper as paper
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

fitz = paper.fitz
ROOT = paper.ROOT
MAIN = ROOT / 'output/pdf/rashi_project_conference_revision.pdf'
OUT = ROOT / 'output/pdf/FindMyMetro_Separate_Figures'
QA = ROOT / 'tmp/pdfs/figure-revision'
COLLECTION = ROOT / 'output/pdf/FindMyMetro_All_10_Figures.pdf'
ARCHIVE = ROOT / 'output/pdf/FindMyMetro_Separate_Figures.zip'
NAME = 'Dr. Laxmi Kant Sagar'
AUTHORS = 'Rashi Gupta, Navdeep Pundir, Arna Gupta, ' + NAME
CAPTIONS = {
    1: 'Block diagram of the software architecture of the real-time metro train arrival prediction system (100).',
    2: 'Context-aware data source routing and backend switching.',
    3: 'Internal structure of the Dynamic Trust Engine: factors, context-dependent weights, and validation gate.',
    4: 'Acquisition and processing of the external feed in the feed-covered context.',
    5: 'Validation of crowd reports and operation in the crowd-only context.',
    6: 'Transition arbitration with a bounded predicted train position.',
    7: 'Hybrid ETA prediction pipeline of the Prediction Engine (116).',
    8: 'Overall operational method of the system.',
    9: 'Executed software workload. The frozen operator catalogue supplies the route baseline. Synthetic reports are processed through the actual API and worker; outputs and outcomes are saved for independent verification.',
    10: 'Combined software validation using frozen DMRC/NMRC indicative times and synthetic crowd reports. (a) Selected source and configured context for four cohorts over five phases, with 25 clients per cell. U, T and S denote underground, transition and surface. (b) Remaining journey duration as the scripted DMRC origin changes from Rajiv Chowk to Mandi House and Supreme Court, with destination Yamuna Bank. (c) Outcomes for 400 unique reports. (d) Empirical loopback latency distributions. The study measures software behavior and delivery, without establishing field train ETA error or hybrid-model accuracy.',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def overlay(page, buf):
    layer = fitz.open(stream=buf.getvalue(), filetype='pdf')
    page.show_pdf_page(page.rect, layer, 0)


def correct_name(doc):
    first = doc[0]
    first.add_redact_annot(fitz.Rect(48, 149, 564, 162), fill=(1, 1, 1))
    first.apply_redactions(images=0, graphics=0)
    buf = BytesIO()
    c = Canvas(buf, pagesize=(612, 792))
    c.setFont('Times-Roman', 10.9589)
    c.drawCentredString(306, 792-158.405, AUTHORS)
    c.save()
    overlay(first, buf)
    last = doc[-1]
    block = next(b for b in last.get_text('blocks') if 'The authors thank Dr.' in b[4])
    rect = fitz.Rect(block[:4])
    last.add_redact_annot(fitz.Rect(rect.x0-.5, rect.y0-.5, rect.x1+.5, rect.y1+.5), fill=(1, 1, 1))
    last.apply_redactions(images=0, graphics=0)
    style = ParagraphStyle('MentorAcknowledgment', parent=paper.BODY, spaceAfter=0)
    paper.overlay_paragraph(last, rect, f'The authors thank {NAME} for supervision and guidance throughout the project.', style)
    doc.set_metadata({**doc.metadata, 'author': AUTHORS})


def full_page(number, image_data=None, vector=None):
    """One independently captioned figure per PDF page."""
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    buf = BytesIO()
    c = Canvas(buf, pagesize=(612, 792))
    c.setFont('Times-Bold', 14)
    c.drawCentredString(306, 759, f'Figure {number}')
    style = ParagraphStyle('SeparateFigureCaption', fontName='Times-Roman', fontSize=10, leading=12)
    cap = Paragraph(f'Fig. {number}. {CAPTIONS[number]}', style)
    _, h = cap.wrap(516, 150)
    cap.drawOn(c, 48, 36)
    c.save()
    # Diagram keeps its native aspect ratio. Caption height sets a safe bottom.
    target = fitz.Rect(48, 52, 564, 792-(36+h+18))
    if image_data is not None:
        pg.insert_image(target, stream=image_data, keep_proportion=True)
    else:
        pg.show_pdf_page(target, vector, 0, keep_proportion=True)
    overlay(pg, buf)
    doc.set_metadata({'title': f'Figure {number}: {CAPTIONS[number].split(". ")[0]}', 'author': AUTHORS})
    return doc


def main():
    QA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    backup = QA / 'before-figure-revision.pdf'
    if not backup.exists():
        shutil.copy2(MAIN, backup)
    source_hash = sha(paper.SOURCE)
    source = fitz.open(paper.SOURCE)
    before = fitz.open(backup)
    revised = fitz.open(backup)
    # Original images were inserted in reverse order. The intended figure IDs
    # are visible inside the supplied drawings; use their original page slots.
    original_slots = {1:(8,0), 2:(7,1), 3:(7,0), 4:(6,0),
                      5:(5,1), 6:(5,0), 7:(4,0), 8:(3,1)}
    destinations = {1:(3,0), 2:(3,1), 3:(4,0), 4:(5,0),
                    5:(5,1), 6:(6,0), 7:(7,0), 8:(7,1)}
    assets, replacements = {}, []
    # Capture image references before replacement so inserted images cannot
    # change the positional enumeration for the following figure.
    placements = {n: revised[p].get_image_info(xrefs=True)[i]
                  for n,(p,i) in destinations.items()}
    for number, (source_page, image_index) in original_slots.items():
        info = source[source_page].get_image_info(xrefs=True)[image_index]
        data = source.extract_image(info['xref'])['image']
        assets[number] = data
        target_page = revised[destinations[number][0]]
        old = placements[number]
        target_page.delete_image(old['xref'])
        xref = target_page.insert_image(fitz.Rect(old['bbox']), stream=data, keep_proportion=True)
        replacements.append({'figure':number, 'page':destinations[number][0]+1,
                             'original_source_page':source_page+1,
                             'source_image_sha256':hashlib.sha256(data).hexdigest(), 'new_xref':xref})
    correct_name(revised)
    temp = QA / 'revised-paper.pdf'
    revised.save(temp, garbage=4, deflate=True)
    revised.close()
    final = fitz.open(temp)
    assert len(final) == len(before) == 12
    fulltext = '\n'.join(pg.get_text() for pg in final)
    assert fulltext.count(NAME) == 2
    assert not re.search(r'Lakshmikant|Laxmikant|Lakshmi\s+Kant', fulltext, re.I)
    assert 'Real-Time Metro Train Arrival Prediction' in final[0].get_text()
    assert not re.search(r'https?://|www\.', fulltext)
    for number in range(1,11):
        assert re.search(rf'Fig\.\s*{number}\.', fulltext), number
    for n in [1,2,8,9,10]:
        assert before[n].get_pixmap().samples == final[n].get_pixmap().samples, n+1
    for page_n in [0,3,4,5,6,7,8,9,11]:
        final[page_n].get_pixmap(matrix=fitz.Matrix(1.35,1.35)).save(QA/f'paper-page-{page_n+1}.png')
    final.close()
    shutil.copy2(temp, MAIN)

    # A fresh vector workload diagram uses the exact existing flowable.
    buf = BytesIO()
    c = Canvas(buf, pagesize=(paper.WIDTH,139))
    harness = paper.Harness()
    harness.drawOn(c,0,0)
    c.save()
    vector9 = fitz.open(stream=buf.getvalue(), filetype='pdf')
    vector10 = fitz.open(paper.TMP/'paper-figure-10.pdf')
    collection = fitz.open()
    exports = []
    for number in range(1,11):
        if number <= 8:
            figure = full_page(number, image_data=assets[number])
        else:
            figure = full_page(number, vector=vector9 if number == 9 else vector10)
        pdf = OUT / f'figure_{number:02}.pdf'
        png = OUT / f'figure_{number:02}.png'
        figure.save(pdf, garbage=4, deflate=True)
        figure[0].get_pixmap(matrix=fitz.Matrix(2,2)).save(png)
        collection.insert_pdf(figure)
        exports.append({'figure':number, 'pdf':pdf.name, 'png':png.name,
                        'caption':CAPTIONS[number], 'pdf_sha256':sha(pdf)})
        figure.close()
    collection.set_metadata({'title':'FindMyMetro: ten separately presented figures', 'author':AUTHORS})
    collection.save(COLLECTION, garbage=4, deflate=True)
    collection.close()
    (OUT/'captions.txt').write_text('\n\n'.join(f'Fig. {n}. {CAPTIONS[n]}' for n in range(1,11))+'\n', encoding='utf-8')
    (OUT/'README.txt').write_text(
        'Ten figures, each in a separate captioned PDF and PNG.\n'
        'Figures 1-8 restore the matching diagrams from the supplied original paper.\n'
        'They describe the proposed design, not completed field validation.\n'
        'Figure 9 describes the executed software workload.\n'
        'Figure 10 preserves four panels of the measured 100-simulated-account results.\n'
        'The experimental measurements and original diagram contents are unchanged.\n'
        'The source diagram images retain their original resolution; larger PNGs do not add detail.\n', encoding='utf-8')
    with zipfile.ZipFile(ARCHIVE,'w',zipfile.ZIP_DEFLATED) as z:
        for file in sorted(OUT.iterdir()):
            if file.suffix in ['.pdf','.png','.txt']:
                z.write(file, f'FindMyMetro_Separate_Figures/{file.name}')
    assert sha(paper.SOURCE) == source_hash
    with fitz.open(COLLECTION) as check:
        assert len(check) == 10
        for n,pg in enumerate(check,1):assert f'Fig. {n}.' in pg.get_text()
    report = {'main_pdf':str(MAIN), 'pages':12, 'mentor':NAME,
              'original_source_preserved':True, 'figure_count':10,
              'restored_original_diagram_order':replacements,
              'results_figures_9_10_unchanged_in_manuscript':True,
              'main_sha256':sha(MAIN), 'collection_sha256':sha(COLLECTION),
              'individual_exports':exports, 'archive_sha256':sha(ARCHIVE)}
    (QA/'verification.json').write_text(json.dumps(report,indent=2), encoding='utf-8')
    prior_file = ROOT/'output/pdf/rashi_project_conference_verification.json'
    if prior_file.exists():
        prior = json.loads(prior_file.read_text(encoding='utf-8-sig'))
        for key in ['preserved_pages', 'page_raster_comparison', 'title_revision']:
            if key in prior:
                prior['pre_figure_revision_'+key] = prior.pop(key)
        prior['output_pdf_sha256'] = sha(MAIN)
        prior['latest_figure_and_mentor_revision'] = report
        prior['earlier_comparison_note'] = 'Earlier raster checks describe prior revisions. The latest revision restores the eight correctly numbered design diagrams and changes the mentor name; results pages 9-11 remain pixel-identical.'
        prior_file.write_text(json.dumps(prior,indent=2), encoding='utf-8')
    notes = ROOT/'output/pdf/conference_author_notes.md'
    if notes.exists():
        value = notes.read_text(encoding='utf-8')
        value = value.replace(
            'Several inherited design figures do not match their captions or numbering; for example, the image captioned as the hybrid prediction pipeline shows trust factors. These images were preserved in this formatting revision and require correction before submission.',
            'The reversed design-diagram order has now been corrected by restoring the matching source diagrams for Figures 1-8. All ten figures are also exported separately, with one figure per page in a companion document. The manuscript remains 12 pages, and the mentor name is Dr. Laxmi Kant Sagar.')
        notes.write_text(value, encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['restored_original_diagram_order','individual_exports']},indent=2))


if __name__ == '__main__':
    main()
