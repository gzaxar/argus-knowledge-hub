import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app/providers.dart';
import '../core/problem.dart';
import '../features/capture/media_source.dart' show readPlace;
import 'common.dart';

/// Where a piece of equipment is: its approved location, and a way to say where it is seen now. What the phone
/// sends is an observation — it never moves the record; it agrees with the approved location, or a person
/// reviews it.
class LocationSection extends ConsumerStatefulWidget {
  const LocationSection({super.key, required this.uid});

  final String uid;

  @override
  ConsumerState<LocationSection> createState() => _LocationSectionState();
}

class _LocationSectionState extends ConsumerState<LocationSection> {
  bool _busy = false;

  Future<void> _observe() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final file = await ref.read(mediaSourceProvider).place();
      final fix = file == null ? null : readPlace(file.bytes);
      if (fix == null) return;
      final r = await ref.read(locationRepositoryProvider).observe(widget.uid, fix.lat, fix.lon, accuracy: fix.accuracy);
      ref.invalidate(assetLocationProvider(widget.uid));
      final distance = r.distance == null ? null : '${r.distance!.round()} m';
      messenger.showSnackBar(SnackBar(
          content: Text(switch (r.status) {
        'consistent' => 'It is where ARGUS has it${distance == null ? '' : ' ($distance away)'}.',
        _ when r.distance == null => 'It has no location yet: yours is sent for review.',
        _ => 'Sent for review: $distance from where ARGUS has it. Its location does not change until accepted.',
      })));
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(assetLocationProvider(widget.uid));
    final l = r.value;
    if (l == null || !l.locatable) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final pending = l.observations.where((o) => o.status == 'pending').length;
    final here = l.current;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SectionHeader('Location', trailing: l.layer),
      if (l.hidden)
        const ListTile(leading: Icon(Icons.lock_outline), title: Text('Its location is restricted.'))
      else ...[
        ListTile(
          key: const Key('asset-location'),
          leading: Icon(here == null ? Icons.location_off_outlined : Icons.place_outlined),
          title: Text(here == null
              ? 'No location yet'
              : '${here.latitude.toStringAsFixed(6)}, ${here.longitude.toStringAsFixed(6)}'
                  '${here.accuracy == null ? '' : ' (±${here.accuracy!.round()} m)'}'),
          subtitle: here == null
              ? null
              : Text([
                  switch (here.source) { 'field' => 'from the field', 'import' => 'imported', _ => 'set by hand' },
                  if (here.at != null) formatWhenDate(here.at),
                  if (here.reviewer != null) 'reviewed by ${here.reviewer}',
                ].join(' · ')),
          trailing: here == null
              ? null
              : IconButton(
                  tooltip: 'Open in maps',
                  icon: const Icon(Icons.map_outlined),
                  onPressed: () => launchUrl(
                      Uri.parse('geo:${here.latitude},${here.longitude}?q=${here.latitude},${here.longitude}'),
                      mode: LaunchMode.externalApplication),
                ),
        ),
        if (pending > 0)
          ListTile(
            dense: true,
            leading: Icon(Icons.pending_outlined, color: theme.colorScheme.tertiary),
            title: Text('$pending observation${pending == 1 ? '' : 's'} waiting for review'),
          ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key('asset-observe-location'),
              onPressed: _busy ? null : _observe,
              icon: _busy
                  ? const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.my_location),
              label: const Text("I'm next to it"),
            ),
          ),
        ),
      ],
    ]);
  }
}
