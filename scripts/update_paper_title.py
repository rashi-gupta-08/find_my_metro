"""Update the conference copy's title, preserving all other paper content."""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / '.local/paper-revision/pdf-edit-deps'))
import pymupdf as fitz
from reportlab.pdfgen.canvas import Canvas

TITLE = ('Real-Time Metro Train Arrival Prediction Using Trust-Based '
         'Multi-Source Data Routing and Machine Learning')
LINES = [
    'Real-Time Metro Train Arrival Prediction',
    'Using Trust-Based Multi-Source Data Routing',
    'and Machine Learning',
]
PDF = ROOT / 'output/pdf/rashi_project_conference_revision.pdf'
QA = ROOT / 'tmp/pdfs/title-revision'
QA.mkdir(parents=True, exist_ok=True)
BACKUP = QA / 'before-title-change.pdf'
if not BACKUP.exists():
    shutil.copy2(PDF, BACKUP)

doc = fitz.open(PDF)
page = doc[0]
page.add_redact_annot(fitz.Rect(48, 49, 564, 138), fill=(1, 1, 1))
page.apply_redactions(images=0, graphics=0)
buf = BytesIO()
c = Canvas(buf, pagesize=(612, 792))
c.setFont('Times-Roman', 23.9103)
for line, y in zip(LINES, [71.232, 99.127, 127.023]):
    c.drawCentredString(306, 792-y, line)
c.save()
overlay = fitz.open(stream=buf.getvalue(), filetype='pdf')
page.show_pdf_page(page.rect, overlay, 0)
metadata = doc.metadata
metadata['title'] = TITLE
doc.set_metadata(metadata)
temp = QA / 'updated.pdf'
doc.save(temp, garbage=4, deflate=True)
doc.close()

before, after = fitz.open(BACKUP), fitz.open(temp)
assert len(before) == len(after) == 12
top = after[0].get_text(clip=fitz.Rect(0, 0, 612, 140))
assert ' '.join(top.split()) == TITLE
assert after.metadata['title'] == TITLE
assert 'Context-Aware Trust-Based Data Source Routing' not in top
checks = []
for n in range(12):
    clip = fitz.Rect(0, 140, 612, 792) if n == 0 else None
    a = before[n].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip)
    b = after[n].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip)
    assert a.samples == b.samples, f'Unexpected content change on page {n+1}'
    checks.append({'page': n+1, 'unchanged_below_title' if n == 0 else 'unchanged': True})
after[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(QA / 'page-1.png')
before.close()
after.close()
shutil.copy2(temp, PDF)
report = {'title': TITLE, 'pages': 12, 'title_and_metadata_verified': True,
          'content_comparison': checks,
          'output_sha256': hashlib.sha256(PDF.read_bytes()).hexdigest()}
(QA / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
old_report = ROOT / 'output/pdf/rashi_project_conference_verification.json'
if old_report.exists():
    previous = json.loads(old_report.read_text(encoding='utf-8-sig'))
    previous['output_pdf_sha256'] = report['output_sha256']
    previous['title_revision'] = report
    previous['earlier_comparison_note'] = 'Earlier page comparisons describe the pre-title revision; the title revision verifies all content below the title remains unchanged.'
    old_report.write_text(json.dumps(previous, indent=2), encoding='utf-8')
print(json.dumps({'pdf': str(PDF), 'title': TITLE, 'pages': 12, 'all_other_content_unchanged': True}))
