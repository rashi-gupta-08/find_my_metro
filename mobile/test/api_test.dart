import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:find_my_metro_mobile/metro_api.dart';

void main() {
  test('Session and CSRF accompany an unchanged offline observation', () async {
    final calls = <http.Request>[];
    final api = MetroApi(
      base: Uri.parse('http://localhost:5174'),
      client: MockClient((request) async {
        calls.add(request);
        if (request.url.path.endsWith('/login')) {
          return http.Response(
            jsonEncode({
              'user': {'id': 'person'},
              'csrf_token': 'bound-token',
            }),
            200,
            headers: {'set-cookie': 'metro_session=private; HttpOnly; Path=/'},
          );
        }
        return http.Response(
          jsonEncode({
            'acknowledgements': [
              {'index': 0, 'status': 'queued'},
            ],
          }),
          202,
        );
      }),
    );
    await api.authenticate('login', {
      'username': 'person',
      'password': 'example-password',
    });
    await api.request(
      '/api/v1/crowd-reports/batch',
      body: {
        'reports': [
          {
            'observed_at': '2026-10-08T08:00:00Z',
            'event_id': 'original-offline-event',
          },
        ],
      },
    );
    expect(calls.last.headers['Cookie'], 'metro_session=private');
    expect(calls.last.headers['X-CSRF-Token'], 'bound-token');
    expect(
      jsonDecode(calls.last.body)['reports'][0]['observed_at'],
      '2026-10-08T08:00:00Z',
    );
    api.close();
  });
  test('A rejected request does not become successful delivery', () async {
    final api = MetroApi(
      client: MockClient(
        (_) async => http.Response('{"detail":"Sign in to continue"}', 401),
      ),
    );
    await expectLater(
      api.request('/api/v1/crowd-reports/batch', body: {'reports': []}),
      throwsA(isA<ApiFailure>().having((error) => error.status, 'status', 401)),
    );
    api.close();
  });
}
