import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../widgets/place_map.dart';
import '../capture/media_source.dart' show readPlace;

/// A record's position, chosen on the map: the map moves under a crosshair, or a tap brings a point to it, and the
/// point is used when the person says so. For someone who may edit the record.
class PositionPickScreen extends ConsumerStatefulWidget {
  const PositionPickScreen({super.key, required this.uid, this.start});

  final String uid;

  /// Where it is now; with none, the map starts on the phone when it can say where it is.
  final LatLng? start;

  @override
  ConsumerState<PositionPickScreen> createState() => _PositionPickScreenState();
}

class _PositionPickScreenState extends ConsumerState<PositionPickScreen> {
  final _map = MapController();
  bool _ready = false;
  bool _saving = false;
  bool _locating = false;

  Future<void> _toPhone({bool quietly = false}) async {
    setState(() => _locating = true);
    try {
      final file = await ref.read(mediaSourceProvider).place();
      final here = file == null ? null : readPlace(file.bytes);
      if (here != null && mounted) _map.move(LatLng(here.lat, here.lon), 18);
    } on Problem catch (p) {
      if (!quietly && mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _use() async {
    final point = _map.camera.center;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(locationRepositoryProvider).setPosition(widget.uid, point.latitude, point.longitude, fromHere: false);
      ref.invalidate(assetLocationProvider(widget.uid));
      refreshAsset(ref, widget.uid);
      messenger.showSnackBar(const SnackBar(content: Text('Position set.')));
      if (mounted) context.pop();
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Choose its position')),
      floatingActionButton: FloatingActionButton(
        key: const Key('pick-locate'),
        tooltip: 'Where am I',
        onPressed: _locating ? null : _toPhone,
        child: const Icon(Icons.my_location),
      ),
      body: Column(children: [
        Expanded(
          child: Stack(alignment: Alignment.center, children: [
            FlutterMap(
              key: const Key('pick-map'),
              mapController: _map,
              options: MapOptions(
                initialCenter: widget.start ?? lnf,
                initialZoom: 18,
                maxZoom: 20,
                onMapReady: () {
                  setState(() => _ready = true);
                  if (widget.start == null) _toPhone(quietly: true);
                },
                onTap: (_, point) => _map.move(point, _map.camera.zoom),
              ),
              children: baseLayers(ref),
            ),
            const IgnorePointer(child: Icon(Icons.add, key: Key('pick-crosshair'), size: 36, color: Colors.redAccent)),
          ]),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              const Expanded(child: Text('Move the map, or tap, to bring the place under the cross.')),
              const SizedBox(width: 8),
              FilledButton(
                key: const Key('pick-use'),
                onPressed: !_ready || _saving ? null : _use,
                child: Text(_saving ? 'Saving…' : 'Use this point'),
              ),
              // Room for the button above it.
              const SizedBox(width: 72),
            ]),
          ),
        ),
      ]),
    );
  }
}
