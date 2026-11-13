"""Editable Word text over retained scientific artwork, preserving PDF pagination.

Body text, title, headings and references are native Word text boxes. Scientific
artwork, equations and compact tables retain their source rendering. This avoids
Word PDF Reflow moving figures and overflowing the bibliography.
"""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import statistics
import sys

from docx import Document
from docx.shared import Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT/'.local/paper-revision/pdf-edit-deps'))
import pymupdf as fitz

SOURCE=ROOT/'output/pdf/FindMyMetro_Revised_Research_Paper.pdf'
OUTPUT=ROOT/'output/docx/FindMyMetro_Revised_Research_Paper.docx'
TMP=ROOT/'tmp/docx/revised-paper'
VML='urn:schemas-microsoft-com:vml'
WPS='http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
WORD='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
AUTHOR_EMAILS=[
    '202342327.rashi@ug.sharda.ac.in',
    '2023387456.navdeep@ug.sharda.ac.in',
    '2023395486.arna@ug.sharda.ac.in',
    'laxmi.sagar1@sharda.ac.in',
]


def set_font(run,size,bold=False,italic=False):
    run.font.name='Times New Roman'
    # Half-point Word sizes are slightly larger than the PDF's fractional
    # sizes. Reserve a little width so fixed PDF line breaks never rewrap.
    run.font.size=Pt(size if size>20 else max(7.5,math.floor(size*.97*2)/2))
    run.bold=bold;run.italic=italic
    rpr=run._r.get_or_add_rPr()
    fonts=rpr.rFonts
    fonts.set(qn('w:ascii'),'Times New Roman');fonts.set(qn('w:hAnsi'),'Times New Roman')
    color=OxmlElement('w:color');color.set(qn('w:val'),'000000');rpr.append(color)


def add_background(paragraph,path):
    run=paragraph.add_run()
    inline=run.add_picture(str(path),width=Pt(612),height=Pt(792))._inline
    anchor=OxmlElement('wp:anchor')
    for key,value in {'distT':'0','distB':'0','distL':'0','distR':'0','simplePos':'0',
                      'relativeHeight':'0','behindDoc':'1','locked':'1',
                      'layoutInCell':'0','allowOverlap':'1'}.items():anchor.set(key,value)
    sp=OxmlElement('wp:simplePos');sp.set('x','0');sp.set('y','0');anchor.append(sp)
    for axis in ['H','V']:
        pos=OxmlElement('wp:position'+axis);pos.set('relativeFrom','page')
        off=OxmlElement('wp:posOffset');off.text='0';pos.append(off);anchor.append(pos)
    for tag in ['extent','effectExtent']:
        child=inline.find(qn('wp:'+tag))
        if child is not None:inline.remove(child);anchor.append(child)
    anchor.append(OxmlElement('wp:wrapNone'))
    for child in list(inline):inline.remove(child);anchor.append(child)
    inline.getparent().replace(inline,anchor)


def add_text_box(paragraph,number,lines):
    spans=[s for line in lines for s in line['spans']]
    size=max(s['size'] for s in spans)
    x0=min(line['bbox'][0] for line in lines)
    x1=max(line['bbox'][2] for line in lines)
    # Column paragraphs span their column. Headings retain their actual width.
    if len(lines)>1 and size<12 and x1-x0>180 and (x1<306 or x0>=306):
        x1=300.024 if x0<306 else 563.036
    baseline=lines[0]['spans'][0]['origin'][1]
    deltas=[lines[i+1]['spans'][0]['origin'][1]-lines[i]['spans'][0]['origin'][1]
            for i in range(len(lines)-1)]
    leading=statistics.median(deltas) if deltas else max(size*1.15,size+1)
    leading=max(leading,size)
    y0=baseline-size*.98
    width=x1-x0+3.5
    height=leading*len(lines)+size*.4+4
    pict=OxmlElement('w:pict')
    shape=etree.SubElement(pict,'{'+VML+'}shape')
    shape.set('id',f'PaperText{number}')
    shape.set('type','#_x0000_t202')
    shape.set('stroked','f');shape.set('filled','f')
    shape.set('style',f'position:absolute;margin-left:{x0:.3f}pt;margin-top:{y0:.3f}pt;'
              f'width:{width:.3f}pt;height:{height:.3f}pt;z-index:{number+1};'
              'mso-position-horizontal-relative:page;mso-position-vertical-relative:page;'
              'mso-wrap-distance-left:0;mso-wrap-distance-right:0;mso-wrap-distance-top:0;mso-wrap-distance-bottom:0')
    tb=etree.SubElement(shape,'{'+VML+'}textbox');tb.set('inset','0,0,0,0')
    content=etree.SubElement(tb,'{'+WORD+'}txbxContent')
    p=etree.SubElement(content,'{'+WORD+'}p')
    from docx.text.paragraph import Paragraph
    native=Paragraph(p,paragraph._parent)
    if size>20:native.style='Title'
    fmt=native.paragraph_format
    fmt.space_before=Pt(0);fmt.space_after=Pt(0)
    fmt.line_spacing=Pt(leading)
    fmt.widow_control=False
    fmt.keep_with_next=False
    # PDF already supplies intended line breaks and its column reading order.
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    native.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
    # Word may supply a decorative bottom rule for its built-in Title style.
    borders=OxmlElement('w:pBdr')
    for side in ['top','left','bottom','right','between','bar']:
        edge=OxmlElement('w:'+side);edge.set(qn('w:val'),'nil');borders.append(edge)
    native._p.get_or_add_pPr().append(borders)
    for index,line in enumerate(lines):
        for span in line['spans']:
            run=native.add_run(span['text'])
            set_font(run,span['size'],bool(span['flags']&16),bool(span['flags']&2))
        if index<len(lines)-1:native.add_run().add_break()
    # A final soft return lets Word preserve the line's original justified
    # width. The following empty line has no visible content.
    native.add_run().add_break()
    paragraph.add_run()._r.append(pict)
    return ' '.join(s['text'] for s in spans)


def main():
    TMP.mkdir(parents=True,exist_ok=True);OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    if OUTPUT.exists():shutil.copy2(OUTPUT,TMP/'first-reflow-conversion.docx')
    src=fitz.open(SOURCE)
    doc=Document()
    sec=doc.sections[0]
    sec.page_width=Pt(612);sec.page_height=Pt(792)
    sec.top_margin=sec.bottom_margin=sec.left_margin=sec.right_margin=Pt(0)
    sec.header_distance=sec.footer_distance=Pt(0)
    for name in ['Normal','Title']:
        doc.styles[name].font.name='Times New Roman'
        doc.styles[name].font.color.rgb=__import__('docx').shared.RGBColor(0,0,0)
        doc.styles[name].font.underline=False
        style_ppr=doc.styles[name].element.find(qn('w:pPr'))
        if style_ppr is not None:
            for node in list(style_ppr):
                if node.tag==qn('w:pBdr'):style_ppr.remove(node)
    doc.styles['Normal'].font.size=Pt(10)
    doc.core_properties.title=src.metadata.get('title','')
    doc.core_properties.author='Rashi Gupta, Navdeep Pundir, Arna Gupta, Dr. Laxmi Kant Sagar'
    doc.core_properties.subject='Editable research manuscript with retained scientific artwork'
    counter=0;records=[]
    native_text=[]
    for number,page in enumerate(src,1):
        # ReportLab can emit widely justified words as separate PDF line
        # objects at one baseline. Rejoin those fragments before authoring;
        # otherwise Word would wrap individual words over adjacent lines.
        rows={}
        for block in page.get_text('dict')['blocks']:
            if block.get('type')!=0:continue
            for line in block['lines']:
                box=line['bbox']
                column='wide' if box[0]<306 and box[2]>306 else ('left' if box[0]<306 else 'right')
                baseline=line['spans'][0]['origin'][1]
                key=(column,round(baseline*2)/2)
                rows.setdefault(key,[]).append(line)
        groups=[]
        for key,fragments in rows.items():
                fragments=sorted(fragments,key=lambda x:x['bbox'][0])
                spans=[]
                for fragment in fragments:
                    for span in fragment['spans']:
                        span=dict(span)
                        if spans and spans[-1]['text'] and span['text'] and not spans[-1]['text'].endswith(' ') and not span['text'].startswith(' '):
                            gap=span['bbox'][0]-spans[-1]['bbox'][2]
                            if gap>span['size']*.12:
                                spans[-1]['text']+=' '
                        spans.append(span)
                line={'spans':spans,'bbox':[min(s['bbox'][0] for s in spans),min(s['bbox'][1] for s in spans),
                                           max(s['bbox'][2] for s in spans),max(s['bbox'][3] for s in spans)]}
                size=max(s['size'] for s in spans)
                # Mathematical Computer Modern/Symbol and chart fonts remain
                # in the scientific artwork. Roman manuscript text is editable.
                native=all(('Times' in s['font'] or 'NimbusRom' in s['font']) for s in spans)
                # Compact table text is retained as artwork, while the complete
                # bibliography is editable along with the manuscript prose.
                native=native and (size>=9.4 or (number==1 and size>=8.9 and any(s['flags']&16 for s in spans))
                                   or (number==12 and line['bbox'][0]>310 and line['bbox'][1]>65))
                if native:groups.append([line])
        # Text boxes are isolated from the page anchor; they cannot push figures
        # or references onto another page when Word lays out the manuscript.
        anchor=doc.add_paragraph()
        if number>1:anchor.paragraph_format.page_break_before=True
        anchor.paragraph_format.space_before=Pt(0);anchor.paragraph_format.space_after=Pt(0)
        anchor.paragraph_format.line_spacing=Pt(1)
        anchor.add_run().font.size=Pt(1)
        background=fitz.open();background.insert_pdf(src,from_page=number-1,to_page=number-1)
        bg=background[0]
        for group in groups:
            for line in group:
                rr=fitz.Rect(line['bbox'])
                bg.add_redact_annot(rr+(-.15,-.1,.15,.1),fill=(1,1,1))
        bg.apply_redactions(images=0,graphics=0)
        image=TMP/f'artwork-page-{number}.png'
        bg.get_pixmap(matrix=fitz.Matrix(2.3,2.3)).save(image)
        add_background(anchor,image)
        for group in groups:
            counter+=1
            native_text.append(add_text_box(anchor,counter,group))
        added_email_lines=0
        if number==1:
            from reportlab.pdfbase.pdfmetrics import stringWidth
            for row,baseline in zip([', '.join(AUTHOR_EMAILS[:2]),', '.join(AUTHOR_EMAILS[2:])],[192.5,202.0]):
                size=9.0
                width=stringWidth(row,'Times-Roman',size)
                left=(612-width)/2
                box=[left,baseline-size*.76,left+width,baseline+size*.22]
                span={'size':size,'font':'Times-Roman','text':row,'flags':0,
                      'origin':[left,baseline],'bbox':box}
                counter+=1
                native_text.append(add_text_box(anchor,counter,[{'bbox':box,'spans':[span]}]))
                added_email_lines+=1
        records.append({'page':number,'editable_text_boxes':len(groups)+added_email_lines})
    settings=doc.settings.element
    compatibility=OxmlElement('w:compat')
    setting=OxmlElement('w:compatSetting');setting.set(qn('w:name'),'compatibilityMode')
    setting.set(qn('w:uri'),'http://schemas.microsoft.com/office/word');setting.set(qn('w:val'),'15')
    compatibility.append(setting);settings.append(compatibility)
    doc.save(OUTPUT)
    report={'source_pdf_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'docx_sha256':hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
            'source_pages':len(src),'native_editable_text_boxes':counter,
            'native_editable_words':len(' '.join(native_text).split()),
            'author_emails':AUTHOR_EMAILS,
            'scientific_artwork_retained_as_images':True,'pages':records}
    (TMP/'structure-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
