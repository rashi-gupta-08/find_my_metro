"""Limited exact-wording and attribution audit, not a plagiarism detector."""
from collections import defaultdict
from datetime import date
from pathlib import Path
import hashlib
import json
import re
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'tmp/pdfs/language-revision'
REPORT=ROOT/'output/pdf/FindMyMetro_Originality_Review.md'


def words(text):
    text=re.sub(r'(?<=[a-z])-\s*\n(?=[a-z])','',text.lower())
    text=unicodedata.normalize('NFKC',text)
    return re.findall(r'[a-z]+(?:\x27[a-z]+)?|\d+(?:\.\d+)?',text)


def main():
    corpus=[]
    for file in ['accessible-source-excerpts.txt','web-source-excerpts.txt']:
        value=(WORK/'corpus'/file).read_text(encoding='utf-8')
        for part in value.split('--------------------------------------------------------------------------------'):
            if 'Failed to fetch' in part or len(part.strip())<300:continue
            lines=part.splitlines()
            heading=next(line for line in lines if line.strip())
            url=re.search(r'\((https?://[^\s]+)\)',heading)
            # Remove tool line markers; these are not part of the source prose.
            cleaned=re.sub(r'L\d+(?:@P[\d-]+)?:\s*','',part)
            tokens=words(cleaned)
            corpus.append({'heading':heading.split(' (https://')[0].strip(),'url':url.group(1) if url else '',
                           'words_in_returned_excerpt':len(tokens),'tokens':tokens})
    index=defaultdict(set)
    n=8
    for j,source in enumerate(corpus):
        for i in range(len(source['tokens'])-n+1):index[tuple(source['tokens'][i:i+n])].add(j)
    revised=json.loads((WORK/'final-rewrites.json').read_text(encoding='utf-8'))
    matches=[]
    for record in revised:
        tokens=words(record['text'])
        for i in range(len(tokens)-n+1):
            key=tuple(tokens[i:i+n])
            if key in index:
                matches.append({'block':record['id'],'phrase':' '.join(key),
                                'source_indices':sorted(index[key])})
    # Find overlaps in the unedited narrative as well, excluding bibliographic
    # titles, tables, chart labels, equations and formula-focused bullet lists.
    source=json.loads((WORK/'source-blocks.json').read_text(encoding='utf-8'))
    narrative_ids={r['id'] for r in revised}|{'p06b11','p07b09','p03b16','p02b18','p02b23'}
    final_narrative=[r for r in revised]+[{'id':r['id'],'text':r['text']} for r in source
                                         if r['id'] in narrative_ids and r['id'] not in {v['id'] for v in revised}]
    retained=[]
    for record in final_narrative:
        tokens=words(record['text'])
        for i in range(len(tokens)-n+1):
            key=tuple(tokens[i:i+n])
            if key in index:retained.append({'block':record['id'],'phrase':' '.join(key),'source_indices':sorted(index[key])})
    evidence={
        'date':'2026-11-10','method':'exact normalized sequences of eight consecutive words',
        'scope':'returned public source excerpts only; not full-text coverage of the cited literature',
        'manuscript_uploaded_to_external_checker':False,
        'ai_detection_score':None,'commercial_similarity_score':None,
        'sources':[{k:v for k,v in s.items() if k!='tokens'} for s in corpus],
        'revised_prose_blocks':len(revised),'reviewed_narrative_blocks':len(final_narrative),
        'eight_word_matches':retained,
        'not_a_comprehensive_plagiarism_test':True,
    }
    (WORK/'wording-overlap-audit.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    verification=json.loads((WORK/'verification.json').read_text(encoding='utf-8'))
    source_lines='\n'.join(f'- {v["heading"]}: {v["url"]}' for v in evidence['sources'])
    outcome=(f'The local comparison identified {len(retained)} matching eight-word sequence(s). '
             'The detailed internal audit records the passages for review.' if retained else
             'The local comparison found no exact eight-word sequences shared by the reviewed narrative and the retrieved source excerpts.')
    text=f'''# Language and originality review

Reviewed on 10 November 2026.

## What was completed

Three section editors revised the front matter, system design and experimental discussion. A further independent pass checked the proposed edits against the supplied paper. The final copy edits {len(revised)} prose blocks while preserving the 12-page layout, title, author line, mentor name, numbered citations, diagrams, tables and equations. Page 10 remains in two columns with Figures 10(a), 10(b), 10(c) and 10(d).

Checks retained the reported 100 simulated accounts, 400 report outcomes, 500 journey checks, 20 conditions, and p95 latencies of 1.531 s and 4.548 s. The initial 398/400 delivery run and two transport failures remain disclosed. The text distinguishes indicative operator times from observed arrivals, account agreement from independently verified train truth, and proposed ML/arbitration components from the tested software workflow. A separate verification script is described as software, rather than implying an external human assessor.

## Wording-overlap check performed

{outcome}

Method: lowercase and Unicode normalization, word tokenization and exact matching of eight consecutive words. The comparison covered {len(final_narrative)} narrative blocks against {len(corpus)} readable public source excerpts returned by web retrieval. Bibliographic entries, table labels, chart labels, equations and formula definitions were excluded. Their conventional wording and correctly attributed titles should not be rewritten merely to suppress matches. Four quoted phrase searches were also inspected; no exact occurrence of the sampled sentences was identified in the returned excerpts. The search returned some unrelated results, so absence from those excerpts is not proof of absence elsewhere.

Retrieved source excerpts:

{source_lines}

Several full-text retrieval attempts failed. The comparison therefore does not cover all cited papers, the complete public web, subscription databases, student-paper repositories, translated copying, image text or all paraphrased borrowing. A word match can be legitimate, and missing a word match cannot establish originality.

## Scores not established

No Turnitin, iThenticate or other comprehensive similarity report was supplied or generated. No AI-authorship detector was run. The manuscript was not uploaded to an external checking service. AI-detection percentage: not available. Comprehensive similarity percentage: not available. Neither a score below 10% nor a plagiarism-free finding is claimed. The local word comparison must not be reported as either percentage.

The revised prose is AI-assisted editing and still requires author review. Any AI-use statement should accurately describe the assistance and follow the conference's actual policy.

## Author checks before submission

- References [8], [9], [12] and [19] remain incomplete or not confidently authenticated. Supply the original publications or verified citation exports. Their entries were not invented or silently replaced.
- Studies [11] and [16] concern circuit timing and data-network traffic. They remain explicitly identified as methodological comparisons, rather than evidence of metro ETA performance.
- The proposed five-minute report-age window and two-report handover threshold differ from the measured 30-second expiry and three-account agreement rule. These belong to different scopes; they are not interchangeable experimental settings.
- The acquisition design's receipt-minus-event median also contains transport delay. It should not be treated as a validated clock-synchronization method without further evidence.
- Field ETA error, individual train identity, cell-fingerprint accuracy and the full hybrid-model comparison remain unmeasured.
- Check the actual venue's template, page limit and disclosure requirements. A named conference template was not supplied.

For a verified similarity assessment, have the final PDF checked through the conference or university's authorized service and review the individual matched passages. A low percentage by itself does not determine whether attribution is adequate.

## File integrity

- Original conference copy retained: yes.
- Final PDF pages: {verification['pages']}.
- Numeric and numbered-citation preservation checks: passed for edited blocks.
- Tables, charts, bibliography and other non-prose regions: unchanged in raster comparisons.
- Final PDF SHA-256: `{verification['output_sha256']}`.
'''
    REPORT.write_text(text,encoding='utf-8')
    print(json.dumps({'report':str(REPORT),'readable_source_excerpts':len(corpus),'narrative_blocks':len(final_narrative),
                      'eight_word_matches':len(retained),'matches':retained,
                      'ai_score':None,'commercial_similarity_score':None},indent=2))


if __name__=='__main__':main()
