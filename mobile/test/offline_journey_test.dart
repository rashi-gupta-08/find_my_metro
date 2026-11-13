import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:find_my_metro_mobile/offline_journey.dart';
import 'package:find_my_metro_mobile/phone_context.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final bundle = jsonDecode(
    File('assets/aqua-offline.json').readAsStringSync(),
  ) as Map<String, dynamic>;
  test('All 21 Aqua stations route offline in both directions without a fabricated live delay', () {
    final ids = List<String>.from(bundle['lines'][0]['station_ids']);
    expect(ids.length, 21);
    for (final a in ids) {
      for (final b in ids.where((id) => id != a)) {
        final route = offlineJourney(
          bundle,
          a,
          b,
          DateTime.utc(2026, 10, 16),
        )['routes'][0];
        final steps = List<Map<String, dynamic>>.from(route['steps']);
        expect(steps.first['from_station_id'], a);
        expect(steps.last['to_station_id'], b);
        expect(
          route['duration_seconds'],
          steps.fold<int>(0, (n, s) => n + (s['seconds'] as int)),
        );
        expect(route['delay_seconds'], 0);
        expect(route['transfers'], 0);
        expect(route['source'], 'schedule');
      }
    }
  });
  test('Outside offline coverage is explicit and cells remain unavailable off Android', () async {
    expect(
      offlineJourney(bundle, 'dmrc-rck', 'nmrc-1', DateTime.now())['reason'],
      'outside_offline_aqua_coverage',
    );
    expect((await PhoneEvidence.read())['cells'], isEmpty);
  });
  test('Android bridge discards stale cache entries and retains the original sample age', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          PhoneEvidence.channel,
          (MethodCall call) async => {
            'status': 'available',
            'cells': [
              {'fingerprint': 'fresh-cell', 'age_ms': 5000},
              {'fingerprint': 'old-cell', 'age_ms': 31000},
            ],
          },
        );
    try {
      final value = await PhoneEvidence.read();
      expect((value['cells'] as List).length, 1);
      final age = DateTime.now().toUtc().difference(
        DateTime.parse(value['observed_at']),
      );
      expect(age.inMilliseconds, inInclusiveRange(5000, 6000));
    } finally {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(PhoneEvidence.channel, null);
      debugDefaultTargetPlatformOverride = null;
    }
  });
}
