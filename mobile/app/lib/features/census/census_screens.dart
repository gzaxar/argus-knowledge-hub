import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/capture.dart' show EquipmentType;
import '../../domain/census.dart';
import '../../domain/models.dart' show LinkTarget;
import '../../widgets/common.dart';
import 'rack_drawing.dart';
import '../../widgets/pick_photo.dart';

/// The guided survey of a rack from the phone (docs/rack-census.md):
/// photograph the rack, confirm which rack it is and where; photograph each unit (and its label); take, correct or
/// type what was read; link each to a record or make a new one; review the whole rack; save. Every step is kept on
/// the server, so a survey left half-way is resumed from this list.
class CensusListScreen extends ConsumerWidget {
  const CensusListScreen({super.key});

  Future<void> _start(BuildContext context, WidgetRef ref, {String? rackUid}) async {
    try {
      final c = await ref.read(censusRepositoryProvider).start(rackUid: rackUid);
      ref.invalidate(openCensusesProvider);
      if (context.mounted) context.push('/census/${c.uid}');
    } on Problem catch (p) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final open = ref.watch(openCensusesProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Rack survey')),
      body: ListView(children: [
        const ListTile(
          title: Text('Photograph a rack and its units'),
          subtitle: Text('What is read on the photos is proposed, never filled in for you. Nothing changes in ARGUS '
              'until you review the whole rack and save it; you can stop and come back.'),
        ),
        ListTile(
          key: const Key('census-existing'),
          leading: const Icon(Icons.dns_outlined),
          title: const Text('A rack already in ARGUS'),
          subtitle: const Text('Find it by name or key'),
          onTap: () async {
            final rack = await pickRecord(context, ref, title: 'Which rack?', types: const {'Rack'});
            if (rack != null && context.mounted) await _start(context, ref, rackUid: rack.uid);
          },
        ),
        ListTile(
          key: const Key('census-new'),
          leading: const Icon(Icons.add_box_outlined),
          title: const Text('A rack not recorded yet'),
          subtitle: const Text('Start from its photo'),
          onTap: () => _start(context, ref),
        ),
        const SectionHeader('Left half-way'),
        ...open.when(
          data: (list) => list.isEmpty
              ? [const ListTile(title: Text('None.'))]
              : [
                  for (final c in list)
                    ListTile(
                      key: Key('census-resume-${c.uid}'),
                      leading: const Icon(Icons.play_circle_outline),
                      title: Text(c.rack ?? 'A rack not identified yet'),
                      subtitle: Text('${c.items} unit${c.items == 1 ? '' : 's'} so far'),
                      onTap: () => context.push('/census/${c.uid}'),
                    ),
                ],
          loading: () => [const LinearProgressIndicator()],
          error: (e, _) => [ProblemView(e, onRetry: () => ref.invalidate(openCensusesProvider))],
        ),
      ]),
    );
  }
}

/// Find a record by what it is called; with [types], only those.
Future<LinkTarget?> pickRecord(BuildContext context, WidgetRef ref, {required String title, Set<String>? types}) =>
    showModalBottomSheet<LinkTarget>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RecordPicker(title: title, types: types),
    );

class _RecordPicker extends ConsumerStatefulWidget {
  const _RecordPicker({required this.title, this.types});
  final String title;
  final Set<String>? types;

  @override
  ConsumerState<_RecordPicker> createState() => _RecordPickerState();
}

class _RecordPickerState extends ConsumerState<_RecordPicker> {
  List<LinkTarget> _found = const [];
  bool _busy = false;

  Future<void> _search(String q) async {
    if (q.trim().length < 2) return;
    setState(() => _busy = true);
    try {
      final r = await ref.read(lookupRepositoryProvider).search(q.trim());
      final t = widget.types;
      setState(() => _found = r.assets.where((a) => t == null || t.contains(a.subtitle)).toList());
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SizedBox(
          height: MediaQuery.of(context).size.height * 0.7,
          child: Column(children: [
            ListTile(title: Text(widget.title, style: Theme.of(context).textTheme.titleMedium)),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                key: const Key('record-picker-q'),
                autofocus: true,
                decoration: const InputDecoration(hintText: 'Name, key or serial', prefixIcon: Icon(Icons.search)),
                onSubmitted: _search,
                onChanged: (v) => v.length >= 3 ? _search(v) : null,
              ),
            ),
            if (_busy) const LinearProgressIndicator(),
            Expanded(
              child: ListView(children: [
                for (final a in _found)
                  ListTile(
                    title: Text(a.title ?? a.key ?? a.uid),
                    subtitle: Text([a.key, a.subtitle].whereType<String>().join(' · ')),
                    onTap: () => Navigator.of(context).pop(a),
                  ),
              ]),
            ),
          ]),
        ),
      );
}

String _percent(double? c) => c == null ? '' : ' · ${(c * 100).round()}% sure';

/// One proposal: what was read, how sure, where — and "Use" to take it.
class CensusProposalTile extends StatelessWidget {
  const CensusProposalTile(this.p, {super.key, required this.onUse, this.taken = false});
  final CensusProposal p;
  final VoidCallback onUse;
  final bool taken;

  static String name(String f) => switch (f) {
        'start_u' => 'Lowest unit (U)',
        'height_u' => 'Height (U)',
        'product_model' => 'Product model',
        'type' => 'Type',
        _ => f[0].toUpperCase() + f.substring(1),
      };

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ListTile(
      key: Key('census-proposal-${p.field}'),
      dense: true,
      leading: Icon(p.weak ? Icons.help_outline : Icons.auto_awesome, color: p.weak ? scheme.tertiary : scheme.primary),
      title: Text('${name(p.field)}: ${p.display}'),
      subtitle: Text([
        p.source == 'catalogue' ? 'from the catalogue' : 'read on the ${p.source}',
        if (p.evidence != null) '“${p.evidence}”',
        if (!p.grounded) 'not seen in the photo: check it',
      ].join(' · ') + _percent(p.confidence)),
      trailing: taken
          ? const Icon(Icons.check, key: Key('census-proposal-taken'))
          : TextButton(key: Key('census-use-${p.field}'), onPressed: onUse, child: const Text('Use')),
    );
  }
}

/// A survey: the rack, its units, and the review before saving.
class CensusScreen extends ConsumerStatefulWidget {
  const CensusScreen({super.key, required this.uid});
  final String uid;

  @override
  ConsumerState<CensusScreen> createState() => _CensusScreenState();
}

class _CensusScreenState extends ConsumerState<CensusScreen> {
  bool _busy = false;

  Future<T?> _do<T>(Future<T> Function() f) async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final r = await f();
      ref.invalidate(censusProvider(widget.uid));
      ref.invalidate(censusReviewProvider(widget.uid));
      return r;
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
      return null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _rackPhoto(String role) async {
    final photo = await pickPhoto(context, ref, title: 'Photo of the rack');
    if (photo == null) return;
    final out = await _do(() => ref.read(censusRepositoryProvider).photo(widget.uid, role, photo));
    if (out?.note != null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(out!.note!)));
    }
  }

  Future<void> _unitPhoto() async {
    final photo = await pickPhoto(context, ref, title: 'Photo of the rack');
    if (photo == null) return;
    final out = await _do(() => ref.read(censusRepositoryProvider).photo(widget.uid, 'device', photo));
    if (out?.item != null && mounted) context.push('/census/${widget.uid}/unit/${out!.item}');
  }

  Future<void> _newRack(Census c) async {
    final values = await showModalBottomSheet<Map<String, Object?>>(
        context: context, isScrollControlled: true, builder: (_) => _NewRackSheet(rack: c.rack));
    if (values != null) await _do(() => ref.read(censusRepositoryProvider).setRack(widget.uid, values: values));
  }

  Future<void> _save() async {
    final out = await _do(() => ref.read(censusRepositoryProvider).apply(widget.uid));
    if (out == null || !mounted) return;
    ref.invalidate(openCensusesProvider);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${out.name} saved: ${out.changes.length} unit(s).')));
    context.go('/asset/${out.uid}');
  }

  @override
  Widget build(BuildContext context) {
    final survey = ref.watch(censusProvider(widget.uid));
    return Scaffold(
      appBar: AppBar(title: const Text('Rack survey'), actions: [
        IconButton(
          tooltip: 'Leave it for later',
          icon: const Icon(Icons.pause_circle_outline),
          onPressed: () => context.pop(),
        ),
      ]),
      body: survey.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(censusProvider(widget.uid))),
        data: (c) => ListView(key: const Key('census-body'), children: [
          if (_busy) const LinearProgressIndicator(),
          if (c.state != 'open') NoticeBar(icon: Icons.info_outline, text: 'This survey is ${c.state}.'),
          const SectionHeader('1 · The rack'),
          ListTile(
            title: Text(c.rack.name),
            subtitle: Text(c.rack.isNew
                ? 'Not recorded yet${c.rack.values['place_uid'] == null ? '' : ' · room chosen'}'
                    '${c.rack.values['position_confirmed'] == true ? ' · point on the plan confirmed' : ''}'
                : 'In ARGUS · ${c.rack.height} U'),
            trailing: c.rack.isNew
                ? TextButton(key: const Key('census-rack-edit'), onPressed: () => _newRack(c), child: const Text('Identify'))
                : null,
          ),
          Wrap(spacing: 8, children: [
            OutlinedButton.icon(key: const Key('census-rack-front'), onPressed: _busy ? null : () => _rackPhoto('rack_front'),
                icon: const Icon(Icons.photo_camera_outlined),
                label: Text('Front${c.rack.photos.any((p) => p.role == 'rack_front') ? ' ✓' : ''}')),
            OutlinedButton.icon(key: const Key('census-rack-rear'), onPressed: _busy ? null : () => _rackPhoto('rack_rear'),
                icon: const Icon(Icons.photo_camera_back_outlined),
                label: Text('Rear${c.rack.photos.any((p) => p.role == 'rack_rear') ? ' ✓' : ''}')),
          ]),
          if (c.rack.isNew)
            for (final p in c.rack.proposals.values)
              CensusProposalTile(p, onUse: () => _do(() =>
                  ref.read(censusRepositoryProvider).setRack(widget.uid, values: {p.field == 'key' ? 'key' : 'name': p.value}))),
          if (c.rack.isNew && c.rack.candidates.isNotEmpty) ...[
            const ListTile(dense: true, title: Text('It may be one already recorded:')),
            for (final r in c.rack.candidates)
              ListTile(
                key: Key('census-rack-candidate-${r.uid}'),
                dense: true,
                title: Text(r.name),
                subtitle: Text([r.key, r.why].whereType<String>().join(' · ')),
                trailing: TextButton(
                    onPressed: () => _do(() => ref.read(censusRepositoryProvider).setRack(widget.uid, existing: r.uid)),
                    child: const Text('It is this one')),
              ),
          ],
          const SectionHeader('2 · Its units'),
          RackDrawing(units: c.rack.height, items: c.items,
              onTap: (item) => context.push('/census/${widget.uid}/unit/${item.id}')),
          for (final i in c.items)
            ListTile(
              key: Key('census-unit-${i.id}'),
              leading: Icon(i.decision == 'skip'
                  ? Icons.remove_circle_outline
                  : i.span == null || i.decision == null
                      ? Icons.pending_outlined
                      : Icons.check_circle_outline),
              title: Text(i.title),
              subtitle: Text([
                if (i.span != null) 'U${i.span!.from}${i.span!.to > i.span!.from ? '–U${i.span!.to}' : ''}',
                switch (i.decision) { 'link' => 'existing record', 'create' => 'new record', 'skip' => 'left out', _ => 'to decide' },
                if (i.duplicates.any((d) => d.strength != 'weak') && !i.duplicateChecked && i.decision != 'link')
                  'possible duplicate',
              ].join(' · ')),
              onTap: () => context.push('/census/${widget.uid}/unit/${i.id}'),
            ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: FilledButton.icon(key: const Key('census-unit-photo'), onPressed: _busy ? null : _unitPhoto,
                icon: const Icon(Icons.add_a_photo_outlined), label: const Text('Photograph a unit')),
          ),
          const SectionHeader('3 · Review and save'),
          _Review(uid: widget.uid, onSave: _busy ? null : _save,
              onOpen: (item) => context.push('/census/${widget.uid}/unit/$item')),
          const SizedBox(height: 24),
        ]),
      ),
    );
  }
}

class _Review extends ConsumerWidget {
  const _Review({required this.uid, required this.onSave, required this.onOpen});
  final String uid;
  final VoidCallback? onSave;
  final void Function(String item) onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final review = ref.watch(censusReviewProvider(uid));
    return review.when(
      loading: () => const LinearProgressIndicator(),
      error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(censusReviewProvider(uid))),
      data: (r) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final m in r.missing)
          ListTile(
            key: Key('census-missing-${m.item ?? 'rack'}-${m.field}'),
            dense: true,
            leading: const Icon(Icons.edit_note),
            title: Text(m.message),
            onTap: m.item == null ? null : () => onOpen(m.item!),
          ),
        for (final p in r.problems)
          ListTile(dense: true, leading: Icon(Icons.error_outline, color: Theme.of(context).colorScheme.error), title: Text(p)),
        if (r.ok) ...[
          for (final ch in r.changes) ListTile(dense: true, leading: const Icon(Icons.arrow_right), title: Text(ch)),
          if (r.newRecords > 0) ListTile(dense: true, title: Text('${r.newRecords} new record(s) will be made.')),
        ],
        Padding(
          padding: const EdgeInsets.all(12),
          child: FilledButton(
            key: const Key('census-save'),
            onPressed: r.ok ? onSave : null,
            child: Text(r.ok ? 'Save the rack' : 'Resolve what is listed first'),
          ),
        ),
      ]),
    );
  }
}

class _NewRackSheet extends ConsumerStatefulWidget {
  const _NewRackSheet({required this.rack});
  final CensusRack rack;

  @override
  ConsumerState<_NewRackSheet> createState() => _NewRackSheetState();
}

class _NewRackSheetState extends ConsumerState<_NewRackSheet> {
  late final _name = TextEditingController(text: (widget.rack.values['name'] ?? '').toString());
  late final _key = TextEditingController(text: (widget.rack.values['key'] ?? '').toString());
  late final _units = TextEditingController(text: '${widget.rack.values['units'] ?? 42}');
  String? _room = '';
  String? _roomName;
  ({String plan, double x, double y})? _point;

  @override
  void initState() {
    super.initState();
    _room = widget.rack.values['place_uid'] as String?;
    final p = widget.rack.values;
    if (p['plan_uid'] != null && p['x'] != null && p['position_confirmed'] == true) {
      _point = (plan: p['plan_uid'] as String, x: (p['x'] as num).toDouble(), y: (p['y'] as num).toDouble());
    }
  }

  Future<void> _pickPoint() async {
    final room = _room;
    if (room == null) return;
    final plans = await ref.read(locationRepositoryProvider).plansFor([room]);
    if (!mounted) return;
    if (plans.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('That room has no floor plan.')));
      return;
    }
    final plan = plans.first.plan;
    final at = await context.push<Offset>('/plan/${plan.uid}?pick=1');
    if (at != null) setState(() => _point = (plan: plan.uid, x: at.dx, y: at.dy));
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom, left: 16, right: 16, top: 12),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('The new rack', style: Theme.of(context).textTheme.titleMedium),
          TextField(key: const Key('census-rack-name'), controller: _name, decoration: const InputDecoration(labelText: 'Name')),
          TextField(key: const Key('census-rack-key'), controller: _key,
              decoration: const InputDecoration(labelText: 'Identifier on its label (optional)')),
          TextField(key: const Key('census-rack-units'), controller: _units, keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Height in units (U)')),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(_roomName ?? (_room == null ? 'Which room is it in?' : 'Room chosen')),
            trailing: TextButton(
              key: const Key('census-rack-room'),
              onPressed: () async {
                final r = await pickRecord(context, ref, title: 'Which room?');
                if (r != null) setState(() { _room = r.uid; _roomName = r.title; _point = null; });
              },
              child: const Text('Choose'),
            ),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(_point == null ? 'Its point on the floor plan (optional)' : 'Point on the plan confirmed'),
            trailing: TextButton(key: const Key('census-rack-point'), onPressed: _room == null ? null : _pickPoint,
                child: Text(_point == null ? 'Choose on the plan' : 'Change')),
          ),
          FilledButton(
            key: const Key('census-rack-done'),
            onPressed: () => Navigator.of(context).pop(<String, Object?>{
              'name': _name.text.trim(),
              if (_key.text.trim().isNotEmpty) 'key': _key.text.trim(),
              'units': int.tryParse(_units.text.trim()),
              'place_uid': _room,
              if (_point != null) ...{'plan_uid': _point!.plan, 'x': _point!.x, 'y': _point!.y, 'position_confirmed': true},
            }),
            child: const Text('Done'),
          ),
          const SizedBox(height: 16),
        ]),
      );
}

/// One unit: its photos, what was read, the values taken or typed, which record it is, and where in the rack.
class CensusUnitScreen extends ConsumerStatefulWidget {
  const CensusUnitScreen({super.key, required this.uid, required this.item});
  final String uid;
  final String item;

  @override
  ConsumerState<CensusUnitScreen> createState() => _CensusUnitScreenState();
}

class _CensusUnitScreenState extends ConsumerState<CensusUnitScreen> {
  bool _busy = false;

  Future<void> _set({Map<String, Object?>? values, String? decision, String? assetUid, bool? duplicateChecked}) async {
    setState(() => _busy = true);
    try {
      await ref.read(censusRepositoryProvider).setItem(widget.uid, widget.item, values: values, decision: decision,
          assetUid: assetUid, duplicateChecked: duplicateChecked);
      ref.invalidate(censusProvider(widget.uid));
      ref.invalidate(censusReviewProvider(widget.uid));
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _photo(String role) async {
    final photo = await pickPhoto(context, ref, title: 'Photo of the rack');
    if (photo == null) return;
    setState(() => _busy = true);
    try {
      final out = await ref.read(censusRepositoryProvider).photo(widget.uid, role, photo, item: widget.item);
      ref.invalidate(censusProvider(widget.uid));
      if (out.note != null && mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(out.note!)));
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _type(String field, CensusItem item, {bool number = false}) async {
    final c = TextEditingController(text: '${item.value(field) ?? ''}');
    final v = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(CensusProposalTile.name(field)),
        content: TextField(key: Key('census-type-$field'), controller: c, autofocus: true,
            keyboardType: number ? TextInputType.number : TextInputType.text),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: const Text('Cancel')),
          FilledButton(key: const Key('census-type-ok'), onPressed: () => Navigator.pop(d, c.text.trim()), child: const Text('OK')),
        ],
      ),
    );
    if (v == null) return;
    await _set(values: {field: v.isEmpty ? null : (number ? int.tryParse(v) : v)});
  }

  Future<void> _chooseType() async {
    final types = await ref.read(objectTypesProvider.future);
    if (!mounted) return;
    final t = await showModalBottomSheet<EquipmentType>(
      context: context,
      builder: (_) => ListView(children: [for (final t in types) ListTile(title: Text(t.name), onTap: () => Navigator.pop(context, t))]),
    );
    if (t != null) await _set(values: {'type': {'value': t.uid, 'source': 'person'}});
  }

  @override
  Widget build(BuildContext context) {
    final survey = ref.watch(censusProvider(widget.uid));
    return Scaffold(
      appBar: AppBar(title: const Text('Unit')),
      body: survey.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(censusProvider(widget.uid))),
        data: (c) {
          final i = c.item(widget.item);
          if (i == null) return const Center(child: Text('This unit was removed from the survey.'));
          final fields = ['type', 'name', 'manufacturer', 'model', 'serial', 'height_u', 'start_u', 'face'];
          return ListView(key: const Key('census-unit-body'), children: [
            if (_busy) const LinearProgressIndicator(),
            ListTile(title: Text(i.title), subtitle: Text('${i.photos.length} photo(s)${i.hasLabel ? ', label included' : ''}')),
            Wrap(spacing: 8, children: [
              OutlinedButton.icon(onPressed: _busy ? null : () => _photo('device'), icon: const Icon(Icons.photo_camera_outlined),
                  label: const Text('Another view')),
              OutlinedButton.icon(key: const Key('census-label-photo'), onPressed: _busy ? null : () => _photo('label'),
                  icon: const Icon(Icons.qr_code_2), label: const Text('Its label')),
            ]),
            if (i.note != null) NoticeBar(icon: Icons.info_outline, text: i.note!),
            const SectionHeader('Read on the photos'),
            if (i.proposals.isEmpty) const ListTile(dense: true, title: Text('Nothing was read: type what you see.')),
            for (final p in i.proposals.values)
              CensusProposalTile(p, taken: i.values[p.field]?.value == p.value && i.values[p.field]?.source == p.source,
                  onUse: () => _set(values: {p.field: p.taken()})),
            const SectionHeader('Its values'),
            for (final f in fields)
              ListTile(
                key: Key('census-value-$f'),
                dense: true,
                title: Text(CensusProposalTile.name(f)),
                subtitle: Text(i.value(f) == null
                    ? (f == 'start_u' || f == 'height_u' || f == 'serial' || f == 'model' ? 'not read — type it' : '—')
                    : '${f == 'type' ? (i.proposals['type']?.label ?? i.value(f)) : i.value(f)}'
                        ' · ${i.values[f]!.source == 'person' ? 'typed' : 'from the ${i.values[f]!.source}'}'),
                trailing: const Icon(Icons.edit, size: 18),
                onTap: () => f == 'type'
                    ? _chooseType()
                    : f == 'face'
                        ? _set(values: {'face': i.value('face') == 'rear' ? 'front' : 'rear'})
                        : _type(f, i, number: f.endsWith('_u')),
              ),
            const SectionHeader('Where in the rack'),
            RackDrawing(
              units: c.rack.height,
              items: c.items,
              current: i.id,
              onPickU: (u) => _set(values: {'start_u': u}),
            ),
            const SectionHeader('Which record'),
            if (i.duplicates.isNotEmpty) ...[
              for (final d in i.duplicates)
                ListTile(
                  key: Key('census-duplicate-${d.uid}'),
                  dense: true,
                  leading: Icon(Icons.content_copy, color: d.strength == 'strong' ? Theme.of(context).colorScheme.error : null),
                  title: Text('May be ${d.key ?? d.name}'),
                  subtitle: Text('${d.why}${d.mountedIn == null ? '' : ' · now in ${d.mountedIn}'}'),
                  trailing: TextButton(onPressed: () => _set(assetUid: d.uid), child: const Text('It is this one')),
                ),
              if (i.decision == 'create')
                CheckboxListTile(
                  key: const Key('census-not-duplicate'),
                  dense: true,
                  value: i.duplicateChecked,
                  onChanged: (v) => _set(duplicateChecked: v ?? false),
                  title: const Text('I checked: it is another unit'),
                ),
            ],
            RadioGroup<String>(
              groupValue: i.decision,
              onChanged: (v) async {
                if (v == 'link') {
                  final r = await pickRecord(context, ref, title: 'Which record is it?');
                  if (r != null) await _set(assetUid: r.uid);
                } else if (v != null) {
                  await _set(decision: v);
                }
              },
              child: const Column(children: [
                RadioListTile<String>(key: Key('census-decision-link'), value: 'link', title: Text('A record already in ARGUS')),
                RadioListTile<String>(key: Key('census-decision-create'), value: 'create', title: Text('A new record')),
                RadioListTile<String>(key: Key('census-decision-skip'), value: 'skip', title: Text('Leave it out')),
              ]),
            ),
            TextButton(
              onPressed: () async {
                await ref.read(censusRepositoryProvider).removeItem(widget.uid, widget.item);
                ref.invalidate(censusProvider(widget.uid));
                ref.invalidate(censusReviewProvider(widget.uid));
                if (context.mounted) context.pop();
              },
              child: const Text('Remove this unit from the survey'),
            ),
          ]);
        },
      ),
    );
  }
}
