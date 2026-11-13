import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'metro_api.dart';

class PhoneEvidence {
  static const channel = MethodChannel('findmymetro/phone_context');
  static Future<Json> read() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) {
      return {'status': 'android_required', 'cells': <Json>[]};
    }
    try {
      final value = await channel.invokeMapMethod<String, dynamic>('readCells');
      final result = Map<String, dynamic>.from(value ?? {});
      final cells = (result['cells'] as List? ?? [])
          .map((cell) => Map<String, dynamic>.from(cell as Map))
          .where(
            (cell) =>
                cell['age_ms'] is num &&
                cell['age_ms'] >= 0 &&
                cell['age_ms'] < 30000,
          )
          .toList();
      final age = cells.fold<int>(
        0,
        (age, cell) => (cell['age_ms'] as num).toInt() > age
            ? (cell['age_ms'] as num).toInt()
            : age,
      );
      return {
        ...result,
        'cells': cells,
        'observed_at': DateTime.now()
            .toUtc()
            .subtract(Duration(milliseconds: age))
            .toIso8601String(),
      };
    } on PlatformException catch (error) {
      return {'status': error.code, 'cells': <Json>[]};
    } on MissingPluginException {
      return {'status': 'android_required', 'cells': <Json>[]};
    }
  }
}
