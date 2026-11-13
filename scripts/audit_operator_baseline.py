"""Export the frozen operator catalogue and verify every stored segment time.

Reads archived public responses; does not refresh or modify the passenger network.
This verifies transcription/provenance, not current field travel-time accuracy.
"""
import argparse
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit(output):
    output = Path(output)
    evidence = output / 'operator-source-responses'
    evidence.mkdir(parents=True, exist_ok=True)
    network_path = ROOT / 'data/operator-network.json'
    network = json.loads(network_path.read_text(encoding='utf-8'))
    stations = {s['id']: s for s in network['stations']}
    rows = []
    for line in network['lines']:
        for index, segment in enumerate(line['segments']):
            a, b = line['station_ids'][index:index+2]
            if line['operator_id'] == 'dmrc':
                first, last = sorted([a[5:].upper(), b[5:].upper()])
                archive = ROOT / f'.local/research/timings/{first}-{last}.json'
                response = json.loads(archive.read_text(encoding='utf-8'))
                legs = response.get('route', [])
                matched = [leg for leg in legs if leg.get('map-path') in [[first+'-'+last], [last+'-'+first]]]
                if len(legs) != 1 or len(matched) != 1:
                    raise ValueError(f'Unverified adjacency {a} {b}')
                value = matched[0]['path_time']
                h, m, s = map(int, value.split(':'))
                parsed = h*3600+m*60+s
                url = f'https://backend.delhimetrorail.com/api/v2/en/station_route/{first}/{last}/least-distance/2026-10-08T12:00:00.000'
            else:
                first, last = int(a[5:]), int(b[5:])
                archive = ROOT / f'.local/research/timings/nmrc-{first}-{last}.html'
                response = html.unescape(re.sub('<[^>]+>', ' ', archive.read_text(encoding='utf-8')))
                value = re.search(r'Timing:\s*([\d.]+)\s*Min', re.sub(r'\s+', ' ', response))[1]
                parsed = round(float(value)*60)
                parameter = (ROOT / f'.local/research/timings/nmrc-param-{first}.json').read_text(encoding='utf-8').strip('"')
                url = 'https://www.nmrcnoida.com/Passenger-Information/Journey-Planner-and-Fares?' + urlencode({'id': parameter})
            shutil.copy2(archive, evidence / archive.name)
            rows.append({'operator': line['operator_id'].upper(), 'line_id': line['id'], 'line_name': line['name'],
                'segment_index': index, 'from_station_id': a, 'from_station': stations[a]['name'],
                'to_station_id': b, 'to_station': stations[b]['name'], 'configured_context': segment['zone'],
                'baseline_seconds': segment['seconds'], 'source_value': value, 'parsed_source_seconds': parsed,
                'matches_archived_source': segment['seconds'] == parsed, 'timing_source': segment['timing_source'],
                'source_url': url, 'catalogue_snapshot_at': network['published_at'],
                'source_archive': 'operator-source-responses/'+archive.name, 'source_sha256': digest(archive),
                'review_flag': 'unusually_short_under_30s' if parsed < 30 else 'unusually_long_over_360s' if parsed > 360 else ''})
    write_csv(output / 'operator-baseline-segments.csv', rows)
    write_csv(output / 'operator-stations.csv', network['stations'])
    shutil.copy2(network_path, output / 'operator-network-snapshot.json')
    summary = {'catalogue_version': network['version'], 'catalogue_snapshot_at': network['published_at'],
        'network_sha256': digest(network_path), 'stations': len(stations), 'ordered_line_paths': len(network['lines']),
        'segment_records': len(rows), 'operator_segments': dict(Counter(r['operator'] for r in rows)),
        'configured_contexts': dict(Counter(r['configured_context'] for r in rows)),
        'verified_against_archived_source': sum(r['matches_archived_source'] for r in rows),
        'unique_source_responses': len({r['source_archive'] for r in rows}),
        'source_mismatches': [r for r in rows if not r['matches_archived_source']],
        'review_flags': [r for r in rows if r['review_flag']],
        'scope': 'Frozen indicative operator travel times; source transcription audit, not real-time or field validation.',
        'notes': ['Source responses were archived for the 8 October 2026 import; this audit does not refresh them.',
            'DMRC timings are not uniformly 120 seconds. All 20 stored NMRC adjacent segments are 120 seconds.',
            'Configured zones inherit station-level layout. Multi-line interchange platforms require separate field review.',
            'Transfer walking time/distance are application estimates, excluded from operator ride-time provenance counts.',
            'NMRC coordinates use a historical OTD mirror; timing values use NMRC planner responses.',
            'Both directions reuse the stored adjacent segment time; directional or daily service differences are not measured.']}
    (output / 'operator-provenance-audit.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/operator-crowd-100-users')
    result = audit(parser.parse_args().output)
    print(json.dumps({k: v for k, v in result.items() if k not in {'review_flags', 'notes'}}, indent=2))
    if result['source_mismatches']:
        raise SystemExit(1)
