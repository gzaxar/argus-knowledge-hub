import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';
import '../../widgets/place_map.dart';
import '../capture/media_source.dart' show readPlace;

/// The records with a location, on a map: positions as dots, routes (cables, pipes, beamlines) as lines and
/// outlines (buildings, halls, rooms, zones) as areas — those the person may see, loaded for the part of the map
/// in view. A tap says what it is and opens it — a building or a hall with floor plans lists them, to go inside;
/// the button centres the map on where the phone is. Search finds a located record and goes to it; layers can be
/// turned off. Opened with [focus] (a record's uid, from Near me), it goes to that record.
class MapScreen extends ConsumerStatefulWidget {
  const MapScreen({super.key, this.center, this.zoom, this.focus});

  final LatLng? center;
  final double? zoom;
  final String? focus;

  @override
  ConsumerState<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends ConsumerState<MapScreen> {
  final _map = MapController();
  final _polygonHits = LayerHitNotifier<MapFeatureItem>(null);
  final _lineHits = LayerHitNotifier<MapFeatureItem>(null);
  Timer? _debounce;
  List<MapFeatureItem> _features = const [];
  LatLng? _me;
  Object? _error;
  bool _loading = false;
  bool _locating = false;
  // Everything located in the workspace, loaded when first needed (search, or a record to go to).
  List<MapFeatureItem>? _all;
  String? _focus;
  bool _mapReady = false;

  Future<List<MapFeatureItem>> _everything() async =>
      _all ??= await ref.read(locationRepositoryProvider).everything();

  /// Take the map to a record: a point close up, a route or an outline whole, outlined in orange.
  void _goTo(MapFeatureItem f) {
    final s = f.shape;
    final pts = [...s.points, for (final l in s.lines) ...l, for (final a in s.areas) ...a.first];
    if (pts.isEmpty) return;
    setState(() => _focus = f.target.uid);
    if (pts.length == 1 || LatLngBounds.fromPoints(pts).north == LatLngBounds.fromPoints(pts).south) {
      _map.move(pts.first, 19);
    } else {
      _map.fitCamera(CameraFit.bounds(bounds: LatLngBounds.fromPoints(pts), padding: const EdgeInsets.all(48),
          maxZoom: 19));
    }
  }

  Future<void> _goToFocus() async {
    final uid = widget.focus;
    if (uid == null || !_mapReady) return;
    try {
      final all = await _everything();
      final hits = all.where((f) => f.target.uid == uid).toList()
        ..sort((a, b) => _order(b.shape.role).compareTo(_order(a.shape.role)));
      if (hits.isNotEmpty && mounted) _goTo(hits.first);
    } catch (_) {/* the map stays where it is */}
  }

  static int _order(String role) => switch (role) { 'outline' => 0, 'route' => 1, _ => 2 };

  Future<void> _find() async {
    final picked = await showModalBottomSheet<MapFeatureItem>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheet) => _FindSheet(load: _everything, showKeys: ref.read(showKeysProvider)),
    );
    if (picked != null && mounted) _goTo(picked);
  }

  Future<void> _layers() async {
    final repo = ref.read(locationRepositoryProvider);
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => FutureBuilder<List<({String id, String name})>>(
        future: repo.layers(),
        builder: (_, snap) => Consumer(builder: (_, ref, _) {
          final hidden = ref.watch(hiddenLayersProvider);
          final layers = snap.data ?? const <({String id, String name})>[];
          return SafeArea(
            child: ListView(shrinkWrap: true, children: [
              const ListTile(title: Text('Layers'), subtitle: Text('Turn a layer off to hide it on this map.')),
              if (snap.connectionState != ConnectionState.done) const LinearProgressIndicator(),
              for (final l in layers)
                SwitchListTile(
                  key: Key('map-layer-${l.id}'),
                  secondary: CircleAvatar(radius: 7, backgroundColor: layerColour(l.id)),
                  title: Text(l.name),
                  value: !hidden.contains(l.id),
                  onChanged: (_) => ref.read(hiddenLayersProvider.notifier).toggle(l.id),
                ),
            ]),
          );
        }),
      ),
    );
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _polygonHits.dispose();
    _lineHits.dispose();
    super.dispose();
  }

  void _moved(MapCamera camera) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () => _load(camera.visibleBounds));
  }

  Future<void> _load(LatLngBounds b) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final found = await ref
          .read(locationRepositoryProvider)
          .features(south: b.south, west: b.west, north: b.north, east: b.east);
      if (mounted) setState(() => _features = found);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _locate() async {
    setState(() => _locating = true);
    try {
      final file = await ref.read(mediaSourceProvider).place();
      final here = file == null ? null : readPlace(file.bytes);
      if (here == null || !mounted) return;
      setState(() => _me = LatLng(here.lat, here.lon));
      _map.move(_me!, 18);
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  void _show(MapFeatureItem f) {
    final s = f.shape;
    final showKeys = ref.read(showKeysProvider);
    final what = switch (s.role) {
      'route' => 'its route',
      'outline' => s.base != null && s.top != null ? 'its outline, from ${s.base} m to ${s.top} m' : 'its outline',
      _ => null,
    };
    final repo = ref.read(locationRepositoryProvider);
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          key: Key('map-feature-${f.target.uid}'),
          leading: Icon(s.role == 'route' ? Icons.timeline : s.role == 'outline' ? Icons.crop_square : Icons.place_outlined,
              color: layerColour(f.layer)),
          title: Text(f.target.title ?? f.target.uid),
          subtitle: Text(keyed(showKeys, f.target.key, [f.target.subtitle, what, f.status])),
          trailing: const Icon(Icons.chevron_right),
          onTap: () {
            Navigator.pop(sheet);
            context.push(f.target.route);
          },
        ),
        // A building, a hall or a room with floor plans (drawn as an outline or only a point): go inside, floor by floor.
        if (s.role != 'route')
          FutureBuilder<List<({PlanRef plan, String? level, String? place})>>(
            future: repo.plansFor([f.target.uid]),
            builder: (_, snap) {
              final plans = snap.data ?? const [];
              if (plans.isEmpty) return const SizedBox.shrink();
              return Column(mainAxisSize: MainAxisSize.min, children: [
                const Divider(height: 1),
                ListTile(dense: true, title: Text('Inside: ${plans.length == 1 ? 'a floor plan' : '${plans.length} floor plans'}')),
                for (final p in plans)
                  ListTile(
                    key: Key('map-inside-${p.plan.uid}'),
                    leading: const Icon(Icons.layers_outlined),
                    title: Text(p.level ?? p.plan.name),
                    subtitle: p.level == null ? null : Text(p.plan.name),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () {
                      Navigator.pop(sheet);
                      context.push('/plan/${p.plan.uid}');
                    },
                  ),
              ]);
            },
          ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final hidden = ref.watch(hiddenLayersProvider);
    final shown = [for (final f in _features) if (!hidden.contains(f.layer ?? '')) f];
    final items = [for (final f in shown) (shape: f.shape, colour: layerColour(f.layer), value: f)];
    final lit = [for (final f in shown) if (f.target.uid == _focus) f];
    return Scaffold(
      appBar: AppBar(title: const Text('Map'), actions: [
        IconButton(key: const Key('map-find'), tooltip: 'Find on the map', icon: const Icon(Icons.search), onPressed: _find),
        IconButton(key: const Key('map-layers'), tooltip: 'Layers', icon: const Icon(Icons.layers_outlined), onPressed: _layers),
      ]),
      floatingActionButton: FloatingActionButton(
        key: const Key('map-locate'),
        tooltip: 'Where am I',
        onPressed: _locating ? null : _locate,
        child: _locating
            ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
            : const Icon(Icons.my_location),
      ),
      body: Stack(children: [
        FlutterMap(
          key: const Key('map'),
          mapController: _map,
          options: MapOptions(
            initialCenter: widget.center ?? lnf,
            initialZoom: widget.zoom ?? 16,
            maxZoom: 20,
            onMapReady: () {
              _mapReady = true;
              _load(_map.camera.visibleBounds);
              _goToFocus();
            },
            onPositionChanged: (camera, _) => _moved(camera),
          ),
          children: [
            ...baseLayers(ref),
            ...shapeLayers<MapFeatureItem>(items, onTap: _show, polygonHits: _polygonHits, lineHits: _lineHits),
            // The record gone to, outlined in orange over the rest.
            if (lit.isNotEmpty) ...[
              PolygonLayer(polygons: [
                for (final f in lit)
                  for (final a in f.shape.areas)
                    Polygon(points: a.first, color: Colors.transparent, borderColor: Colors.orange, borderStrokeWidth: 4),
              ]),
              PolylineLayer(polylines: [
                for (final f in lit)
                  for (final l in f.shape.lines) Polyline(points: l, color: Colors.orange, strokeWidth: 5),
              ]),
              MarkerLayer(markers: [
                for (final f in lit)
                  for (final p in f.shape.points)
                    Marker(point: p, width: 30, height: 30,
                        child: const Icon(Icons.radio_button_unchecked, color: Colors.orange, size: 30)),
              ]),
            ],
            if (_me != null)
              MarkerLayer(markers: [
                Marker(
                    point: _me!,
                    width: 22,
                    height: 22,
                    child: const Icon(Icons.radio_button_checked, color: Colors.redAccent, size: 22)),
              ]),
          ],
        ),
        if (_loading) const Positioned(top: 0, left: 0, right: 0, child: LinearProgressIndicator()),
        if (_error != null)
          Positioned(
            top: 8,
            left: 8,
            right: 8,
            child: NoticeBar(
                icon: Icons.error_outline,
                text: _error is Problem ? (_error as Problem).message : 'The map could not be loaded.',
                severe: true),
          ),
        Positioned(
          left: 8,
          bottom: 8,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              child: Text('${shown.length} in view', key: const Key('map-count')),
            ),
          ),
        ),
      ]),
    );
  }
}


/// Located records whose name, key or type has every word typed, a name that starts with them first.
List<MapFeatureItem> findOnMap(List<MapFeatureItem> all, String text, {int limit = 30}) {
  final words = text.trim().toLowerCase().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  if (words.isEmpty) return const [];
  final seen = <String>{};
  final hits = <MapFeatureItem>[];
  for (final f in all) {
    final t = '${f.target.title ?? ''} ${f.target.key ?? ''} ${f.target.subtitle ?? ''}'.toLowerCase();
    if (words.every(t.contains) && seen.add(f.target.uid)) hits.add(f);
  }
  int starts(MapFeatureItem f) => (f.target.title ?? '').toLowerCase().startsWith(words.first) ? 0 : 1;
  hits.sort((a, b) {
    final c = starts(a).compareTo(starts(b));
    return c != 0 ? c : (a.target.title ?? '').compareTo(b.target.title ?? '');
  });
  return hits.take(limit).toList();
}

/// Search the located records of the workspace; a tap returns the one to go to.
class _FindSheet extends StatefulWidget {
  const _FindSheet({required this.load, required this.showKeys});

  final Future<List<MapFeatureItem>> Function() load;
  final bool showKeys;

  @override
  State<_FindSheet> createState() => _FindSheetState();
}

class _FindSheetState extends State<_FindSheet> {
  late final Future<List<MapFeatureItem>> _all = widget.load();
  String _text = '';

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SizedBox(
          height: MediaQuery.of(context).size.height * 0.6,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                key: const Key('map-find-text'),
                autofocus: true,
                decoration: const InputDecoration(prefixIcon: Icon(Icons.search),
                    hintText: 'A building, a room, a rack, a key…'),
                onChanged: (v) => setState(() => _text = v),
              ),
            ),
            Expanded(
              child: FutureBuilder<List<MapFeatureItem>>(
                future: _all,
                builder: (_, snap) {
                  if (snap.hasError) return const ListTile(title: Text('The located records could not be loaded.'));
                  if (!snap.hasData) return const LinearProgressIndicator();
                  final hits = findOnMap(snap.data!, _text);
                  if (_text.trim().isNotEmpty && hits.isEmpty) return const ListTile(title: Text('Nothing located matches.'));
                  return ListView(children: [
                    for (final f in hits)
                      ListTile(
                        key: Key('map-found-${f.target.uid}'),
                        leading: CircleAvatar(radius: 7, backgroundColor: layerColour(f.layer)),
                        title: Text(f.target.title ?? f.target.uid),
                        subtitle: Text(keyed(widget.showKeys, f.target.key, [f.target.subtitle])),
                        onTap: () => Navigator.pop(context, f),
                      ),
                  ]);
                },
              ),
            ),
          ]),
        ),
      );
}
