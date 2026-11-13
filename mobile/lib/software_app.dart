import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'metro_api.dart';
import 'metro_app.dart' show AccountSheet;
import 'offline_journey.dart';
import 'phone_context.dart';

void main() => runApp(const SoftwareMetroApp());
const teal = Color(0xff138f87), navy = Color(0xff0b2d40);

class SoftwareMetroApp extends StatelessWidget {
  const SoftwareMetroApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'FindMyMetro',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'MetroSans',
      colorScheme: ColorScheme.fromSeed(seedColor: teal),
      scaffoldBackgroundColor: const Color(0xfff4f7f8),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
    ),
    home: const SoftwareMetroHome(),
  );
}

class SoftwareMetroHome extends StatefulWidget {
  const SoftwareMetroHome({super.key});
  @override
  State<SoftwareMetroHome> createState() => _HomeState();
}

class _HomeState extends State<SoftwareMetroHome> {
  final api = MetroApi();
  SharedPreferences? storage;
  Json? network, bundle, journey, rewards, phone;
  List<Json> reports = [], queue = [];
  String origin = '',
      destination = '',
      scope = 'aqua',
      preference = 'fastest',
      message = '';
  bool connected = false,
      busy = false,
      reportBusy = false,
      searching = false,
      hasJourney = false;
  int epoch = 0, tick = 0, snapshotVersion = 0;
  Timer? timer;
  WebSocketChannel? socket;
  StreamSubscription<dynamic>? subscription;
  List<Json> get stations =>
      List<Json>.from(network?['stations'] ?? bundle?['stations'] ?? [])
          .where(
            (s) => scope == 'all' || s['id'].toString().startsWith('nmrc-'),
          )
          .toList();
  List<Json> get lines =>
      List<Json>.from(network?['lines'] ?? bundle?['lines'] ?? []);
  String name(dynamic id) =>
      List<Json>.from(network?['stations'] ?? bundle?['stations'] ?? [])
          .firstWhere(
            (s) => s['id'] == id,
            orElse: () => {'name': id ?? ''},
          )['name']
          .toString();
  String get owner => api.user?['id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    initialize();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      tick++;
      setState(() {});
      if (tick % 5 == 0) {
        refreshPrivate();
        if (hasJourney && socket == null) findJourney();
      }
      if (tick % 15 == 0 && queue.isNotEmpty) flushQueue();
    });
  }

  Future<void> initialize() async {
    storage = await SharedPreferences.getInstance();
    bundle = jsonDecode(
      await rootBundle.loadString('assets/aqua-offline.json'),
    ) as Json;
    try {
      network =
          jsonDecode(storage!.getString('software-network') ?? 'null') as Json?;
    } catch (_) {}
    defaults();
    if (mounted) setState(() {});
    try {
      final fresh = await api.request('/api/v1/network');
      if (!mounted) return;
      network = fresh;
      connected = true;
      defaults();
      await storage!.setString('software-network', jsonEncode(network));
      bundle = await api.request('/api/v1/offline-bundle');
      await api.restoreAccount();
      loadQueue();
      await refreshPrivate();
    } catch (_) {
      connected = false;
    }
    if (mounted) setState(() {});
  }

  void defaults() {
    if (stations.isEmpty) return;
    if (!stations.any((s) => s['id'] == origin)) origin = stations.first['id'];
    if (!stations.any((s) => s['id'] == destination)) {
      destination = stations.last['id'];
    }
  }

  Future<void> account() async {
    final previous = owner;
    await showDialog<void>(
      context: context,
      builder: (_) => AccountSheet(api: api),
    );
    if (!mounted) return;
    if (owner != previous) {
      reports = [];
      rewards = null;
      phone = null;
    }
    loadQueue();
    await refreshPrivate();
    if (mounted) setState(() {});
  }

  Future<void> signOut() async {
    final previous = owner;
    try {
      await api.logout();
      await storage?.remove('service-queue:$previous');
      queue = [];
      reports = [];
      rewards = null;
      phone = null;
      if (mounted) {
        setState(
          () => message =
              'Signed out. Private reports were cleared from this device.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    }
  }

  void loadQueue() {
    try {
      queue = owner.isEmpty
          ? []
          : List<Json>.from(
                  jsonDecode(
                    storage?.getString('service-queue:$owner') ?? '[]',
                  ),
                )
                .where((r) {
                  final age = DateTime.now()
                      .toUtc()
                      .difference(DateTime.parse(r['observed_at']))
                      .inSeconds;
                  return age >= -5 && age < 86400;
                })
                .take(100)
                .toList();
    } catch (_) {
      queue = [];
    }
  }

  Future<void> refreshPrivate() async {
    if (owner.isEmpty || busy) return;
    busy = true;
    final currentOwner = owner;
    try {
      final result = await api.request('/api/v1/reports/mine');
      final points = await api.request('/api/v1/contributions/mine');
      if (!mounted || currentOwner != owner) return;
      reports = List<Json>.from(result['reports']);
      rewards = points;
    } catch (_) {
      /* Retain private outcomes without relabelling them as fresh. */
    } finally {
      busy = false;
      if (mounted) setState(() {});
    }
  }

  String get query => Uri(
    queryParameters: {
      'origin': origin,
      'destination': destination,
      'preference': preference,
    },
  ).query;
  Future<void> findJourney({bool reconnect = false}) async {
    if (origin.isEmpty || destination.isEmpty || searching) return;
    searching = true;
    hasJourney = true;
    final requestEpoch = epoch,
        selectedOrigin = origin,
        selectedDestination = destination,
        selectedPreference = preference;
    try {
      final value = await api.request('/api/v1/routes?$query');
      if (!mounted ||
          requestEpoch != epoch ||
          origin != selectedOrigin ||
          destination != selectedDestination ||
          preference != selectedPreference) {
        return;
      }
      journey = value;
      connected = true;
      snapshotVersion = (value['snapshot_version'] as num? ?? 0).toInt();
      if (socket == null || reconnect) connectJourney();
    } catch (_) {
      if (!mounted || requestEpoch != epoch) return;
      connected = false;
      journey = offlineJourney(bundle!, origin, destination, DateTime.now());
    } finally {
      searching = false;
      if (mounted) setState(() {});
    }
  }

  void connectJourney() {
    subscription?.cancel();
    socket?.sink.close();
    final requestEpoch = epoch;
    final endpoint = api
        .uri('/ws/journeys?$query')
        .replace(scheme: api.base.scheme == 'https' ? 'wss' : 'ws');
    socket = WebSocketChannel.connect(endpoint);
    subscription = socket!.stream.listen(
      (frame) {
        try {
          final value = jsonDecode(frame.toString()) as Json;
          final version = (value['snapshot_version'] as num? ?? 0).toInt();
          if (mounted &&
              epoch == requestEpoch &&
              value['type'] == 'journey_snapshot' &&
              value['origin'] == origin &&
              value['destination'] == destination &&
              value['preference'] == preference &&
              version >= snapshotVersion) {
            setState(() {
              journey = value;
              snapshotVersion = version;
              connected = true;
            });
          }
        } catch (_) {}
      },
      onError: (_) => disconnected(requestEpoch),
      onDone: () => disconnected(requestEpoch),
    );
  }

  void disconnected(int requestEpoch) {
    if (!mounted || requestEpoch != epoch) return;
    socket = null;
    setState(() {
      connected = false;
      journey = offlineJourney(bundle!, origin, destination, DateTime.now());
    });
  }

  void change(void Function() action) {
    epoch++;
    subscription?.cancel();
    socket?.sink.close();
    socket = null;
    snapshotVersion = 0;
    setState(() {
      action();
      defaults();
      journey = null;
      hasJourney = false;
    });
  }

  Future<void> permission() async {
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw Exception(
        'Location permission is needed. Static route planning remains available.',
      );
    }
  }

  Future<Json> readPhone() async {
    await permission();
    final reading = await PhoneEvidence.read();
    final cells = List<Json>.from(reading['cells'] ?? []);
    if (cells.isEmpty) return {...reading, 'station_id': null};
    final fingerprints = cells.map((c) => c['fingerprint'] as String).toList();
    if (owner.isEmpty) return {'status': 'sign_in_required', 'cells': cells};
    final result = await api.request(
      '/api/v1/phone-context',
      body: {
        'observed_at': reading['observed_at'],
        'fingerprints': fingerprints,
        'route_station_ids':
            journey != null && (journey!['routes'] as List).isNotEmpty
            ? (List<Json>.from(journey!['routes'][0]['steps'])
                  .expand(
                    (s) => [
                      s['from_station_id'] as String,
                      s['to_station_id'] as String,
                    ],
                  )
                  .toSet()
                  .toList())
            : [origin],
      },
    );
    return {...result, 'cells': cells, 'cell_fingerprints': fingerprints};
  }

  Future<void> checkPhone() async {
    if (owner.isEmpty) {
      await account();
      return;
    }
    try {
      final result = await readPhone();
      if (mounted) setState(() => phone = result);
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    }
  }

  Future<void> submitReport() async {
    if (owner.isEmpty) {
      await account();
      return;
    }
    if (queue.length >= 100) {
      setState(
        () => message =
            'The local queue is full. Upload or remove old reports first.',
      );
      return;
    }
    final reportStation = origin;
    final serving = lines
        .where((l) => List.from(l['station_ids']).contains(reportStation))
        .toList();
    if (serving.isEmpty) return;
    String lineId = serving.first['id'],
        direction = 'outbound',
        kind = 'delayed';
    final extraWait = TextEditingController(text: '5');
    final form = GlobalKey<FormState>();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: Text('Update at ${name(reportStation)}'),
          content: SingleChildScrollView(
            child: Form(
              key: form,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  DropdownButtonFormField<String>(
                    initialValue: lineId,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Line'),
                    items: serving
                        .map(
                          (l) => DropdownMenuItem(
                            value: l['id'] as String,
                            child: Text(
                              l['name'],
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: (v) => update(() => lineId = v!),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: direction,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Direction'),
                    items: ['outbound', 'inbound'].map((d) {
                      final ids = List<String>.from(
                        serving.firstWhere(
                          (l) => l['id'] == lineId,
                        )['station_ids'],
                      );
                      return DropdownMenuItem(
                        value: d,
                        child: Text(
                          'Towards ${name(d == 'outbound' ? ids.last : ids.first)}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      );
                    }).toList(),
                    onChanged: (v) => update(() => direction = v!),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: kind,
                    decoration: const InputDecoration(labelText: 'Update type'),
                    items: ['delayed', 'arrived', 'departed', 'crowded']
                        .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                        .toList(),
                    onChanged: (v) => update(() => kind = v!),
                  ),
                  if (kind == 'delayed')
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: TextFormField(
                        controller: extraWait,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Observed extra wait (minutes)',
                        ),
                        validator: (v) {
                          final n = int.tryParse(v ?? '');
                          return n == null || n < 0 || n > 60
                              ? 'Enter 0–60 minutes'
                              : null;
                        },
                      ),
                    ),
                  const SizedBox(height: 12),
                  const Text(
                    'One-time location check. Three independent accounts must agree while every report is less than 30 seconds old.',
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                if (form.currentState!.validate()) Navigator.pop(context, true);
              },
              child: const Text('Check location and send'),
            ),
          ],
        ),
      ),
    );
    final delay = int.tryParse(extraWait.text) ?? 0;
    // The dialog may still be completing its route animation when it closes.
    if (accepted != true || !mounted) return;
    final currentOwner = owner;
    setState(() => reportBusy = true);
    try {
      await permission();
      Json location;
      try {
        final fix = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high,
            timeLimit: Duration(seconds: 12),
          ),
        );
        if (fix.accuracy > 100 ||
            DateTime.now()
                    .toUtc()
                    .difference(fix.timestamp.toUtc())
                    .inSeconds >=
                30) {
          throw Exception('Usable location unavailable');
        }
        location = {
          'latitude': fix.latitude,
          'longitude': fix.longitude,
          'accuracy_m': fix.accuracy,
          'observed_at': fix.timestamp.toUtc().toIso8601String(),
        };
      } catch (_) {
        final reading = await readPhone();
        if (reading['station_id'] != reportStation ||
            (reading['accuracy_m'] as num? ?? 251) > 100) {
          throw Exception(
            'Your location could not confirm this station. Try again with a stronger signal; the static route estimate remains available.',
          );
        }
        location = {
          'cell_fingerprints': reading['cell_fingerprints'],
          'observed_at': reading['observed_at'],
        };
      }
      if (!mounted || owner != currentOwner || owner.isEmpty) return;
      queue.add({
        'event_id':
            'phone-${DateTime.now().microsecondsSinceEpoch}-${Random.secure().nextInt(1 << 32).toRadixString(16)}',
        'station_id': reportStation,
        'line_id': lineId,
        'direction': direction,
        'event_type': kind,
        'delay_seconds': kind == 'delayed' ? delay * 60 : 0,
        'note': '',
        ...location,
      });
      await storage?.setString('service-queue:$owner', jsonEncode(queue));
      await flushQueue();
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => reportBusy = false);
    }
  }

  bool uploading = false;
  Future<void> flushQueue() async {
    if (queue.isEmpty || owner.isEmpty || uploading) return;
    uploading = true;
    final currentOwner = owner;
    try {
      final batch = queue.take(20).toList();
      final result = await api.request(
        '/api/v1/reports/batch',
        body: {'reports': batch},
      );
      if (!mounted || owner != currentOwner) return;
      final settled = List<Json>.from(result['acknowledgements'])
          .where(
            (a) => [
              'queued',
              'duplicate',
              'rejected',
              'conflict',
            ].contains(a['status']),
          )
          .map((a) => a['client_event_id'])
          .toSet();
      queue.removeWhere((r) => settled.contains(r['event_id']));
      await storage?.setString('service-queue:$owner', jsonEncode(queue));
      message = 'Reports uploaded for validation. View your processing outcomes below.';
      await refreshPrivate();
    } catch (_) {
      if (mounted && owner == currentOwner) {
        setState(
          () => message = 'Saved on this device. Retry keeps the original event ID and observation time. Reports older than 30 seconds cannot change live delays.',
        );
      }
    } finally {
      uploading = false;
      if (mounted) setState(() {});
    }
  }

  Widget card(Widget child) => Card(
    child: Padding(padding: const EdgeInsets.all(18), child: child),
  );
  Widget selector(String label, String value, ValueChanged<String> update) =>
      DropdownButtonFormField<String>(
        key: ValueKey('$label:$value:$scope'),
        initialValue: stations.any((s) => s['id'] == value) ? value : null,
        isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: stations
            .map(
              (s) => DropdownMenuItem(
                value: s['id'] as String,
                child: Text(s['name'], overflow: TextOverflow.ellipsis),
              ),
            )
            .toList(),
        onChanged: (v) {
          if (v != null) change(() => update(v));
        },
      );

  Widget routeCard(Json route) {
    final statuses = List<Json>.from(route['source_statuses'] ?? []);
    final expired = statuses.any(
      (s) =>
          s['valid_until'] != null &&
          !DateTime.now().toUtc().isBefore(DateTime.parse(s['valid_until'])),
    );
    final delay = (route['delay_seconds'] as num? ?? 0).round();
    final seconds =
        (route['duration_seconds'] as num).round() -
        (expired || !connected ? delay : 0);
    return card(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${(seconds / 60).ceil()} min · ${route['transfers']} interchanges',
            style: const TextStyle(fontSize: 23, fontWeight: FontWeight.bold),
          ),
          Text(
            '${route['walking_metres'] ?? 0} m estimated walking · ${route['station_count']} stations',
          ),
          Text(
            connected && !expired && delay > 0
                ? 'Includes ${(delay / 60).ceil()} min confirmed extra wait, counted once at boarding'
                : 'Static travel-time estimate',
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('All stations and source details'),
            children: [
              ...List<Json>.from(route['steps']).map(
                (s) => ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    s['kind'] == 'transfer'
                        ? Icons.directions_walk
                        : Icons.train_outlined,
                  ),
                  title: Text(
                    '${name(s['from_station_id'])} → ${name(s['to_station_id'])}',
                  ),
                  subtitle: Text(
                    s['kind'] == 'transfer'
                        ? '${s['walking_metres']} m walking estimate'
                        : '${s['context']} · operator segment time',
                  ),
                ),
              ),
              ...statuses.map(
                (s) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(
                    '${name(s['boarding_station_id'])}: ${connected && !expired && s['source'] != 'schedule' ? 'Community evidence' : 'Static baseline'}',
                  ),
                  subtitle: Text(
                    s['last_observed_at'] == null
                        ? 'No qualified live evidence'
                        : 'Observed ${DateTime.now().toUtc().difference(DateTime.parse(s['last_observed_at'])).inSeconds.clamp(0, 999999)}s ago · heuristic trust ${s['trust_score']}',
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  String phoneMessage() {
    final reading = phone;
    if (reading == null) return '';
    if (reading['station_id'] == null) {
      if (reading['status'] == 'android_required') {
        return 'Phone signal checks are available in the Android app. Use station search here.';
      }
      return 'Phone signal could not locate your station. Choose it manually; travel times use static estimates.';
    }
    if (reading['expires_at'] != null &&
        !DateTime.now().toUtc().isBefore(
          DateTime.parse(reading['expires_at']),
        )) {
      return 'This station hint has expired. Choose your station or check again.';
    }
    return 'Station hint: ${name(reading['station_id'])}. Confirm your station before reporting; this does not identify a train.';
  }

  @override
  Widget build(BuildContext context) {
    final routes = List<Json>.from(journey?['routes'] ?? []);
    final rerouting = journey?['rerouting'] as Json?;
    final freshDelay =
        connected &&
        rerouting?['valid_until'] != null &&
        DateTime.now().toUtc().isBefore(
          DateTime.parse(rerouting!['valid_until']),
        );
    return Scaffold(
      appBar: AppBar(
        title: const Text('FindMyMetro'),
        actions: [
          IconButton(
            tooltip: owner.isEmpty ? 'Sign in' : 'Sign out',
            onPressed: owner.isEmpty ? account : signOut,
            icon: Icon(owner.isEmpty ? Icons.person_outline : Icons.logout),
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 800),
          child: ListView(
            padding: const EdgeInsets.all(18),
            children: [
              const Text(
                'Your station. Your best route.',
                style: TextStyle(
                  fontSize: 30,
                  fontWeight: FontWeight.bold,
                  color: navy,
                ),
              ),
              const Text(
                'Compare time, interchanges and walking. Station updates from nearby passengers.',
              ),
              const SizedBox(height: 18),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'aqua', label: Text('Aqua · Phase 1')),
                  ButtonSegment(value: 'all', label: Text('Delhi + Noida')),
                ],
                selected: {scope},
                onSelectionChanged: (v) => change(() => scope = v.first),
              ),
              const SizedBox(height: 18),
              if (stations.isNotEmpty) ...[
                selector('Source station', origin, (v) => origin = v),
                const SizedBox(height: 14),
                selector(
                  'Destination station',
                  destination,
                  (v) => destination = v,
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<String>(
                  initialValue: preference,
                  decoration: const InputDecoration(
                    labelText: 'Route preference',
                  ),
                  items: const [
                    DropdownMenuItem(
                      value: 'fastest',
                      child: Text('Shortest time'),
                    ),
                    DropdownMenuItem(
                      value: 'fewest_changes',
                      child: Text('Fewer interchanges'),
                    ),
                    DropdownMenuItem(
                      value: 'least_walking',
                      child: Text('Less walking'),
                    ),
                    DropdownMenuItem(
                      value: 'shortest_distance',
                      child: Text('Shortest distance'),
                    ),
                  ],
                  onChanged: (v) => change(() => preference = v!),
                ),
                const SizedBox(height: 14),
                FilledButton.icon(
                  onPressed: searching || origin == destination
                      ? null
                      : () => findJourney(reconnect: true),
                  icon: const Icon(Icons.route),
                  label: Text(searching ? 'Finding routes…' : 'Find my route'),
                ),
              ],
              if (message.isNotEmpty) card(Text(message)),
              if (journey != null)
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    connected
                        ? 'Journey updates connected · live evidence expires after 30s'
                        : 'Offline Aqua estimate · no live tracking',
                  ),
                ),
              if (freshDelay && rerouting['status'] == 'alternative_suggested')
                card(
                  Text(
                    'A validated delay exceeds 3 minutes. The faster alternative saves ${((rerouting['saving_seconds'] as num) / 60).floor()} minutes.',
                  ),
                ),
              if (freshDelay && rerouting['status'] == 'no_faster_alternative')
                card(
                  const Text(
                    'Delay confirmed. No faster metro alternative is available; keep this route and allow extra time.',
                  ),
                ),
              ...routes.map(routeCard),
              if (journey != null && routes.isEmpty)
                card(
                  Text(
                    journey?['reason'] == 'outside_offline_aqua_coverage'
                        ? 'Offline planning is bundled for all 21 Aqua Line stations. Reconnect for Delhi routes.'
                        : 'No valid alternative is available for these stations.',
                  ),
                ),
              if (routes.isNotEmpty)
                card(
                  Text(
                    journey?['timing_note'] ?? 'Operator running time plus estimated transfers. Ordinary boarding wait, security and station access are additional.',
                  ),
                ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: reportBusy ? null : submitReport,
                icon: const Icon(Icons.add_location_alt_outlined),
                label: Text(
                  reportBusy
                      ? 'Checking location…'
                      : 'Report at ${name(origin)}',
                ),
              ),
              OutlinedButton.icon(
                onPressed: checkPhone,
                icon: const Icon(Icons.cell_tower),
                label: const Text('Check underground phone signal'),
              ),
              if (phone != null) card(Text(phoneMessage())),
              if (queue.isNotEmpty)
                TextButton(
                  onPressed: flushQueue,
                  child: Text('Retry ${queue.length} queued reports'),
                ),
              if (rewards != null)
                card(
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${rewards!['points']} contribution points',
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 20,
                        ),
                      ),
                      Text(List.from(rewards!['badges']).join(' · ')),
                      Text(rewards!['award_policy']),
                    ],
                  ),
                ),
              if (reports.isNotEmpty)
                const Text(
                  'My reports',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                ),
              ...reports.take(15).map((r) {
                final age = DateTime.now()
                    .toUtc()
                    .difference(DateTime.parse(r['observed_at']))
                    .inSeconds
                    .clamp(0, 999999);
                final outcome =
                    age >= 30 &&
                        [
                          'confirmed',
                          'awaiting_agreement',
                          'not_in_current_agreement',
                        ].contains(r['outcome'])
                    ? 'expired'
                    : r['outcome'];
                return card(
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                      '${name(r['station_id'])} · ${r['event_type']}',
                    ),
                    subtitle: Text(
                      '$outcome · $age seconds old · ${r['confirmations']}/${r['required_confirmations']} accounts',
                    ),
                  ),
                );
              }),
              const Padding(
                padding: EdgeInsets.only(top: 18, bottom: 30),
                child: Text(
                  'Travel times are estimates, not current train arrivals. Your location is checked only when you choose to report or locate your station. A community update does not identify a particular train.',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    timer?.cancel();
    subscription?.cancel();
    socket?.sink.close();
    api.close();
    super.dispose();
  }
}
