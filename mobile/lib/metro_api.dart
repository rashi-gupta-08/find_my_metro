import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'transport.dart';

typedef Json = Map<String, dynamic>;

class ApiFailure implements Exception {
  final int status;
  final String message;
  const ApiFailure(this.status, this.message);
  @override
  String toString() => message;
}

class MetroApi {
  final http.Client client;
  final Uri base;
  String? cookie, csrf;
  Json? user;
  MetroApi({http.Client? client, Uri? base})
    : client = client ?? createClient(),
      base = base ?? defaultBase();
  static Uri defaultBase() {
    const configured = String.fromEnvironment('API_BASE');
    if (configured.isNotEmpty) return Uri.parse(configured);
    return kIsWeb
        ? Uri.parse(Uri.base.origin)
        : Uri.parse('http://localhost:5173');
  }

  Uri uri(String path) => base.resolve(path);
  Uri socket(String station) =>
      uri('/ws/eta/${Uri.encodeComponent(station)}')
          .replace(scheme: base.scheme == 'https' ? 'wss' : 'ws');
  Future<Json> request(String path, {Json? body}) async {
    final headers = <String, String>{};
    if (!kIsWeb) {
      if (cookie != null) headers['Cookie'] = cookie!;
      headers['Origin'] = const String.fromEnvironment(
        'API_ORIGIN',
        defaultValue: 'http://localhost:5173',
      );
    }
    if (body != null) {
      headers['Content-Type'] = 'application/json';
      if (csrf != null) headers['X-CSRF-Token'] = csrf!;
    }
    final response =
        await (body == null
                ? client.get(uri(path), headers: headers)
                : client.post(
                    uri(path),
                    headers: headers,
                    body: jsonEncode(body),
                  ))
            .timeout(const Duration(seconds: 8));
    if (!kIsWeb && response.headers['set-cookie'] != null) {
      cookie = response.headers['set-cookie']!.split(';').first;
    }
    Json value;
    try {
      value = jsonDecode(response.body) as Json;
    } catch (_) {
      throw const ApiFailure(503, 'The service is temporarily unavailable.');
    }
    if (response.statusCode >= 400) {
      throw ApiFailure(
        response.statusCode,
        value['detail'] is String
            ? value['detail'] as String
            : 'Check the entered details (${response.statusCode}).',
      );
    }
    return value;
  }

  Future<void> restoreAccount() async {
    final value = await request('/api/v1/auth/me');
    user = value['user'] as Json?;
    csrf = value['csrf_token'] as String?;
  }

  Future<void> authenticate(String kind, Json body) async {
    final value = await request('/api/v1/auth/$kind', body: body);
    user = value['user'] as Json?;
    csrf = value['csrf_token'] as String?;
  }

  Future<void> logout() async {
    await request('/api/v1/auth/logout', body: {});
    user = null;
    csrf = null;
    cookie = null;
  }

  void close() => client.close();
}
