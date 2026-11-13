"""Copy-edit narrative prose while preserving measured results and PDF layout.

The original conference PDF is never overwritten. This editor does not estimate
AI authorship or a commercial similarity score.
"""
from collections import Counter
from io import BytesIO
from pathlib import Path
import hashlib
import html
import json
import re

import add_results_to_paper as paper
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.platypus import Paragraph
from PIL import Image, ImageChops, ImageDraw

fitz = paper.fitz
ROOT = paper.ROOT
WORK = ROOT/'tmp/pdfs/language-revision'
SOURCE = ROOT/'output/pdf/rashi_project_conference_revision.pdf'
OUTPUT = ROOT/'output/pdf/FindMyMetro_Revised_Research_Paper.pdf'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(text):
    return re.sub(r'\s+',' ',re.sub(r'(?<=[a-z])-\s*\n(?=[a-z])','',text)).strip()


def markup(text):
    text = html.escape(text.replace('\u2013','-').replace('\u2014','-'))
    # Keep mathematical relationships while using readable inline subscripts.
    for word, fragment in [('Tmax','T<sub>max</sub>'),('ETAbase','ETA<sub>base</sub>'),
                           ('dobs','d<sub>obs</sub>'),('t1/2','t<sub>1/2</sub>'),
                           ('ε0','ε<sub>0</sub>'),('εv','ε<sub>v</sub>'),
                           ('t0','t<sub>0</sub>'),('zF','z<sub>F</sub>'),
                           ('zC','z<sub>C</sub>'),('zH','z<sub>H</sub>')]:
        text = text.replace(word,fragment)
    text = text.replace('∈','<font name="Symbol">∈</font>')
    text = text.replace('∗','<super>*</super>')
    return text


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    source_hash = sha(SOURCE)
    records = json.loads((WORK/'source-blocks.json').read_text(encoding='utf-8'))
    original = {r['id']:r for r in records}
    edits = []
    for name in ['front','design','results']:
        edits += json.loads((WORK/f'{name}-rewrites.json').read_text(encoding='utf-8-sig'))
    changes = {r['id']:r['text'] for r in edits}
    assert len(changes)==len(edits)==65
    changes['p02b09'] = ('Crowdsourced activity information has been used to estimate station demand [2]. '
        'Passenger reports serve a different purpose here: they describe service conditions. Because submissions can be noisy, repeated or stale, '
        'each retains its provenance and must pass validation and trust checks. Multiple reports from one contributor never count as independent confirmations.')
    changes['p07b07'] = ("Acceptance requires the candidate weight to reach the threshold and be at least as high as the predicted state's current confidence:")
    changes['p09b11'] = ('Two 2-second values and one 720-second value are retained for review; none lies on the tested Blue/Aqua routes. '
        'NMRC coordinates come from a historical mirror. Station-level zone assignments need platform-specific review at interchanges.')
    changes['p09b10'] = changes['p09b10'].replace('all 20 stored NMRC adjacent segments take 120 s',
                                               'all 20 stored NMRC adjacent-segment values are 120 s')
    changes['p07b13'] = changes['p07b13'].replace('Chronological training, validation and test splits prevent future information from entering',
        'Chronological training, validation and test splits are used to keep future information out of')
    changes['p11b14'] = changes['p11b14'].replace('An independent verifier recomputed', 'A separate verification script recomputed')
    changes['p05b13'] = changes['p05b13'].replace('they are tuned on validation data and held fixed during testing.',
        'they should be tuned on validation data and then fixed for testing.')
    # Shorten one long sentence while preserving its reported design operation.
    changes['p03b04'] = changes['p03b04'].replace('clock offset','estimated clock offset')
    changes['p01b15'] = changes['p01b15'].replace('Abstract—','Abstract - ')
    # Preserve original typesetting of inline hats and the correction formula.
    # These compact technical passages already read clearly.
    for key in ['p06b11','p07b09']:
        del changes[key]
    changes['p09b23'] = ('A live report must be younger than 30 s, carry suitable location evidence, and match station, ordered line, direction and type. '
        'Nearby GPS fixtures use 10 m accuracy; proximity is limited to 250 m. Agreement requires at least three distinct active accounts with delays '
        'within a 60 s band. Duplicate IDs and repeated submissions from one account cannot increase independent agreement.')
    for key,value in changes.items():
        old = compact(original[key]['text'])
        nums = lambda t: Counter(re.findall(r'(?<![A-Za-z])\d+(?:\.\d+)?',t))
        assert nums(old)==nums(value), f'Numeric change in {key}'
        assert re.findall(r'\[\d+\]',old)==re.findall(r'\[\d+\]',value), f'Citation change in {key}'
    for font,file in [('PaperTimes','times.ttf'),('PaperTimesBold','timesbd.ttf')]:
        pdfmetrics.registerFont(TTFont(font,'C:/Windows/Fonts/'+file))
    doc = fitz.open(SOURCE)
    plans = []
    failures = []
    for key,text in changes.items():
        rec = original[key]
        page = doc[rec['page']-1]
        rect = fitz.Rect(rec['bbox'])
        data = page.get_text('dict')['blocks'][int(key[-2:])]
        assert data['type']==0 and compact('\n'.join(''.join(s['text'] for s in l['spans']) for l in data['lines']))==compact(rec['text'])
        # Use the established column rather than a short last line's width.
        left = paper.LEFT if rect.x0<306 else paper.RIGHT
        width = paper.WIDTH
        indent = max(0,min(10,data['lines'][0]['bbox'][0]-left))
        if rec['text'].startswith('•'):
            left = rect.x0
            width = 300.024-left if left<306 else 563.036-left
            indent = 0
        size = max(rec['sizes'])
        leading = 10.1 if key=='p01b15' else (11.8 if size>9.5 else 11.3)
        font = 'PaperTimesBold' if key=='p01b15' else 'PaperTimes'
        style = ParagraphStyle(key,fontName=font,fontSize=size,leading=leading,alignment=TA_JUSTIFY,
                               firstLineIndent=indent,spaceAfter=0,allowWidows=0,allowOrphans=0)
        flow = Paragraph(markup(text),style)
        _,height = flow.wrap(width,800)
        available = rect.height+2.2
        if height>available:
            failures.append({'id':key,'height':round(height,2),'available':round(available,2),'text':text})
        plans.append({'id':key,'page':rec['page'],'rect':rect,'left':left,'width':width,
                      'flow':flow,'height':height,'new_text':text,'font_size':size,'leading':leading})
    (WORK/'fit-check.json').write_text(json.dumps(failures,indent=2),encoding='utf-8')
    if failures:
        print(json.dumps({'fit_failures':failures},ensure_ascii=False,indent=2))
        return
    for n,page in enumerate(doc,1):
        selected = [p for p in plans if p['page']==n]
        for p in selected:
            rect = p['rect']+(-.1,-.1,.1,.1)
            page.add_redact_annot(rect,fill=(1,1,1))
        if selected:page.apply_redactions(images=0,graphics=0)
        layer = BytesIO()
        canvas = Canvas(layer,pagesize=(612,792))
        for p in selected:
            p['flow'].drawOn(canvas,p['left'],792-p['rect'].y0-p['height'])
        canvas.save()
        donor = fitz.open(stream=layer.getvalue(),filetype='pdf')
        if selected:page.show_pdf_page(page.rect,donor,0)
    doc.set_metadata({**doc.metadata,'subject':'Language revision preserving the reported software experiment and source attributions'})
    doc.save(OUTPUT,garbage=4,deflate=True)
    doc.close()
    saved = fitz.open(OUTPUT)
    assert len(saved)==12
    alltext = '\n'.join(p.get_text() for p in saved)
    assert alltext.count('Dr. Laxmi Kant Sagar')==2
    assert 'Real-Time Metro Train Arrival Prediction' in saved[0].get_text()
    for s in ['1.531','4.548','398','765','500 / 500','10(a)','10(b)','10(c)','10(d)']:
        assert s in alltext,s
    assert not re.search(r'https?://|www\.|Sponsored tool|ai-humanizer',alltext,re.I)
    old = fitz.open(SOURCE)
    # Compare every pixel outside prose-edit rectangles. Tables, equations,
    # diagrams, bibliography, captions and page10's two-column chart positions
    # must remain exactly as before, allowing a two-pixel antialiasing margin.
    untouched = []
    for i,page in enumerate(saved):
        fitz.TOOLS.store_shrink(100)
        a,b = old[i].get_pixmap(),page.get_pixmap()
        ia = Image.frombytes('RGB',(a.width,a.height),a.samples)
        ib = Image.frombytes('RGB',(b.width,b.height),b.samples)
        drawa,drawb = ImageDraw.Draw(ia),ImageDraw.Draw(ib)
        for p in plans:
            if p['page']==i+1:
                rr=p['rect']
                box=(int(min(rr.x0,p['left']))-2,int(rr.y0)-2,int(max(rr.x1,p['left']+p['width']))+2,int(max(rr.y1,rr.y0+p['height'])))
                box=(box[0],box[1],box[2],box[3]+5)
                drawa.rectangle(box,fill='white');drawb.rectangle(box,fill='white')
        equal = ImageChops.difference(ia,ib).getbbox() is None
        untouched.append({'page':i+1,'non_prose_areas_identical':equal})
        if not equal:
            print('Outside-prose difference',i+1,ImageChops.difference(ia,ib).getbbox())
            ia.save(WORK/f'mask-source-{i+1}.png')
            ib.save(WORK/f'mask-revised-{i+1}.png')
            ImageChops.difference(ia,ib).save(WORK/f'mask-diff-{i+1}.png')
        assert equal, f'Unexpected edit outside prose on page {i+1}'
        page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(WORK/f'page-{i+1}.png')
    assert sha(SOURCE)==source_hash
    (WORK/'final-rewrites.json').write_text(json.dumps([{'id':k,'text':v} for k,v in changes.items()],ensure_ascii=False,indent=2),encoding='utf-8')
    (WORK/'revised-extracted-text.txt').write_text(alltext,encoding='utf-8')
    # A plain, editable review copy contains prose, not a reconstructed PDF order.
    report = {'source_sha256':source_hash,'output_sha256':sha(OUTPUT),'pages':12,
              'revised_prose_blocks':len(plans),'source_edited_word_count':sum(original[k]['words'] for k in changes),
              'revised_prose_word_count':sum(len(v.split()) for v in changes.values()),
              'numeric_and_citation_checks_passed':True,'source_unchanged':True,
              'unchanged_layout_checks':untouched,'no_detector_or_plagiarism_percentage_claimed':True}
    (WORK/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
