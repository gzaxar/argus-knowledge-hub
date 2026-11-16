import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/capture.dart';
import '../../domain/models.dart' show RecordKind;
import '../../widgets/common.dart';
import 'proposal_tile.dart';
import '../../widgets/pick_photo.dart';

/// The identifiers a nameplate carries, always offered even before the assistant answers.
const baseFields = ['manufacturer', 'model', 'serial', 'inventory_number'];

/// Registering a unit the person has in front of them (revision §24.6, §24.8).
///
/// 1. The person photographs the nameplate.
/// 2. The server reads it and proposes values, each with its confidence and where it was read.
/// 3. The person takes, corrects or leaves each value, then runs the guide's checks, which include
///    duplicates.
/// 4. Saving creates the unit with the person's values, attaches the photo as evidence, and records
///    what was kept.
///
/// No Equipment is made from a Position, channel or scanned name (I-MOB-6): only from a photo, from
/// values the person types, or from a similar unit the person scans (its kind and attributes, never its
/// identifiers). A QR code read from the unit's own label becomes its label.
class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key, this.label, this.pick = false, this.photoFirst = false});

  /// Opened to photograph the nameplate (from Ask ARGUS): the camera opens at once.
  final bool photoFirst;

  /// Return the new unit's uid to the screen that asked (the replacement), instead of opening it.
  final bool pick;

  /// A label value that found nothing (a serial, an inventory number), offered as the serial.
  final String? label;

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _uid = const Uuid().v4();
  final _name = TextEditingController();
  final _attrs = <String, TextEditingController>{
    for (final f in baseFields) f: TextEditingController(),
  };
  final _qr = TextEditingController();
  EquipmentType? _type;
  PickedPhoto? _photo;
  /// Attributes taken from a similar unit, beyond the fields shown: sent with the new one.
  Map<String, Object?> _copied = const {};
  String? _copiedFrom;
  AssistResult? _assist;
  final _taken = <String>{};
  List<GuideCheck> _checks = const [];
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // A label that found nothing: a web address is a QR code printed for this unit, anything else its serial.
    final label = widget.label;
    if (label != null) (label.contains('://') ? _qr : _attrs['serial']!).text = label;
    if (widget.photoFirst) WidgetsBinding.instance.addPostFrameCallback((_) => _capture());
  }

  @override
  void dispose() {
    _qr.dispose();
    _name.dispose();
    for (final c in _attrs.values) {
      c.dispose();
    }
    super.dispose();
  }

  Map<String, Object?> get _attributes => {
        ..._copied,
        for (final e in _attrs.entries)
          if (e.value.text.trim().isNotEmpty) e.key: e.value.text.trim(),
      };

  /// What identifies one unit, and so is never copied from another.
  static const identifiers = {
    'serial', 'inventory_number', 'mac', 'qrcode', 'barcode', 'asset_tag', 'former_key', 'former_uid', 'alias',
  };

  /// Scans (or reads, or types) a similar unit's label, and starts from it: its kind and attributes, not
  /// its identifiers — the person edits what differs.
  Future<void> _copyFrom() async {
    final path = await context.push<String>('/scan?pick=1');
    if (path == null || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final target = await ref.read(lookupRepositoryProvider).resolveLink(path);
      if (target.kind != RecordKind.asset) {
        throw Problem(ProblemCode.invalid, 'That label is not on equipment. Scan the label of a similar unit.');
      }
      final a = await ref.read(assetRepositoryProvider).detail(target.uid);
      setState(() {
        _type = EquipmentType(a.schemaUid, a.type);
        if (_name.text.trim().isEmpty) _name.text = a.name;
        final copied = <String, Object?>{};
        for (final e in a.attributes.entries) {
          if (identifiers.contains(e.key) || e.key.startsWith('argus_') || e.value == null) continue;
          if (_attrs.containsKey(e.key)) {
            if (_attrs[e.key]!.text.trim().isEmpty) _attrs[e.key]!.text = e.value.toString();
          } else {
            copied[e.key] = e.value;
          }
        }
        _copied = copied;
        _copiedFrom = a.name;
      });
    } on Problem catch (p) {
      setState(() => _error = p.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _scanQr() async {
    final path = await context.push<String>('/scan?pick=1');
    if (path == null || !mounted) return;
    setState(() => _qr.text = path.startsWith('/lookup/') ? Uri.decodeComponent(path.substring(8)) : path);
  }

  Map<String, Object?> get _draft => {
        'uid': _uid,
        'name': _name.text.trim(),
        'schema_uid': ?_type?.uid,
        'attributes': _attributes,
      };

  Future<void> _capture() async {
    final photo = await pickPhoto(context, ref, title: 'Photo of the nameplate or the unit');
    if (photo == null) return;
    setState(() {
      _photo = photo;
      _busy = true;
      _error = null;
    });
    try {
      final r = await ref.read(intakeRepositoryProvider).assistAssetPhoto(photo, _draft);
      setState(() {
        _assist = r;
        _checks = r.checks;
      });
    } on Problem catch (p) {
      setState(() => _error = 'The nameplate could not be read (${p.message}). Type the values from it; '
          'the photo is kept as evidence.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _take(Proposal p, List<EquipmentType> types) {
    setState(() {
      _taken.add(p.field);
      if (p.field == 'schema_uid') {
        _type = types.where((t) => t.uid == p.value).firstOrNull ?? EquipmentType(p.value.toString(), p.display);
      } else if (p.field == 'name') {
        _name.text = p.value.toString();
      } else if (p.field.startsWith('attributes.')) {
        _attrs.putIfAbsent(p.field.substring(11), TextEditingController.new).text = p.value.toString();
      }
    });
  }

  Future<void> _check() async {
    setState(() => _busy = true);
    try {
      final checks = await ref.read(intakeRepositoryProvider).guideAsset(_draft);
      setState(() => _checks = checks);
    } on Problem catch (p) {
      setState(() => _error = p.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_type == null) throw Problem(ProblemCode.invalid, 'Choose what kind of equipment it is.');
      if (_name.text.trim().isEmpty) throw Problem(ProblemCode.invalid, 'Give it a name.');
      final checks = await ref.read(intakeRepositoryProvider).guideAsset(_draft);
      setState(() => _checks = checks);
      if (checks.any((c) => c.blocking)) return;
      final uid = await ref.read(equipmentCommandsProvider).register(
          uid: _uid, typeUid: _type!.uid, name: _name.text.trim(), attributes: _attributes);
      var labelled = true;
      if (_qr.text.trim().isNotEmpty) {
        try {
          await ref.read(assetRepositoryProvider).addLabel(uid, const Uuid().v4(), 'qrcode', _qr.text.trim());
        } on Problem {
          labelled = false;
        }
      }
      var photoSent = true;
      if (_photo != null) {
        try {
          await ref.read(uploadRepositoryProvider).uploadAndAttach(_photo!, assetUid: uid, key: 'nameplate:$uid');
        } on Problem {
          photoSent = false;
        }
      }
      if (_assist != null) {
        await ref.read(intakeRepositoryProvider).recordOutcome(_assist!.runId, uid, {
          'schema_uid': _type!.uid,
          'name': _name.text.trim(),
          for (final e in _attributes.entries) 'attributes.${e.key}': e.value,
        });
      }
      if (!mounted) return;
      if (!photoSent || !labelled) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(!labelled
                ? 'Registered, but its QR code was not added: add it from its page.'
                : 'Registered, but the nameplate photo was not sent.')));
      }
      widget.pick ? context.pop(uid) : context.pushReplacement('/asset/$uid');
    } on Problem catch (p) {
      setState(() => _error = p.field != null ? '${p.message} (${p.field})' : p.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final types = ref.watch(objectTypesProvider).value ?? const <EquipmentType>[];
    final theme = Theme.of(context);
    final open = (_assist?.proposals.values ?? const <Proposal>[]).where((p) => !_taken.contains(p.field)).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Register equipment')),
      body: ListView(padding: const EdgeInsets.only(bottom: 120), children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Row(children: [
            if (_photo != null)
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.memory(_photo!.bytes, width: 96, height: 96, fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const SizedBox(width: 96, height: 96, child: Icon(Icons.image))),
                ),
              ),
            Expanded(
              child: FilledButton.tonalIcon(
                key: const Key('register-photo'),
                onPressed: _busy ? null : _capture,
                icon: const Icon(Icons.photo_camera_outlined),
                label: Text(_photo == null ? 'Photograph the nameplate' : 'Take another photo'),
              ),
            ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: OutlinedButton.icon(
            key: const Key('register-copy'),
            onPressed: _busy ? null : _copyFrom,
            icon: const Icon(Icons.copy_all_outlined),
            label: const Text('Copy from similar equipment (scan its label)'),
          ),
        ),
        if (_copiedFrom != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: NoticeBar(
              key: const Key('register-copied'),
              icon: Icons.copy_all_outlined,
              text: 'Started from $_copiedFrom: its kind, manufacturer, model and other attributes. Its serial, '
                  'inventory number and labels are not copied — this unit has its own.',
            ),
          ),
        if (_busy) const LinearProgressIndicator(),
        if (_assist != null) ...[
          SectionHeader('Read from the photo', trailing: open.isEmpty ? null : 'not used until you take them'),
          if (_assist!.redacted > 0)
            const NoticeBar(
                icon: Icons.password,
                text: 'Something that looked like a password was on the plate. It was not kept, and it is not proposed.'),
          for (final p in open) ProposalTile(p, onTake: () => _take(p, types)),
          if (open.length > 1)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  key: const Key('register-take-all'),
                  onPressed: () {
                    for (final p in open) {
                      _take(p, types);
                    }
                  },
                  child: const Text('Use all'),
                ),
              ),
            ),
          for (final d in _assist!.dropped)
            ListTile(
                dense: true,
                leading: const Icon(Icons.block),
                title: Text('Not used: ${ProposalTile.fieldName(d.field)}'),
                subtitle: Text(d.reason)),
        ],
        const SectionHeader('The unit'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Column(children: [
            DropdownMenu<String>(
              key: const Key('register-type'),
              expandedInsets: EdgeInsets.zero,
              enableFilter: true,
              requestFocusOnTap: true,
              label: const Text('Kind of equipment'),
              initialSelection: _type?.uid,
              dropdownMenuEntries: [
                for (final t in [...types, if (_type != null && !types.any((t) => t.uid == _type!.uid)) _type!])
                  DropdownMenuEntry(value: t.uid, label: t.name),
              ],
              onSelected: (v) => setState(() => _type = types.where((t) => t.uid == v).firstOrNull ?? _type),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('register-name'),
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('register-qr'),
              controller: _qr,
              decoration: InputDecoration(
                labelText: 'QR code on its label (optional)',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  key: const Key('register-qr-scan'),
                  tooltip: 'Scan it',
                  icon: const Icon(Icons.qr_code_scanner),
                  onPressed: _busy ? null : _scanQr,
                ),
              ),
            ),
            for (final e in _attrs.entries) ...[
              const SizedBox(height: 12),
              TextField(
                key: Key('register-attr-${e.key}'),
                controller: e.value,
                decoration: InputDecoration(
                    labelText: ProposalTile.fieldName('attributes.${e.key}'), border: const OutlineInputBorder()),
              ),
            ],
          ]),
        ),
        if (_checks.isNotEmpty) ...[
          const SectionHeader('Checks'),
          for (final c in _checks)
            ListTile(
              key: Key('check-${c.id}'),
              leading: Icon(
                  c.blocking ? Icons.error_outline : (c.level == 'warning' ? Icons.warning_amber : Icons.info_outline),
                  color: c.blocking ? theme.colorScheme.error : null),
              title: Text(c.message),
              subtitle: c.links.isEmpty
                  ? null
                  : Wrap(spacing: 6, children: [
                      for (final l in c.links)
                        ActionChip(label: Text(l.name), onPressed: () => context.push('/asset/${l.uid}')),
                    ]),
            ),
        ],
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(_error!, key: const Key('register-error'), style: TextStyle(color: theme.colorScheme.error)),
          ),
      ]),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            Expanded(
              child: OutlinedButton(
                  key: const Key('register-check'), onPressed: _busy ? null : _check, child: const Text('Check')),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 2,
              child: FilledButton(
                  key: const Key('register-save'), onPressed: _busy ? null : _save, child: const Text('Register')),
            ),
          ]),
        ),
      ),
    );
  }
}
