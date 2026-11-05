import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app/providers.dart';
import '../core/problem.dart';
import '../features/capture/media_source.dart' show readPlace;
import '../domain/models.dart';
import 'common.dart';
import 'place_map.dart';

/// Where a piece of equipment is: its approved location — and its route or outline, on a small map — and a way
/// to say where it is seen now. What the phone sends then is an observation — it never moves the record; it agrees
/// with the approved location, or a person reviews it. Someone who may edit the record sets its position directly:
/// from where the phone stands, or a point chosen on the map.
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
        'noted' => 'Noted. It is placed indoors, where a GPS fix this vague does not move it: place it on its plan instead.',
        _ when r.distance == null => 'It has no location yet: yours is sent for review.',
        _ => 'Sent for review: $distance from where ARGUS has it. Its location does not change until accepted.',
      })));
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Its position, from where the phone stands: confirmed first, since it takes effect at once.
  Future<void> _setHere(IndoorInfo? inside, PlacedPoint? here) async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final file = await ref.read(mediaSourceProvider).place();
      final fix = file == null ? null : readPlace(file.bytes);
      if (fix == null || !mounted) return;
      if (inside != null && inside.placed && (fix.accuracy == null || fix.accuracy! > indoorGpsMetres)) {
        messenger.showSnackBar(SnackBar(
            content: Text('It is placed indoors, where a GPS fix this vague '
                '${fix.accuracy == null ? '' : '(±${fix.accuracy!.round()} m) '}does not move it: '
                'choose the point on the map, or place it on its plan.')));
        return;
      }
      final where = '${fix.lat.toStringAsFixed(6)}, ${fix.lon.toStringAsFixed(6)}'
          '${fix.accuracy == null ? '' : ' (±${fix.accuracy!.round()} m)'}';
      setState(() => _busy = false); // the fix is in: no spinner behind the question
      final sure = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: const Text('Set its position here?'),
          content: Text('$where.\n'
              '${fix.accuracy != null && fix.accuracy! > weakGpsMetres ? 'The GPS fix is weak: outdoors, or choosing the point on the map, is better.\n' : ''}'
              '${here == null ? 'It takes effect at once.' : 'It takes effect at once, and the position it had stays in its history.'}'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialog), child: const Text('Cancel')),
            FilledButton(
              key: const Key('asset-set-here-confirm'),
              onPressed: () => Navigator.pop(dialog, true),
              child: const Text('Set position'),
            ),
          ],
        ),
      );
      if (sure != true) return;
      await ref.read(locationRepositoryProvider).setPosition(widget.uid, fix.lat, fix.lon, accuracy: fix.accuracy, fromHere: true);
      ref.invalidate(assetLocationProvider(widget.uid));
      refreshAsset(ref, widget.uid);
      messenger.showSnackBar(const SnackBar(content: Text('Position set.')));
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _chooseOnMap(PlacedPoint? here) async {
    await context.push(Uri(path: '/asset/${widget.uid}/position', queryParameters: {
      if (here != null) 'lat': '${here.latitude}',
      if (here != null) 'lon': '${here.longitude}',
    }).toString());
  }

  /// The plans it could be placed on — its room's and those of the places the room is in, or those on the map
  /// around it — to choose one and tap where it is.
  Future<void> _pickPlan(IndoorInfo inside, PlacedPoint? here) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final places = [?inside.placeUid, ...inside.chainUids];
      // With neither a place nor a position yet, the plans around the phone: it is standing by the thing.
      var lat = here?.latitude, lon = here?.longitude;
      if (places.isEmpty && lat == null) {
        final file = await ref.read(mediaSourceProvider).place();
        final fix = file == null ? null : readPlace(file.bytes);
        lat = fix?.lat;
        lon = fix?.lon;
      }
      final plans = await ref.read(locationRepositoryProvider).plansFor(places, lat: lat, lon: lon);
      if (!mounted) return;
      if (plans.isEmpty) {
        messenger.showSnackBar(const SnackBar(content: Text('No floor plan here yet: add one on the web, on its place.')));
        return;
      }
      final chosen = await showModalBottomSheet<String>(
        context: context,
        showDragHandle: true,
        builder: (sheet) => SafeArea(
          child: ListView(shrinkWrap: true, children: [
            for (final p in plans)
              ListTile(
                key: Key('plan-choice-${p.plan.uid}'),
                leading: const Icon(Icons.layers_outlined),
                title: Text(p.plan.name),
                subtitle: Text([p.place, p.level].whereType<String>().join(' · ')),
                onTap: () => Navigator.pop(sheet, p.plan.uid),
              ),
          ]),
        ),
      );
      if (chosen != null && mounted) context.push('/plan/$chosen?asset=${widget.uid}');
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
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
    final colour = layerColour(l.layer);
    final shapes = [
      if (l.outline != null) (shape: l.outline!, colour: colour, value: 'outline'),
      if (l.route != null) (shape: l.route!, colour: colour, value: 'route'),
      if (here != null)
        (shape: PlaceShape(role: 'position', points: [LatLng(here.latitude, here.longitude)]), colour: colour, value: 'position'),
    ];
    final all = [for (final s in shapes) ...s.shape.all];
    final inside = ref.watch(indoorProvider(widget.uid)).value;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SectionHeader('Location', trailing: l.layer),
      if (l.hidden)
        const ListTile(leading: Icon(Icons.lock_outline), title: Text('Its location is restricted.'))
      else ...[
        if (all.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: SizedBox(
                key: const Key('asset-location-map'),
                height: 180,
                child: FlutterMap(
                  options: fittedOptions(all),
                  children: [...baseLayers(ref), ...shapeLayers<String>(shapes)],
                ),
              ),
            ),
          ),
        if (l.route != null)
          ListTile(
            key: const Key('asset-route'),
            dense: true,
            leading: const Icon(Icons.timeline),
            title: Text('Route${l.route!.length == null ? '' : ', ${_length(l.route!.length!)} long'}'),
          ),
        if (l.outline != null)
          ListTile(
            key: const Key('asset-outline'),
            dense: true,
            leading: const Icon(Icons.crop_square),
            title: Text([
              'Outline',
              if (l.outline!.area != null) _area(l.outline!.area!),
              if (l.outline!.base != null && l.outline!.top != null) 'from ${l.outline!.base} m to ${l.outline!.top} m',
            ].join(', ')),
          ),
        if (all.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: const Key('asset-open-map'),
                onPressed: () => context.push(Uri(path: '/map', queryParameters: {
                  'lat': '${all.first.latitude}',
                  'lon': '${all.first.longitude}',
                }).toString()),
                icon: const Icon(Icons.map_outlined),
                label: const Text('Open the map here'),
              ),
            ),
          ),
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
        if (inside != null && inside.placed)
          ListTile(
            key: const Key('asset-indoors'),
            leading: const Icon(Icons.meeting_room_outlined),
            title: Text([
              if (inside.placeName != null) 'In ${inside.placeName}',
              if (inside.levelName != null) inside.levelName!,
            ].join(', ')),
            subtitle: inside.chain.length > 1 ? Text('which is in ${inside.chain.skip(1).join(' → ')}') : null,
            trailing: inside.plan == null
                ? null
                : IconButton(
                    key: const Key('asset-show-plan'),
                    tooltip: 'Show on the plan',
                    icon: const Icon(Icons.layers_outlined),
                    onPressed: () => context.push('/plan/${inside.plan!.uid}?asset=${widget.uid}'),
                  ),
          ),
        if (inside != null && inside.plan == null && (inside.placed || here != null || l.maySet))
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: const Key('asset-pick-plan'),
                onPressed: () => _pickPlan(inside, here),
                icon: const Icon(Icons.layers_outlined),
                label: const Text('Place it on a plan'),
              ),
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
          child: Wrap(spacing: 8, runSpacing: 4, children: [
            // Pinned on a plan, its position comes from there: it is moved on the plan.
            if (l.maySet && inside?.plan == null) ...[
              FilledButton.icon(
                key: const Key('asset-set-here'),
                onPressed: _busy ? null : () => _setHere(inside, here),
                icon: _busy
                    ? const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.my_location),
                label: const Text('Set position here'),
              ),
              OutlinedButton.icon(
                key: const Key('asset-choose-on-map'),
                onPressed: _busy ? null : () => _chooseOnMap(here),
                icon: const Icon(Icons.edit_location_alt_outlined),
                label: const Text('Choose on the map'),
              ),
            ],
            // Saying where it is seen: to check the position, or all one can do without the right to edit. With
            // no position yet, someone who may set it has no need of it.
            if (!l.maySet || here != null)
              OutlinedButton.icon(
                key: const Key('asset-observe-location'),
                onPressed: _busy ? null : _observe,
                icon: const Icon(Icons.fact_check_outlined),
                label: const Text("I'm next to it"),
              ),
          ]),
        ),
      ],
    ]);
  }
}

/// A fix less precise than this does not move a record placed indoors (services/indoor.py INDOOR_GPS_M).
const indoorGpsMetres = 10.0;

/// A fix less precise than this is called weak when asking to confirm it.
const weakGpsMetres = 30.0;

String _length(double m) => m >= 1000 ? '${(m / 1000).toStringAsFixed(2)} km' : '${m.toStringAsFixed(1)} m';
String _area(double m2) => m2 >= 10000 ? '${(m2 / 10000).toStringAsFixed(2)} ha' : '${m2.round()} m²';
