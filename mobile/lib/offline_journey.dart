import 'metro_api.dart';

Json offlineJourney(
  Json bundle,
  String origin,
  String destination,
  DateTime now,
) {
  final lines = List<Json>.from(bundle['lines'] ?? []);
  for (final line in lines) {
    final ids = List<String>.from(line['station_ids']);
    if (!ids.contains(origin) ||
        !ids.contains(destination) ||
        origin == destination) {
      continue;
    }
    final start = ids.indexOf(origin), end = ids.indexOf(destination);
    final direction = start < end ? 1 : -1;
    final segments = List<Json>.from(line['segments']);
    final steps = <Json>[];
    int duration = 0, distance = 0;
    for (int i = start; i != end; i += direction) {
      final segment = segments[direction == 1 ? i : i - 1];
      final seconds = (segment['seconds'] as num).round();
      steps.add({
        'kind': 'ride',
        'from_station_id': ids[i],
        'to_station_id': ids[i + direction],
        'line_id': line['id'],
        'context': segment['zone'],
        'seconds': seconds,
        'source': 'schedule',
        'delay_seconds': 0,
      });
      duration += seconds;
      distance += (segment['metres'] as num).round();
    }
    return {
      'routes': [
        {
          'id': 'offline-$origin-$destination',
          'steps': steps,
          'duration_seconds': duration,
          'transfers': 0,
          'walking_metres': 0,
          'distance_metres': distance,
          'source': 'schedule',
          'delay_seconds': 0,
          'station_count': steps.length + 1,
          'source_statuses': <Json>[],
        },
      ],
      'origin': origin,
      'destination': destination,
      'generated_at': now.toUtc().toIso8601String(),
      'network_version': bundle['network_version'],
      'offline': true,
      'timing_note': 'Offline operator travel-time estimate. Ordinary boarding wait, security and access time are additional. No live delay is carried into this estimate.',
    };
  }
  return {
    'routes': <Json>[],
    'reason': origin == destination
        ? 'already_at_destination'
        : 'outside_offline_aqua_coverage',
    'offline': true,
  };
}
