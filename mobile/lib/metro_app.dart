import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'metro_api.dart';

void main() => runApp(const MetroApp());
const navy = Color(0xff0b2d40), teal = Color(0xff138f87);
String words(dynamic value) =>
    (value ?? '').toString().replaceAll('_', ' ').replaceAll('-', ' ');
String waitLabel(num seconds) =>
    seconds < 15 ? 'Now' : '${(seconds / 60).ceil()} min';
const sources = {
  'wsn': 'Underground signal',
  'crowd': 'Community reports',
  'fused': 'Combined evidence',
  'estimate': 'Transition estimate',
  'schedule': 'Timetable estimate',
};

class MetroApp extends StatelessWidget {
  const MetroApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'FindMyMetro',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'MetroSans',
      colorScheme: ColorScheme.fromSeed(seedColor: teal),
      scaffoldBackgroundColor: const Color(0xfff4f7f8),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.white,
        foregroundColor: navy,
      ),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        filled: true,
        fillColor: Colors.white,
      ),
    ),
    home: const MetroHome(),
  );
}

class MetroHome extends StatefulWidget {
  const MetroHome({super.key});
  @override
  State<MetroHome> createState() => _MetroHomeState();
}

class _MetroHomeState extends State<MetroHome> {
  final api = MetroApi();
  SharedPreferences? storage;
  Json? network, snapshot, status;
  List<Json> trips = [], options = [], queued = [];
  String? station, tripId, destination;
  String operatorId = 'dmrc', message = '', connection = 'Connecting';
  int tab = 0, epoch = 0, beat = 0;
  bool refreshing = false, sending = false;
  Timer? timer;
  WebSocketChannel? channel;
  StreamSubscription<dynamic>? subscription;
  List<Json> get lines =>
      List<Json>.from(network?['lines'] ?? [])
          .where((line) => line['operator_id'] == operatorId)
          .toList();
  List<Json> get stations {
    final ids = lines
        .expand((line) => List<String>.from(line['station_ids']))
        .toSet();
    return List<Json>.from(network?['stations'] ?? [])
        .where((item) => ids.contains(item['id']))
        .toList();
  }

  String name(dynamic id) => List<Json>.from(network?['stations'] ?? [])
      .firstWhere(
        (item) => item['id'] == id,
        orElse: () => {'name': id ?? 'Station'},
      )['name']
      .toString();
  List<Json> get arrivals => List<Json>.from(snapshot?['arrivals'] ?? []);
  @override
  void initState() {
    super.initState();
    initialize();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      beat++;
      if (mounted) setState(() {});
      if (beat % 3 == 0) refresh();
    });
  }

  Future<void> initialize() async {
    storage = await SharedPreferences.getInstance();
    try {
      network = jsonDecode(storage!.getString('network') ?? 'null') as Json?;
      if (network != null) selectDefaults();
    } catch (_) {
      network = null;
    }
    try {
      await api.restoreAccount();
      await loadQueue();
    } catch (_) {}
    await refresh();
  }

  void selectDefaults() {
    if (stations.isEmpty) {
      station = null;
      destination = null;
      return;
    }
    if (!stations.any((item) => item['id'] == station)) {
      station = stations.last['id'] as String;
    }
    if (!stations.any((item) => item['id'] == destination)) {
      destination = stations.last['id'] as String;
    }
  }

  Future<void> refresh() async {
    if (refreshing || !mounted) return;
    refreshing = true;
    try {
      network = await api.request('/api/v1/network');
      await storage?.setString('network', jsonEncode(network));
      selectDefaults();
      trips = List<Json>.from((await api.request('/api/v1/trips'))['trips']);
      final eligible = trips
          .where((trip) => lines.any((line) => line['id'] == trip['line_id']))
          .toList();
      if (!eligible.any((trip) => trip['id'] == tripId)) {
        tripId = eligible.isEmpty ? null : eligible.first['id'] as String;
      }
      status = tripId == null
          ? null
          : await api.request(
              '/api/v1/source-status/${Uri.encodeComponent(tripId!)}',
            );
      if (station != null) {
        if (channel == null) connect();
        if (connection != 'Connected') {
          await acceptSnapshot(
            await api.request('/api/v1/eta/${Uri.encodeComponent(station!)}'),
          );
        }
      }
      if (api.user != null && queued.isNotEmpty) await flushQueue();
    } catch (_) {
      if (snapshot == null && station != null) {
        try {
          snapshot = jsonDecode(
            storage?.getString('snapshot:$station') ?? 'null',
          ) as Json?;
        } catch (_) {}
      }
      connection = snapshot == null ? 'Unavailable' : 'Cached';
    } finally {
      refreshing = false;
      if (mounted) setState(() {});
    }
  }

  Future<void> acceptSnapshot(Json value) async {
    if (value['station_id'] != station) return;
    snapshot = value;
    connection = 'Connected';
    await storage?.setString('snapshot:$station', jsonEncode(value));
    if (mounted) setState(() {});
  }

  void connect() {
    if (station == null) return;
    final generation = ++epoch;
    channel = WebSocketChannel.connect(api.socket(station!));
    subscription = channel!.stream.listen(
      (event) {
        if (generation != epoch || !mounted) return;
        try {
          acceptSnapshot(jsonDecode(event as String) as Json);
        } catch (_) {}
      },
      onError: (_) => disconnected(generation),
      onDone: () => disconnected(generation),
    );
  }

  void disconnected(int generation) {
    if (generation != epoch || !mounted) return;
    channel = null;
    setState(() => connection = snapshot == null ? 'Unavailable' : 'Cached');
  }

  void changeStation(String? value) {
    epoch++;
    subscription?.cancel();
    channel?.sink.close();
    channel = null;
    setState(() {
      station = value;
      snapshot = null;
      connection = 'Connecting';
    });
    refresh();
  }

  Future<void> loadQueue() async {
    queued = [];
    if (api.user == null) return;
    try {
      queued =
          List<Json>.from(
                jsonDecode(
                  storage?.getString('reports:${api.user!['id']}') ?? '[]',
                ),
              )
              .where(
                (report) =>
                    DateTime.now()
                        .toUtc()
                        .difference(DateTime.parse(report['observed_at']))
                        .inHours <
                    24,
              )
              .toList();
    } catch (_) {
      queued = [];
    }
  }

  Future<void> saveQueue() async {
    if (api.user != null) {
      await storage?.setString(
        'reports:${api.user!['id']}',
        jsonEncode(queued),
      );
    }
  }

  Future<void> flushQueue() async {
    if (sending || queued.isEmpty || api.user == null) return;
    sending = true;
    try {
      final value = await api.request(
        '/api/v1/crowd-reports/batch',
        body: {'reports': queued},
      );
      final results = List<Json>.from(value['acknowledgements']);
      final terminal = results
          .where(
            (item) => [
              'queued',
              'duplicate',
              'rejected',
              'conflict',
              'accepted',
              'historical',
            ].contains(item['status']),
          )
          .map((item) => item['index'] as int)
          .toSet();
      queued = [
        for (int i = 0; i < queued.length; i++)
          if (!terminal.contains(i)) queued[i],
      ];
      await saveQueue();
      message =
          results.any(
            (item) =>
                item['status'] == 'rejected' || item['status'] == 'conflict',
          )
          ? 'Some reports could not be accepted. Check location, time and selected train.'
          : 'Reports uploaded for validation. Source changes need independent agreement.';
    } on ApiFailure catch (error) {
      message = error.message;
    } catch (_) {
      message = 'Saved on this device; upload resumes after reconnection.';
    } finally {
      sending = false;
      if (mounted) setState(() {});
    }
  }

  Future<void> report() async {
    if (api.user == null) {
      await account();
      return;
    }
    if (tripId == null || queued.length >= 100) {
      setState(
        () => message =
            'Select an active train; the queue holds at most 100 reports.',
      );
      return;
    }
    try {
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if ([
        LocationPermission.denied,
        LocationPermission.deniedForever,
      ].contains(permission)) {
        throw Exception('Location permission is required for a sighting.');
      }
      final location = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );
      final trip = trips.firstWhere((item) => item['id'] == tripId),
          now = DateTime.now().toUtc();
      queued.add({
        'event_id': 'mobile-${now.microsecondsSinceEpoch}',
        'trip_id': tripId,
        'direction': trip['direction'],
        'contributor_id': api.user!['id'],
        'observed_at': now.toIso8601String(),
        'kind': 'sighting',
        'latitude': location.latitude,
        'longitude': location.longitude,
        'accuracy_m': location.accuracy,
        'note': 'User submitted train sighting',
      });
      await saveQueue();
      await flushQueue();
    } catch (error) {
      if (mounted) setState(() => message = error.toString());
    }
  }

  Future<void> account() async {
    await showDialog<void>(
      context: context,
      builder: (context) => AccountSheet(api: api),
    );
    await loadQueue();
    if (mounted) setState(() {});
  }

  Future<void> logout() async {
    try {
      final owner = api.user!['id'];
      await api.logout();
      await storage?.remove('reports:$owner');
      setState(() {
        queued = [];
        message = 'Signed out.';
      });
    } catch (error) {
      setState(() => message = error.toString());
    }
  }

  Future<void> searchRoutes() async {
    try {
      final value = await api.request(
        '/api/v1/routes?origin=${Uri.encodeComponent(station!)}&destination=${Uri.encodeComponent(destination!)}',
      );
      setState(() {
        options = List<Json>.from(value['routes']);
        message = options.isEmpty
            ? 'No valid journey is available at this time.'
            : '';
      });
    } catch (error) {
      setState(() => message = error.toString());
    }
  }

  Widget panel(Widget child) => Card(
    margin: const EdgeInsets.only(bottom: 16),
    color: Colors.white,
    child: Padding(padding: const EdgeInsets.all(20), child: child),
  );
  Widget heading(String title) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: Text(
      title,
      style: const TextStyle(
        fontSize: 23,
        fontWeight: FontWeight.w700,
        color: navy,
      ),
    ),
  );
  Widget select(String label, String? value, void Function(String?) update) =>
      DropdownButtonFormField<String>(
        key: ValueKey('$label:$value:$operatorId'),
        initialValue: value,
        isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: stations
            .map(
              (item) => DropdownMenuItem(
                value: item['id'] as String,
                child: Text(
                  item['name'] as String,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            )
            .toList(),
        onChanged: update,
      );
  String get age {
    final stamp = snapshot?['generated_at'];
    if (stamp == null) return 'No snapshot available';
    final seconds = DateTime.now()
        .toUtc()
        .difference(DateTime.parse(stamp))
        .inSeconds
        .clamp(0, 1000000);
    return '$connection · snapshot ${seconds}s old';
  }

  Widget arrivalCard(Json arrival) {
    final observed = arrival['last_observation_at'];
    final observedAge = observed == null
        ? null
        : DateTime.now()
              .toUtc()
              .difference(DateTime.parse(observed))
              .inSeconds
              .clamp(0, 1000000);
    return panel(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.train, color: teal),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  '${arrival['train_code']} → ${name(arrival['towards'])}',
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Text(
                waitLabel(arrival['remaining_seconds']),
                style: const TextStyle(
                  fontSize: 25,
                  fontWeight: FontWeight.w700,
                  color: teal,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text('${sources[arrival['source']]} · ${words(arrival['context'])}'),
          Text(
            '${words(arrival['freshness_status'])} · ${((arrival['trust_score'] as num) * 100).round()}% heuristic trust',
          ),
          Text(
            observedAge == null
                ? 'No recent observation; schedule fallback'
                : 'Last observation ${observedAge}s ago',
          ),
          if ((arrival['delay_seconds'] as num) > 30)
            Text(
              'Delay ${waitLabel(arrival['delay_seconds'])}',
              style: const TextStyle(color: Colors.deepOrange),
            ),
        ],
      ),
    );
  }

  Widget tracking() => panel(
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        heading('Source tracking'),
        if (status == null)
          const Text('Waiting for an active journey.')
        else ...[
          Text(
            words(status!['context']),
            style: const TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w700,
              color: teal,
            ),
          ),
          Text(
            '${sources[status!['source']]} · ${((status!['trust'] as num) * 100).round()}% heuristic trust',
          ),
          const SizedBox(height: 12),
          Text('Decision: ${words(status!['reason'])}'),
          if (status!['transition'] != null)
            Text(
              'Handover window: ${DateTime.parse(status!['transition']['deadline']).difference(DateTime.now().toUtc()).inSeconds.clamp(0, 60)}s remaining',
            ),
          if (status!['arbitration'] != null)
            Text(
              'Estimated trust ${(100 * (status!['arbitration']['estimated_trust'] as num)).round()}% · incoming ${status!['arbitration']['incoming_trust']}',
            ),
          const Divider(height: 30),
          ...List<Json>.from(status!['decisions'] ?? [])
              .take(5)
              .map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Text(
                    '${sources[item['source']]} · ${words(item['reason'])}',
                  ),
                ),
              ),
        ],
      ],
    ),
  );
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Row(
        children: [
          Icon(Icons.train, color: teal),
          SizedBox(width: 8),
          Text('FindMyMetro', style: TextStyle(fontWeight: FontWeight.bold)),
        ],
      ),
      actions: [
        IconButton(
          tooltip: api.user == null ? 'Sign in' : 'Sign out',
          onPressed: api.user == null ? account : logout,
          icon: Icon(api.user == null ? Icons.person_outline : Icons.logout),
        ),
      ],
    ),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: RefreshIndicator(
          onRefresh: refresh,
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'dmrc', label: Text('Delhi Metro')),
                  ButtonSegment(value: 'nmrc', label: Text('Noida Metro')),
                ],
                selected: {operatorId},
                onSelectionChanged: (value) {
                  setState(() {
                    operatorId = value.first;
                    selectDefaults();
                    tripId = null;
                    options = [];
                  });
                  changeStation(station);
                },
              ),
              const SizedBox(height: 18),
              if (network?['simulated'] == true)
                panel(
                  const Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.science_outlined, color: teal),
                      SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'Software validation feed\nGenerated train and crowd inputs. Hardware comes later; these are not actual Delhi/Noida train positions.',
                        ),
                      ),
                    ],
                  ),
                ),
              if (message.isNotEmpty) panel(Text(message)),
              if (stations.isEmpty)
                panel(
                  Text(
                    network == null ? 'Connecting to your local backend…' : 'Approved station and timetable data are not connected.',
                  ),
                )
              else ...[
                select('Station', station, changeStation),
                const SizedBox(height: 16),
                if (tab == 0) ...[
                  heading('Next trains at ${name(station)}'),
                  Text(age),
                  const SizedBox(height: 14),
                  if (arrivals.isEmpty)
                    panel(const Text('No upcoming arrival is available.')),
                  ...arrivals.map(arrivalCard),
                ],
                if (tab == 1) ...[
                  select(
                    'Destination',
                    destination,
                    (value) => setState(() => destination = value),
                  ),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    onPressed: station == destination ? null : searchRoutes,
                    icon: const Icon(Icons.route),
                    label: const Text('Find journey'),
                  ),
                  const SizedBox(height: 16),
                  ...options.map(
                    (option) => panel(
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          heading(
                            '${waitLabel(option['duration_seconds'])} · ${option['transfers']} transfers',
                          ),
                          ...List<Json>.from(option['steps']).map(
                            (step) => Text(
                              '${words(step['kind'])}: ${name(step['from_station_id'])} → ${name(step['to_station_id'])} · ${waitLabel(step['seconds'])}',
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
                if (tab == 2) ...[
                  heading('Service alerts'),
                  if (List.from(snapshot?['alerts'] ?? []).isEmpty)
                    panel(
                      const Text('No delay alerts in the current snapshot.'),
                    ),
                  ...List<Json>.from(snapshot?['alerts'] ?? []).map(
                    (alert) => panel(
                      Text(
                        '${alert['title']}\n${sources[alert['source']]} · ${words(alert['freshness_status'])}',
                      ),
                    ),
                  ),
                ],
                if (tab == 3) tracking(),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: sending ? null : report,
                  icon: const Icon(Icons.add_location_alt_outlined),
                  label: Text(
                    api.user == null
                        ? 'Sign in to report a train'
                        : 'Report a train · ${queued.length} queued',
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Reports use a one-time location check. New contributors need independent verification before affecting predictions.',
                  style: TextStyle(fontSize: 12),
                ),
              ],
            ],
          ),
        ),
      ),
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: tab,
      onDestinationSelected: (value) => setState(() => tab = value),
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.train_outlined),
          label: 'Arrivals',
        ),
        NavigationDestination(icon: Icon(Icons.route), label: 'Journey'),
        NavigationDestination(
          icon: Icon(Icons.notifications_outlined),
          label: 'Alerts',
        ),
        NavigationDestination(icon: Icon(Icons.sensors), label: 'Tracking'),
      ],
    ),
  );
  @override
  void dispose() {
    timer?.cancel();
    subscription?.cancel();
    channel?.sink.close();
    api.close();
    super.dispose();
  }
}

class AccountSheet extends StatefulWidget {
  final MetroApi api;
  const AccountSheet({super.key, required this.api});
  @override
  State<AccountSheet> createState() => _AccountSheetState();
}

class _AccountSheetState extends State<AccountSheet> {
  final username = TextEditingController(),
      password = TextEditingController(),
      name = TextEditingController();
  bool register = false, busy = false;
  String error = '';
  Future<void> submit() async {
    setState(() {
      busy = true;
      error = '';
    });
    try {
      await widget.api.authenticate(register ? 'register' : 'login', {
        'username': username.text.trim(),
        'password': password.text,
        if (register) 'display_name': name.text.trim(),
      });
      if (mounted) Navigator.pop(context);
    } catch (problem) {
      if (mounted) setState(() => error = problem.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(register ? 'Create account' : 'Welcome back'),
    content: SizedBox(
      width: 360,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (register)
              TextField(
                controller: name,
                decoration: const InputDecoration(labelText: 'Your name'),
              ),
            const SizedBox(height: 12),
            TextField(
              controller: username,
              autofillHints: const [AutofillHints.username],
              decoration: const InputDecoration(labelText: 'Username'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: password,
              obscureText: true,
              autofillHints: const [AutofillHints.password],
              decoration: const InputDecoration(labelText: 'Password'),
            ),
            if (register)
              const Padding(
                padding: EdgeInsets.only(top: 12),
                child: Text(
                  'Use 3–32 letters, numbers or underscores, and at least 12 password characters.',
                ),
              ),
            if (error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(error, style: const TextStyle(color: Colors.red)),
              ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: busy ? null : () => setState(() => register = !register),
        child: Text(register ? 'Sign in instead' : 'Create account'),
      ),
      FilledButton(
        onPressed: busy ? null : submit,
        child: Text(
          busy
              ? 'Please wait…'
              : register
              ? 'Create account'
              : 'Sign in',
        ),
      ),
    ],
  );
  @override
  void dispose() {
    username.dispose();
    password.dispose();
    name.dispose();
    super.dispose();
  }
}
