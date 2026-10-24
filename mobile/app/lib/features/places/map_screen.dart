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
/// in view. A tap says what it is and opens it; the button centres the map on where the phone is.
class MapScreen extends ConsumerStatefulWidget {
  const MapScreen({super.key, this.center, this.zoom});

  final LatLng? center;
  final double? zoom;

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
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: ListTile(
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
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final items = [for (final f in _features) (shape: f.shape, colour: layerColour(f.layer), value: f)];
    return Scaffold(
      appBar: AppBar(title: const Text('Map')),
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
            onMapReady: () => _load(_map.camera.visibleBounds),
            onPositionChanged: (camera, _) => _moved(camera),
          ),
          children: [
            ...baseLayers(ref),
            ...shapeLayers<MapFeatureItem>(items, onTap: _show, polygonHits: _polygonHits, lineHits: _lineHits),
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
              child: Text('${_features.length} in view', key: const Key('map-count')),
            ),
          ),
        ),
      ]),
    );
  }
}
