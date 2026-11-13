"""Package recorded research evidence and a plain-language evaluation guide.

No server is started, no timestamps are rebased, and original evidence is read only.
"""
from collections import Counter
import csv
from datetime import datetime
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/operator-crowd-100-users'
OUT = ROOT / 'artifacts/final-evaluation-dataset'
RECORDED = OUT / 'recorded-experiment'
QA = ROOT / 'tmp/pdfs/final-evaluation-dataset'
PDF = ROOT / 'output/pdf/FindMyMetro_Final_Dataset_Guide.pdf'
ZIP = OUT.parent / 'FindMyMetro_Final_Evaluation_Dataset.zip'
PREPARED = '12 November 2026'

FILES = {
    'operator-stations.csv': ('265 station records', 'One configured station; names, coordinates and zone.'),
    'operator-baseline-segments.csv': ('281 segment records', 'One adjacent segment in an ordered line path; seconds and source provenance.'),
    'simulated-participants.csv': ('100 simulated accounts', 'One synthetic account and its cohort/report role.'),
    'crowd-reports.csv': ('400 reports', 'One unique submitted event, joined to its worker outcome.'),
    'journey-context-results.csv': ('500 journey checks', 'One client and phase; expected and returned context, source and duration.'),
    'cohort-phase-summary.csv': ('20 representative checks', 'One client selected from each of four cohorts in each of five phases.'),
    'delay-report-summary.csv': ('20 cohort/phase summaries', 'One cohort/phase with report totals and a representative journey result.'),
    'http-acknowledgements.csv': ('400 acknowledgements', 'One unique report request, with transport attempts and acknowledgement time.'),
}


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, q):
    values = sorted(values)
    x = (len(values) - 1) * q
    lo = int(x)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)


def inspect_workbook(path):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as z:
        names = [n.attrib['name'] for n in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet', ns)]
        errors = []
        for filename in z.namelist():
            if filename.startswith('xl/worksheets/sheet') and filename.endswith('.xml'):
                root = ET.fromstring(z.read(filename))
                errors += [(filename, c.attrib.get('r'), c.findtext('s:v', default='', namespaces=ns))
                           for c in root.findall('.//s:c', ns) if c.attrib.get('t') == 'e']
    assert names == ['Summary', 'Journey checks', 'Report inputs', 'Operator timings', 'Latency records']
    assert not errors, errors
    return {'sheets': names, 'cached_cell_errors': errors, 'sha256': sha(path),
            'note': 'Existing workbook copied byte for byte; formulas and views not changed.'}


def audit_original():
    rows = {name: read_csv(SOURCE / name) for name in FILES}
    result = read_json(SOURCE / 'combined-results.json')
    provenance = read_json(SOURCE / 'operator-provenance-audit.json')
    reports, journeys, segments = (rows[name] for name in (
        'crowd-reports.csv', 'journey-context-results.csv', 'operator-baseline-segments.csv'))
    assert len(rows['operator-stations.csv']) == 265
    assert len(segments) == 281 and Counter(r['operator'] for r in segments) == {'DMRC': 261, 'NMRC': 20}
    assert len(rows['simulated-participants.csv']) == 100
    assert len(reports) == len({r['event_id'] for r in reports}) == 400
    assert len({r['participant'] for r in reports}) == 100
    assert all(r['data_kind'] == 'synthetic' for r in reports)
    assert len(journeys) == len({(r['phase'], r['participant']) for r in journeys}) == 500
    assert all(r['passed'] == 'True' for r in journeys)
    assert all(r['actual_source'] == r['expected_source'] and r['actual_context'] == r['expected_context'] for r in journeys)
    assert all(int(r['actual_journey_seconds']) == int(r['baseline_seconds']) + int(r['actual_delay_seconds']) for r in journeys)
    assert Counter(r['actual_source'] for r in journeys) == {'schedule': 250, 'crowd': 250}
    assert Counter(r['actual_processing'] for r in reports) == {'validated': 150, 'historical': 50, 'rejected': 200}
    assert Counter(r['reason'] for r in reports if r['actual_processing'] == 'rejected') == {
        'location_evidence_required': 150, 'outside_station_proximity': 50}
    assert all(r['actual_processing'] == r['expected_processing'] for r in reports)
    assert len(rows['cohort-phase-summary.csv']) == len(rows['delay-report-summary.csv']) == 20
    assert len({(r['cohort'], r['phase']) for r in journeys}) == 20
    assert sum(r['phase'] == 'evidence_expired' and r['actual_source'] == 'schedule' for r in journeys) == 100
    assert all(r['next_train_claimed'] == 'False' for r in journeys)
    assert all(r['matches_archived_source'] == 'True' and int(r['baseline_seconds']) == int(r['parsed_source_seconds']) for r in segments)
    assert all(sha(SOURCE / r['source_archive']) == r['source_sha256'] for r in segments)
    assert len({r['source_archive'] for r in segments}) == 280
    assert sha(SOURCE / 'operator-network-snapshot.json') == provenance['network_sha256']
    assert all(int(r['baseline_seconds']) == 120 for r in segments if r['operator'] == 'NMRC')
    assert len({int(r['baseline_seconds']) for r in segments if r['operator'] == 'DMRC'}) > 1
    acks = rows['http-acknowledgements.csv']
    assert len(acks) == 400 and {r['event_id'] for r in acks} == {r['event_id'] for r in reports}
    assert all(r['http_status'] == '202' and r['ack'] == 'queued' for r in acks)
    assert round(percentile([float(r['elapsed_ms']) for r in acks], .95), 2) == result['http_ack_latency']['p95_ms']
    ws = [float(r['observed_to_matching_ws_ms']) for r in journeys if r['observed_to_matching_ws_ms']]
    assert len(ws) == 250
    assert round(percentile(ws, .95), 2) == result['observation_to_matching_journey_ws_latency']['p95_ms']
    worker = [(datetime.fromisoformat(r['validated_at']) - datetime.fromisoformat(r['received_at'])).total_seconds() * 1000 for r in reports]
    assert round(percentile(worker, .95), 2) == result['receipt_to_processing_latency']['p95_ms']
    assert result['physical_users'] == 0 and not result['prophet_random_forest_used']
    assert result['duplicate_checks'] == ['duplicate'] * 3 and all(result['acceptance'].values())
    return rows, result, provenance


FIELDS = {
    'phase': ('category', '', 'Recorded test stage. Five stages, including expiry without report submission.'),
    'phase_index': ('integer', '', 'Zero-based stage index, 0 through 4.'),
    'participant': ('integer', '', 'Synthetic account number, 1 through 100. Not a real person identifier.'),
    'cohort': ('category', '', 'One of four scripted route groups, 25 accounts each.'),
    'expected_processing': ('category', '', 'Injected reference label: validated, historical or rejected.'),
    'actual_processing': ('category', '', 'Recorded worker outcome. Validated means eligible for agreement, not independently proven truth.'),
    'data_kind': ('category', '', 'Synthetic for all crowd report and participant records.'),
    'reason': ('text', '', 'Worker reason recorded at processing time. Awaiting agreement is not a later consensus count.'),
    'received_at': ('ISO 8601 timestamp', 'UTC', 'Receipt timestamp. In reports, server receipt; in journey results, client-read timestamp.'),
    'validated_at': ('ISO 8601 timestamp', 'UTC', 'Worker outcome timestamp, also populated for historical/rejected reports.'),
    'event_id': ('identifier', '', 'Unique durable report key. Join reports to HTTP acknowledgements using this value.'),
    'station_id': ('identifier', '', 'Reported station, or representative boarding station in a summary; join to operator-stations.id.'),
    'line_id': ('identifier', '', 'Ordered line/branch identifier, such as dmrc-ln3 or nmrc-aqua.'),
    'direction': ('category', '', 'Inbound or outbound relative to configured station order, not a compass bearing.'),
    'event_type': ('category', '', 'Report event. This workload uses delayed.'),
    'observed_at': ('ISO 8601 timestamp', 'UTC', 'Original report observation time. Offline uploads keep their original time.'),
    'delay_seconds': ('integer', 'seconds', 'Injected report of extra station-service waiting time, not independently observed train delay.'),
    'note': ('text', '', 'Explicit synthetic-data label preserved from the submitted payload.'),
    'latitude': ('decimal', 'degrees', 'Synthetic reported latitude. Blank means missing evidence, not zero.'),
    'longitude': ('decimal', 'degrees', 'Synthetic reported longitude. Blank means missing evidence, not zero.'),
    'accuracy_m': ('decimal', 'metres', 'Submitted location uncertainty. Present fixture locations use 10 m; not measured GPS performance.'),
    'operator': ('category', '', 'DMRC or NMRC, as recorded in the source catalogue.'),
    'line_name': ('text', '', 'Display name of the line path.'),
    'segment_index': ('integer', '', 'Zero-based position in an ordered line. A shared physical segment may occur in multiple paths.'),
    'from_station_id': ('identifier', '', 'Start station of an ordered adjacent segment; join to station id.'),
    'from_station': ('text', '', 'Recorded segment start station name.'),
    'to_station_id': ('identifier', '', 'End station of an ordered adjacent segment; join to station id.'),
    'to_station': ('text', '', 'Recorded segment end station name.'),
    'configured_context': ('category', '', 'Application-configured underground, surface or transition segment context; not a measured phone location.'),
    'baseline_seconds': ('integer', 'seconds', 'Stored indicative segment travel time, or sum of ride times for a queried route. Excludes an unmeasured next-train wait.'),
    'source_value': ('text', 'source-dependent', 'Original operator value. DMRC examples use H:MM:SS; NMRC examples use minutes.'),
    'parsed_source_seconds': ('integer', 'seconds', 'Source value converted to seconds for the provenance audit.'),
    'matches_archived_source': ('boolean', '', 'Recorded source-transcription match. Not a field arrival-accuracy result.'),
    'timing_source': ('text', '', 'Operator timing source type used by the importer.'),
    'source_url': ('text', '', 'Public source URL retained for provenance. Snapshot evidence is authoritative for this test.'),
    'catalogue_snapshot_at': ('ISO 8601 timestamp', 'UTC', 'Frozen catalogue import timestamp on 8 October 2026.'),
    'source_archive': ('relative path', '', 'Archived response relative to recorded-experiment, preserved without changing values.'),
    'source_sha256': ('hexadecimal', '', 'SHA-256 digest of the archived public source response.'),
    'review_flag': ('text or blank', '', 'Unusual value retained for review. Blank does not establish field correctness.'),
    'origin': ('identifier', '', 'Query boarding station id; changed by script across phases, not observed train motion.'),
    'destination': ('identifier or name', '', 'Journey destination. Journey result files use ids; delay summary uses station names.'),
    'expected_context': ('category', '', 'Configured context expected for the scripted query.'),
    'actual_context': ('category', '', 'Context returned for the query by the backend.'),
    'expected_source': ('category', '', 'Reference source label for the test: schedule or crowd.'),
    'actual_source': ('category', '', 'Returned source label. Schedule means stored static operator timing in this dataset.'),
    'scope': ('category', '', 'Static or station_service. Crowd evidence is about station service, not an identified individual train.'),
    'expected_delay_seconds': ('integer', 'seconds', 'Reference extra wait from the injected scenario, zero when crowd evidence is unusable.'),
    'actual_delay_seconds': ('integer', 'seconds', 'Extra boarding wait accepted by the backend for this query.'),
    'expected_journey_seconds': ('integer', 'seconds', 'Known policy reference: stored baseline plus expected extra wait once.'),
    'actual_journey_seconds': ('integer', 'seconds', 'Returned journey duration. This is not an independently observed arrival time.'),
    'confirmations': ('integer', 'accounts', 'Fresh qualifying independent account evidence at that snapshot. May be below all reports eventually validated.'),
    'model_version': ('text', '', 'Implementation version. The overlay/static version strings do not indicate trained ML inference.'),
    'snapshot_version': ('integer', '', 'Version key of the returned snapshot.'),
    'snapshot_at': ('ISO 8601 timestamp', 'UTC', 'Backend snapshot-generation timestamp.'),
    'phase_to_matching_ws_ms': ('decimal', 'milliseconds', 'Harness phase release to matching WebSocket client read, including completion-barrier effects.'),
    'observed_to_matching_ws_ms': ('decimal or blank', 'milliseconds', 'Observation to matching crowd-adjusted client read. Blank for static-only results, not zero latency.'),
    'next_train_claimed': ('boolean', '', 'False in all 500 records: a particular next train was not identified.'),
    'passed': ('boolean', '', 'Expected-vs-actual software condition passed. Does not mean field ETA was exact.'),
    'station': ('text', '', 'Display name of representative boarding station.'),
    'context': ('category', '', 'Configured context of representative query.'),
    'source': ('category', '', 'Selected source of representative query: schedule or crowd.'),
    'accepted_delay_seconds': ('integer', 'seconds', 'Qualified extra wait added once to representative route.'),
    'journey_seconds': ('integer', 'seconds', 'Representative returned journey duration including accepted extra wait.'),
    'reports_submitted': ('integer', 'reports', 'Unique reports in this cohort and phase. Zero in expiry phase.'),
    'validated_reports': ('integer', 'reports', 'Reports eligible for agreement across the whole cohort/phase; not necessarily confirmations at snapshot time.'),
    'historical_reports': ('integer', 'reports', 'Accepted for history but too old for current live service evidence.'),
    'rejected_reports': ('integer', 'reports', 'Unqualified reports that do not change live journey duration.'),
    'lat': ('decimal', 'degrees', 'Catalogue station latitude, not a collected participant location.'),
    'lng': ('decimal', 'degrees', 'Catalogue station longitude, not a collected participant location.'),
    'id': ('identifier', '', 'Station key used to join reports, routes and segment endpoints.'),
    'name': ('text', '', 'Catalogue station display name.'),
    'area': ('text', '', 'Catalogue operator/area display label.'),
    'x': ('decimal', 'map coordinate', 'Application map display coordinate; not metres or geographical longitude.'),
    'y': ('decimal', 'map coordinate', 'Application map display coordinate; not metres or geographical latitude.'),
    'zone': ('category', '', 'Configured station-level zone. Interchange platform details require separate review.'),
    'report_role': ('category', '', 'Scripted role: agreement low/median/high, stale upload or outside station.'),
    'physical_person_recruited': ('boolean', '', 'False: no human participant was recruited in this experiment.'),
    'http_status': ('integer', '', 'HTTP acknowledgement status. All 400 unique report requests returned 202.'),
    'ack': ('category', '', 'Durable ingestion acknowledgement. Queued means stored for processing, not validated.'),
    'attempts': ('integer', 'attempts', 'Transport attempts for the same event id. Not distinct users or reports.'),
    'transport_errors': ('JSON list', '', 'Transport errors before retry. Empty for completed-run acknowledgement rows.'),
    'elapsed_ms': ('decimal', 'milliseconds', 'HTTP request to acknowledgement duration as measured by the harness.'),
}


def dictionary(rows):
    output = []
    for filename, records in rows.items():
        for field in records[0]:
            if field not in FIELDS:
                raise KeyError(f'Missing dictionary definition: {filename}: {field}')
            dtype, units, explanation = FIELDS[field]
            example = next((r[field] for r in records if r[field] != ''), '')
            output.append(dict(file='recorded-experiment/' + filename, column=field,
                               type=dtype, units=units, meaning=explanation, example=example,
                               missing_value='Blank is unavailable/not applicable, never silently replaced by zero.'))
    return output


def make_examples(rows):
    station_names = {r['id']: r['name'] for r in rows['operator-stations.csv']}
    selects = [
        ('E1', 'boundary_agreement', '1', 'Transition: accepted 6-minute station delay.'),
        ('E2', 'surface_and_underground', '1', 'Surface: accepted 8-minute station delay.'),
        ('E3', 'surface_and_underground', '26', 'Underground: missing usable phone evidence leaves static timing active.'),
        ('E4', 'evidence_expired', '1', 'Expiry: the surface query returns to the static baseline.'),
        ('E5', 'fresh_evidence_recovery', '1', 'Recovery: fresh agreement adds a 10-minute delay.'),
        ('E6', 'fresh_evidence_recovery', '51', 'NMRC: three stored 120-second segments plus a 10-minute extra wait.'),
        ('E7', 'initial_static', '1', 'Initial underground query: baseline only; no qualified live evidence.'),
        ('E8', 'boundary_agreement', '26', 'Reverse boundary: surface-to-underground query also accepts qualified reports.'),
    ]
    examples = []
    for eid, phase, participant, explanation in selects:
        rownum, r = next((i + 2, r) for i, r in enumerate(rows['journey-context-results.csv'])
                         if r['phase'] == phase and r['participant'] == participant)
        examples.append(dict(example_id=eid, explanation=explanation,
            source_file='recorded-experiment/journey-context-results.csv', source_csv_row=rownum,
            phase=phase, participant=int(participant), cohort=r['cohort'],
            origin=station_names[r['origin']], destination=station_names[r['destination']],
            context=r['actual_context'], source=r['actual_source'],
            baseline_seconds=int(r['baseline_seconds']), accepted_delay_seconds=int(r['actual_delay_seconds']),
            journey_seconds=int(r['actual_journey_seconds']), confirmations=int(r['confirmations']),
            arithmetic=f"{r['baseline_seconds']} + {r['actual_delay_seconds']} = {r['actual_journey_seconds']} seconds",
            interpretation='Recorded software result with injected delay; no actual train arrival measurement.'))
    report_examples = []
    meanings = {
        'combined-1-000': 'Nearby fresh report, one of 15 reports eventually eligible in this cohort/phase; agreement still required.',
        'combined-1-001': 'Nearby fresh report around the injected 360-second agreement value.',
        'combined-1-002': 'Nearby fresh report within the agreement tolerance.',
        'combined-1-003': 'Approximately 45 seconds old on receipt, so stored as historical and excluded from live overlay.',
        'combined-1-004': 'Latitude offset by 0.02 degrees in fixture, beyond the station proximity limit; rejected.',
        'combined-0-000': 'No submitted location, so this report cannot qualify as live station evidence.',
    }
    for event_id, meaning in meanings.items():
        rownum, r = next((i + 2, r) for i, r in enumerate(rows['crowd-reports.csv']) if r['event_id'] == event_id)
        report_examples.append(dict(example_id='R' + str(len(report_examples) + 1),
            source_file='recorded-experiment/crowd-reports.csv', source_csv_row=rownum,
            **r, station_name=station_names[r['station_id']],
            observation_age_at_receipt_seconds=round((datetime.fromisoformat(r['received_at']) - datetime.fromisoformat(r['observed_at'])).total_seconds(), 3),
            explanation=meaning))
    return examples, report_examples


def blocks(rows, result, provenance, examples, report_examples):
    # A shared content model keeps the printable and browser explanations consistent.
    def p(text): return ('p', text)
    def h(text): return ('h', text)
    def note(text): return ('note', text)
    def table(headers, data, widths): return ('table', headers, data, widths)
    phases = [
        ['Initial static', 'Rajiv Chowk', 'Underground', 'Static', '641 + 0 = 641'],
        ['Boundary agreement', 'Mandi House', 'Transition', 'Crowd', '405 + 360 = 765'],
        ['After boundary', 'Supreme Court', 'Surface', 'Crowd', '288 + 480 = 768'],
        ['Evidence expired', 'Supreme Court', 'Surface', 'Static', '288 + 0 = 288'],
        ['Fresh recovery', 'Supreme Court', 'Surface', 'Crowd', '288 + 600 = 888'],
    ]
    return [
        ('Final evaluation dataset', [
            p(f'FindMyMetro | Prepared {PREPARED} | Evaluation: 13 November 2026'),
            note('Use this pack to demonstrate the completed software experiment: stored operator travel times plus qualified crowdsourced station-delay reports.'),
            table(['Catalogue', 'Crowd input', 'Software output'], [
                ['265 stations', '100 simulated accounts', '500 journey checks'],
                ['281 adjacent segment records', '400 synthetic reports', '20 distinct cohort/phase conditions'],
                ['DMRC: 261; NMRC: 20 segments', '0 human participants', '250 static + 250 crowd updates'],
            ], [171, 170, 170]),
            h('Three kinds of data'),
            table(['Kind', 'What the dataset contains'], [
                ['Operator source records', 'Frozen public DMRC/NMRC indicative travel-time catalogue, imported 8 October 2026. All 281 time values match the archived source audit.'],
                ['Synthetic crowd inputs', '100 authenticated test accounts, scripted station locations, report ages and 6-, 8- and 10-minute delay scenarios.'],
                ['Measured software outcomes', 'Actual local FastAPI requests, PostgreSQL worker outcomes and 100 connected journey WebSocket clients, recorded 4 November 2026.'],
            ], [118, 393]),
            h('The result you can defend'),
            p('The software selected the expected source and calculated the expected journey duration for all 500 client checks. These are repeated checks across 20 conditions. The experiment demonstrates validation, source selection, delay addition, expiry and recovery.'),
            p('This handover rechecks saved evidence. It does not represent a new trial, current passenger reports or a 100-person field study. Hardware, native cell-tower matching and real train arrival accuracy were outside this run.'),
        ]),
        ('What to open and how to read it', [
            p('Start with START_HERE.html. It works offline. Open the Excel workbook for tables and the recorded panel demo for the five test phases. The original CSV/JSON files remain unchanged in recorded-experiment.'),
            table(['Dataset file', 'Rows', 'One row means'], [
                [name, str(len(rows[name])), desc] for name, (_, desc) in FILES.items()
            ], [193, 45, 273]),
            h('Join the evidence'),
            p('Match crowd-reports.event_id to http-acknowledgements.event_id. Match participant to simulated-participants.participant. Match station_id, origin or destination to operator-stations.id. A journey record is identified by phase + participant.'),
            p('Source paths and SHA-256 digests in operator-baseline-segments.csv lead to the archived public responses. DATA_DICTIONARY.csv defines every column in the eight raw CSV tables, with units and a real example value.'),
            note('Seconds are durations. Milliseconds measure processing/delivery latency. UTC timestamps retain the original test time. Blank location or latency fields mean missing/not applicable, not zero.'),
            p('The five workbook sheets are Summary, Journey checks, Report inputs, Operator timings and Latency records. The workbook is the existing verified snapshot, copied without edits.'),
        ]),
        ('Example 1: build the static baseline', [
            p('The baseline is calculated from adjacent operator segment values. Do not describe every DMRC segment as two minutes. DMRC values vary; all 20 stored NMRC segment values in this snapshot are 120 seconds.'),
            h('Mandi House to Yamuna Bank'),
            table(['Adjacent segment', 'Source value', 'Seconds'], [
                ['Mandi House to Supreme Court', '0:01:57', '117'],
                ['Supreme Court to Indraprastha', '0:01:51', '111'],
                ['Indraprastha to Yamuna Bank', '0:02:57', '177'],
                ['Sum of three ride segments', '', '405'],
            ], [326, 105, 80]),
            note('117 + 111 + 177 = 405 seconds = 6 minutes 45 seconds. With a qualified 360-second extra wait, the returned duration becomes 765 seconds = 12 minutes 45 seconds.'),
            h('NMRC Sector 51 to Sector 101'),
            table(['Adjacent segment', 'Seconds'], [
                ['Noida Sector - 51 to Noida Sector - 50', '120'],
                ['Noida Sector - 50 to Noida Sector - 76', '120'],
                ['Noida Sector - 76 to Noida Sector - 101', '120'],
                ['Sum', '360'],
            ], [411, 100]),
            p('At fresh recovery, the accepted synthetic extra wait was 600 seconds. The returned NMRC duration was 360 + 600 = 960 seconds, or 16 minutes. See worked-journey-examples.csv, E6.'),
            h('Source quality matters'),
            p('The catalogue has three unusual retained timing records: two 2-second values and one 720-second value. They are flagged for review and lie outside the Blue/Aqua routes used here. A transcription match is not proof of a correct operational time. Both directions reuse stored adjacent times; directional accuracy was not measured.'),
        ]),
        ('Example 2: accept useful reports', [
            p('At Mandi House in boundary_agreement, nearby accounts reported around a six-minute extra wait. The following are exact selected rows. Their location coordinates are scripted fixture values, not passenger GPS measurements.'),
            table(['Event ID', 'Account', 'Delay (s)', 'Worker outcome', 'Why it matters'], [
                [r['event_id'], r['participant'], r['delay_seconds'], r['actual_processing'],
                 {'combined-1-000': 'Fresh and nearby; agreement required.',
                  'combined-1-001': 'Fresh and nearby; median-value example.',
                  'combined-1-002': 'Fresh and nearby; within tolerance.',
                  'combined-1-003': '45.197 seconds old on receipt; historical only.',
                  'combined-1-004': 'Outside station proximity; excluded.',
                  'combined-0-000': 'No location evidence; excluded.'}[r['event_id']]] for r in report_examples
            ], [104, 55, 52, 76, 224]),
            h('How agreement affects the route'),
            p('The first three selected delays are 345, 360 and 375 seconds; their median is 360 seconds. They are examples from 15 reports eventually validated in this cohort/phase. The representative journey snapshot had 15 confirmations and used a 360-second overlay.'),
            p('A report marked validated is eligible evidence. Its saved reason may still be awaiting_independent_agreement because that row records processing time. It does not, by itself, prove the live aggregate had already reached consensus.'),
            h('Rules used in this recorded workload'),
            table(['Rule', 'Configured value / effect'], [
                ['Freshness', '30-second live lifetime; collection window 120 seconds does not extend this lifetime.'],
                ['Independent agreement', 'At least 3 distinct authenticated accounts; compatible delays within 60 seconds.'],
                ['Location checks', 'Within 250 m of the station; submitted uncertainty at most 100 m. Fixture uncertainty was 10 m.'],
                ['Duplicates', 'Same event ID is acknowledged as duplicate; it adds no new observation or contributor.'],
            ], [130, 381]),
        ]),
        ('Example 3: switch context and recover', [
            p('The DMRC outbound group contains 25 accounts. This table follows representative account 1 across the five recorded phases. Context describes configured geography; the source separately describes usable evidence.'),
            table(['Phase', 'Query origin', 'Context', 'Source', 'Baseline + wait = duration (s)'], phases,
                  [103, 96, 81, 53, 178]),
            note('Query origins advance by script. The shorter baseline in later rows reflects a different origin. This table does not show a train physically tracked between stations.'),
            h('Underground fallback in the reverse group'),
            p('For account 26, the reverse boundary query at Supreme Court used transition context and returned 353 + 360 = 713 seconds. After the query moved to underground Barakhamba Road, missing verified location left the 108-second static route to Rajiv Chowk active.'),
            p('The software can accept qualified crowd evidence in any zone. The underground fallback in this workload is caused by unavailable qualified phone evidence; it is not a rule that every underground report must be rejected.'),
            h('Expiry works without another report'),
            p('The expiry phase submitted zero reports. After the live evidence aged beyond 30 seconds, all 100 connected clients returned to static timing. Account 1 returned from 768 seconds to the 288-second stored baseline. Fresh recovery then produced 288 + 600 = 888 seconds.'),
            h('What is being estimated'),
            p('The delay is an additional station-service boarding wait and is counted once. The output does not identify a particular next train. Source selection at these geographic boundaries was tested; identified-train handover, motion estimation and cell-tower tracking were not tested.'),
            p('Use worked-journey-examples.csv (E1-E8) to find these exact examples and their original CSV row numbers. Rows count the header as row 1, matching Excel.'),
        ]),
        ('Measured results and panel explanation', [
            table(['Measure', 'Recorded result', 'Meaning'], [
                ['Unique report outcomes', '150 validated; 50 historical; 200 rejected', '400 total. All matched the injected labels.'],
                ['Journey checks', '500 / 500 matched', '20 distinct conditions, repeated over 100 clients.'],
                ['Source split', '250 static; 250 crowd', 'Fallback plus qualified overlay behavior.'],
                ['Expiry and duplicates', '100 / 100 fallbacks; 3 / 3 duplicates', 'Expired evidence removed; retries added no rows.'],
                ['HTTP acknowledgement p95', f"{result['http_ack_latency']['p95_ms'] / 1000:.3f} s", '400 unique report requests.'],
                ['Worker processing p95', f"{result['receipt_to_processing_latency']['p95_ms'] / 1000:.3f} s", 'Receipt to outcome for 400 reports.'],
                ['Crowd journey update p95', f"{result['observation_to_matching_journey_ws_latency']['p95_ms'] / 1000:.3f} s", '250 updates; includes harness completion barrier.'],
                ['Field ETA MAE / RMSE', 'Not measured', 'No independent real train arrival timestamps.'],
            ], [157, 145, 209]),
            h('Show these five things to the panel'),
            p('1. Operator timings: show the three Mandi House-to-Yamuna Bank segments. 2. Selected reports: compare fresh, historical and rejected examples. 3. Journey checks: show E1, E3, E4 and E6. 4. Offline demo: move through the five phases. 5. Summary: explain the software results and the remaining field test.'),
            h('A short explanation you can say'),
            note('Our project combines stored DMRC and NMRC travel times with fresh, nearby and agreeing crowd reports. We tested 100 simulated accounts with 400 reports and 500 journey checks. The software accepted qualified delays, excluded unsuitable reports, and returned to static timing when evidence expired. For example, a 405-second route plus a 360-second accepted wait became 765 seconds. This validates the software workflow; real passenger and train-arrival testing is the next step.'),
            p('Use the exact phrase "100 simulated accounts". A 100% software-check pass rate is not 100% ETA accuracy. This run did not use Prophet or Random Forest inference. The retained initial attempt had two transport failures; the completed run used bounded event-ID-safe retries and recorded no transport errors.'),
        ]),
    ]


def make_pdf(pages):
    PDF.parent.mkdir(parents=True, exist_ok=True)
    for name, filename in [('Guide', 'arial.ttf'), ('Guide-Bold', 'arialbd.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts') / filename)))
    pdfmetrics.registerFontFamily('Guide', normal='Guide', bold='Guide-Bold', italic='Guide', boldItalic='Guide-Bold')
    navy, teal, muted = '#123044', '#007F86', '#526576'
    base = ParagraphStyle('Body', fontName='Guide', fontSize=10, leading=14, textColor=colors.HexColor(navy), spaceAfter=9)
    heading = ParagraphStyle('Heading', parent=base, fontName='Guide-Bold', fontSize=13, leading=17, spaceBefore=8, spaceAfter=8)
    title = ParagraphStyle('Page title', parent=base, fontName='Guide-Bold', fontSize=24, leading=29, spaceAfter=15)
    cell = ParagraphStyle('Cell', parent=base, fontSize=8.4, leading=11.3, spaceAfter=0)
    th = ParagraphStyle('Table head', parent=cell, fontName='Guide-Bold', textColor=colors.white)
    callout = ParagraphStyle('Callout', parent=base, fontName='Guide-Bold', fontSize=10, leading=14.3,
                             backColor=colors.HexColor('#EAF6F4'), borderPadding=11, spaceBefore=6, spaceAfter=14)

    def para(text, style):
        return Paragraph(html.escape(text), style)

    story = []
    for index, (name, items) in enumerate(pages):
        if index:
            story.append(PageBreak())
        story.append(para(name, title))
        for item in items:
            kind = item[0]
            if kind in ('p', 'h', 'note'):
                story.append(para(item[1], {'p': base, 'h': heading, 'note': callout}[kind]))
            elif kind == 'table':
                _, headers, data, widths = item
                cells = [[para(x, th) for x in headers]] + [[para(str(x), cell) for x in row] for row in data]
                t = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(navy)),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                    ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F2F6F8'), colors.white]),
                    ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#DBE4E9')),
                ]))
                story += [t, Spacer(1, 11)]

    def decorate(canvas, doc):
        w, height = A4
        canvas.setFillColor(colors.HexColor(teal))
        canvas.rect(0, height - 10, w, 10, fill=1, stroke=0)
        canvas.setFont('Guide-Bold', 8)
        canvas.setFillColor(colors.HexColor(muted))
        canvas.drawString(42, height - 35, 'FINDMYMETRO  /  RECORDED DATASET AND WORKED EXAMPLES')
        canvas.setStrokeColor(colors.HexColor('#D5E1E7'))
        canvas.line(42, 39, w - 42, 39)
        canvas.setFont('Guide', 8)
        canvas.drawString(42, 25, 'Recorded run: 4 Nov 2026  |  100 simulated accounts  |  No human trial')
        canvas.drawRightString(w - 42, 25, f'{doc.page}')
    doc = SimpleDocTemplate(str(PDF), pagesize=A4, rightMargin=42, leftMargin=42,
                            topMargin=54, bottomMargin=52,
                            title='FindMyMetro Final Evaluation Dataset and Worked Examples',
                            author='FindMyMetro Project Team')
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    shutil.copy2(PDF, OUT / PDF.name)


def make_text_and_html(pages):
    markdown = ['# FindMyMetro final evaluation dataset', '']
    sections = []
    for title, items in pages:
        content = [f'<h2>{html.escape(title)}</h2>']
        markdown += [f'## {title}', '']
        for item in items:
            if item[0] == 'table':
                _, headers, rows, _ = item
                content.append('<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{html.escape(x)}</th>' for x in headers) + '</tr></thead><tbody>')
                content += ['<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in row) + '</tr>' for row in rows]
                content.append('</tbody></table></div>')
                markdown += ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|']
                markdown += ['| ' + ' | '.join(str(x).replace('|', '/') for x in row) + ' |' for row in rows]
                markdown.append('')
            else:
                tag = 'h3' if item[0] == 'h' else 'p'
                cls = ' class="note"' if item[0] == 'note' else ''
                content.append(f'<{tag}{cls}>{html.escape(item[1])}</{tag}>')
                markdown += [(('### ' if item[0] == 'h' else '> ' if item[0] == 'note' else '') + item[1]), '']
        sections.append('<section>' + ''.join(content) + '</section>')
    (OUT / 'DATASET_README.md').write_text('\n'.join(markdown), encoding='utf-8')
    links = [
        ('Printable guide', PDF.name), ('Excel results workbook', 'FindMyMetro_Evaluation_Data.xlsx'),
        ('Recorded interactive demo', 'recorded-experiment/panel-demo.html'),
        ('Eight journey examples', 'worked-journey-examples.csv'),
        ('Six report examples', 'selected-crowd-report-examples.csv'),
        ('All column definitions', 'DATA_DICTIONARY.csv'),
        ('400 report records', 'recorded-experiment/crowd-reports.csv'),
        ('500 journey checks', 'recorded-experiment/journey-context-results.csv'),
        ('281 operator segments', 'recorded-experiment/operator-baseline-segments.csv'),
    ]
    link_html = ''.join(f'<a href="{html.escape(path, quote=True)}">{html.escape(label)}</a>' for label, path in links)
    (OUT / 'START_HERE.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FindMyMetro final evaluation dataset</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf3f6;color:#173244;font:16px/1.6 system-ui,Arial,sans-serif}header{background:#123044;color:white;padding:36px max(22px,calc((100vw - 1040px)/2));}header p{max-width:900px;color:#d9e8ed}h1{font-size:32px;margin:0}main{max-width:1084px;margin:26px auto;padding:0 22px}section,nav{background:white;border:1px solid #d6e2e7;border-radius:15px;padding:25px 30px;margin:22px 0}h2{font-size:25px;margin:0 0 18px}h3{font-size:19px;margin:25px 0 10px}.note{padding:16px 18px;background:#eaf6f4;border-left:4px solid #00868c;border-radius:5px}nav{display:flex;flex-wrap:wrap;gap:10px}nav a{background:#eaf3f7;color:#123044;border:1px solid #bed4df;border-radius:7px;padding:9px 13px;text-decoration:none}nav a:hover{background:#d5ebe9}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;margin:16px 0}th,td{text-align:left;vertical-align:top;padding:12px 11px;border-bottom:1px solid #dce5ea}th{background:#123044;color:white}tbody tr:nth-child(odd){background:#f3f7f8}footer{color:#526576;margin:30px 0}@media(max-width:600px){section,nav{padding:20px}h1{font-size:27px}}@media print{body{background:white}nav{display:none}section{break-inside:avoid;border:0;padding:0;margin:20px 0}}
</style><header><h1>FindMyMetro final evaluation dataset</h1><p>Prepared 12 November 2026. Original experiment: 4 November 2026. Operator snapshot: 8 October 2026. Open this folder after extracting the ZIP; all pages and data are available offline.</p></header><main><nav>''' + link_html + '</nav>' + ''.join(sections) + '<footer>Original reports retain their timestamps. This saved dataset must not be presented as current passenger observations.</footer></main></html>', encoding='utf-8')


def copy_evidence():
    RECORDED.mkdir(parents=True, exist_ok=True)
    flat = list(FILES) + [
        'combined-results.json', 'crowd-reports.jsonl', 'journey-snapshots.jsonl',
        'operator-network-snapshot.json', 'operator-provenance-audit.json',
        'verification.json', 'source-code-fingerprints.json', 'runtime-packages.json',
        'panel-demo.html', 'README.md',
    ]
    copied = []
    for name in flat:
        shutil.copy2(SOURCE / name, RECORDED / name)
        assert sha(SOURCE / name) == sha(RECORDED / name)
        copied.append(name)
    for folder in ['operator-source-responses', 'reproduction', 'attempts']:
        shutil.copytree(SOURCE / folder, RECORDED / folder, dirs_exist_ok=True)
        for source in (SOURCE / folder).rglob('*'):
            if source.is_file():
                rel = source.relative_to(SOURCE)
                assert sha(source) == sha(RECORDED / rel)
                copied.append(rel.as_posix())
    workbook = ROOT / 'artifacts/evaluation-panel/FindMyMetro_Evaluation_Data.xlsx'
    shutil.copy2(workbook, OUT / workbook.name)
    assert sha(workbook) == sha(OUT / workbook.name)
    return copied, inspect_workbook(workbook)


def render_and_verify():
    import pypdfium2 as pdfium
    from pypdf import PdfReader
    reader = PdfReader(str(PDF))
    assert len(reader.pages) == 6, f'Expected six pages, got {len(reader.pages)}'
    expected = ['Final evaluation dataset', 'What to open and how to read it',
                'Example 1: build the static baseline', 'Example 2: accept useful reports',
                'Example 3: switch context and recover', 'Measured results and panel explanation']
    for page, title in zip(reader.pages, expected):
        assert title in page.extract_text(), (title, page.extract_text()[:100])
    document = pdfium.PdfDocument(str(PDF))
    from PIL import Image, ImageOps, ImageDraw
    thumbnails = []
    for i in range(len(document)):
        bitmap = document[i].render(scale=1.45)
        page = bitmap.to_pil().convert('RGB')
        page.save(QA / f'page-{i + 1}.png')
        thumb = ImageOps.contain(page, (390, 552))
        thumbnails.append(thumb)
    contact = Image.new('RGB', (3 * 410, 2 * 580), '#dce6eb')
    for i, thumb in enumerate(thumbnails):
        contact.paste(thumb, (10 + (i % 3) * 410, 10 + (i // 3) * 580))
    contact.save(QA / 'contact.png')
    return {'pdf_pages': 6, 'page_titles_match': True}


def make_manifest(rows, copied, workbook, render):
    manifest = {
        'prepared_date': PREPARED,
        'experiment_completed_at': read_json(SOURCE / 'combined-results.json')['completed_at'],
        'operator_snapshot': '8 October 2026',
        'new_trial_performed': False,
        'original_evidence_modified': False,
        'all_checks_passed': True,
        'copied_evidence_files': len(copied),
        'row_counts': {name: len(records) for name, records in rows.items()},
        'workbook': workbook,
        'render': render,
        'files': [{'path': p.relative_to(OUT).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
                  for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'DATASET_MANIFEST.json'],
    }
    (OUT / 'DATASET_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():
                bundle.write(p, Path('FindMyMetro_Final_Evaluation_Dataset') / p.relative_to(OUT))
    with zipfile.ZipFile(ZIP) as bundle:
        assert bundle.testzip() is None
        assert len(bundle.namelist()) == len([p for p in OUT.rglob('*') if p.is_file()])
    return manifest


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    rows, result, provenance = audit_original()
    examples, reports = make_examples(rows)
    write_csv(OUT / 'worked-journey-examples.csv', examples)
    write_csv(OUT / 'selected-crowd-report-examples.csv', reports)
    write_csv(OUT / 'DATA_DICTIONARY.csv', dictionary(rows))
    copied, workbook = copy_evidence()
    # Re-run the existing independent verifier against the copied evidence only.
    spec = importlib.util.spec_from_file_location('recorded_verifier', ROOT / 'scripts/verify_operator_crowd.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    verified = verifier.verify(RECORDED)
    assert verified['all_checks_passed']
    # Keep the original verification unchanged and store today's recomputation separately.
    shutil.copy2(RECORDED / 'verification.json', OUT / 'recomputed-verification.json')
    shutil.copy2(SOURCE / 'verification.json', RECORDED / 'verification.json')
    content = blocks(rows, result, provenance, examples, reports)
    make_text_and_html(content)
    make_pdf(content)
    render = render_and_verify()
    manifest = make_manifest(rows, copied, workbook, render)
    print(json.dumps({'zip': str(ZIP), 'zip_bytes': ZIP.stat().st_size, 'guide': str(PDF),
                      'start': str(OUT / 'START_HERE.html'), 'rows': manifest['row_counts'],
                      'examples': len(examples), 'report_examples': len(reports),
                      'all_checks_passed': True, 'pages': render['pdf_pages']}, indent=2))


if __name__ == '__main__':
    main()
