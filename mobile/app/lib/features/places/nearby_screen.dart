import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';
import '../capture/media_source.dart' show readPlace;

/// What is near the person: the records with a location within a distance of where the phone is, nearest
/// first — those they may see, in every workspace they can open.
class NearbyScreen extends ConsumerStatefulWidget {
  const NearbyScreen({super.key});

  @override
  ConsumerState<NearbyScreen> createState() => _NearbyScreenState();
}

class _NearbyScreenState extends ConsumerState<NearbyScreen> {
  static const radii = [50.0, 200.0, 1000.0];
  double _radius = 200;
  ({double lat, double lon, double? accuracy})? _here;
  List<NearbyHit>? _hits;
  Object? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _locate());
  }

  Future<void> _locate() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final file = await ref.read(mediaSourceProvider).place();
      _here = file == null ? null : readPlace(file.bytes);
      await _search();
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _search() async {
    final here = _here;
    if (here == null) return;
    final hits = await ref.read(locationRepositoryProvider).nearby(here.lat, here.lon, radius: _radius);
    if (mounted) setState(() => _hits = hits);
  }

  String _distance(double m) => m < 1000 ? '${m.round()} m' : '${(m / 1000).toStringAsFixed(1)} km';

  @override
  Widget build(BuildContext context) {
    final showKeys = ref.watch(showKeysProvider);
    final here = _here;
    return Scaffold(
      appBar: AppBar(title: const Text('Near me'), actions: [
        IconButton(tooltip: 'Where am I now', icon: const Icon(Icons.my_location), onPressed: _busy ? null : _locate),
      ]),
      body: ListView(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: SegmentedButton<double>(
            key: const Key('nearby-radius'),
            segments: [for (final r in radii) ButtonSegment(value: r, label: Text('within ${_distance(r)}'))],
            selected: {_radius},
            onSelectionChanged: (s) {
              setState(() => _radius = s.first);
              _search();
            },
          ),
        ),
        if (here != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Text('You are at ${here.lat.toStringAsFixed(5)}, ${here.lon.toStringAsFixed(5)}'
                '${here.accuracy == null ? '' : ' (±${here.accuracy!.round()} m)'}',
                style: Theme.of(context).textTheme.bodySmall),
          ),
        if (_busy) const LinearProgressIndicator(),
        if (_error != null) ListTile(title: Text(_error is Problem ? (_error as Problem).message : '$_error')),
        if (_hits != null && _hits!.isEmpty)
          ListTile(title: Text('Nothing with a location within ${_distance(_radius)}.')),
        for (final h in _hits ?? const <NearbyHit>[])
          ListTile(
            key: Key('nearby-${h.target.uid}'),
            leading: const Icon(Icons.place_outlined),
            title: Text(h.target.title ?? h.target.uid),
            subtitle: Text(keyed(showKeys, h.target.key, [h.target.subtitle])),
            trailing: Text(_distance(h.distance)),
            onTap: () => context.push(h.target.route),
          ),
      ]),
    );
  }
}
