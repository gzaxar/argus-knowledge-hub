import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../data/command_queue.dart';
import '../../core/problem.dart';
import '../../data/replacement_repositories.dart';
import '../../domain/capture.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';
import '../../widgets/pick_photo.dart';

const removalReasons = ['Failure', 'Maintenance', 'Upgrade', 'Unknown'];

/// Guided equipment replacement (flutter-app-design §8). Each step shows what the server knows and
/// the person confirms it:
/// 1. What is installed at the Position now.
/// 2. The outgoing unit: the recorded one, or the unit actually found, which becomes a review item.
/// 3. The removal details: time, reason, condition, work reference.
/// 4. The incoming unit, scanned, or registered from its nameplate. Never made from a name.
/// 5. The server's dry run: identity, I-INS-1, compatibility, and the consequences behind the
///    Position, from the confirmed graph.
/// 6. One command: applied at once, or a proposal for an approver with the reasons.
class ReplaceScreen extends ConsumerStatefulWidget {
  const ReplaceScreen({super.key, required this.positionUid});

  final String positionUid;

  @override
  ConsumerState<ReplaceScreen> createState() => _ReplaceScreenState();
}

class _ReplaceScreenState extends ConsumerState<ReplaceScreen> {
  ReplacementDraft? _draft;
  bool _outgoingIsRecorded = true;
  LinkTarget? _outgoingScanned;
  LinkTarget? _incoming;
  String? _incomingNotFound;
  final _condition = TextEditingController();
  final _photos = <PickedPhoto>[];
  ReplacementPreview? _preview;
  PendingCommand? _result;
  bool _unchecked = false; // ARGUS could not be reached for the dry run
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _condition.dispose();
    super.dispose();
  }

  ReplacementDraft _ensureDraft(AssetDetail a) {
    final current = a.current.isEmpty ? null : a.current.first;
    return _draft ??= ReplacementDraft(
      commandUid: const Uuid().v4(),
      positionUid: widget.positionUid,
      seenInstallationUid: current?.uid,
    )..outgoingUid = current?.asset?.uid;
  }

  void _changed() => setState(() => _preview = null); // a changed draft needs a new dry run

  Future<LinkTarget?> _scan({required String role}) async {
    final path = await context.push<String>('/scan?pick=1');
    if (path == null) return null;
    try {
      final t = await ref.read(lookupRepositoryProvider).resolveLink(path);
      if (t.kind == RecordKind.position) {
        setState(() => _error = 'That label is a Position, not a unit. Scan the label on the $role unit itself.');
        return null;
      }
      return t;
    } on Problem catch (p) {
      if (p.code == ProblemCode.notFound && role == 'incoming') {
        setState(() => _incomingNotFound = Uri.decodeComponent(path.split('/').last));
      } else {
        setState(() => _error = p.message);
      }
      return null;
    }
  }

  Future<void> _scanOutgoing(ReplacementDraft d) async {
    final t = await _scan(role: 'removed');
    if (t == null) return;
    setState(() {
      _outgoingScanned = t;
      d.outgoingUid = t.uid;
      _preview = null;
    });
  }

  Future<void> _scanIncoming(ReplacementDraft d) async {
    setState(() => _incomingNotFound = null);
    final t = await _scan(role: 'incoming');
    if (t == null) return;
    setState(() {
      _incoming = t;
      d.incomingUid = t.uid;
      _preview = null;
    });
  }

  Future<void> _register(ReplacementDraft d) async {
    final label = _incomingNotFound ?? '';
    final uid = await context.push<String>('/register?pick=1&label=${Uri.encodeComponent(label)}');
    if (uid == null) return;
    setState(() {
      _incoming = LinkTarget(kind: RecordKind.asset, uid: uid, title: 'Newly registered unit ($label)');
      _incomingNotFound = null;
      d.incomingUid = uid;
      _preview = null;
    });
  }

  Future<void> _pickTime(ReplacementDraft d) async {
    final now = DateTime.now();
    final day = await showDatePicker(context: context, firstDate: DateTime(now.year - 1), lastDate: now, initialDate: d.at);
    if (day == null || !mounted) return;
    final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(d.at));
    if (t == null) return;
    setState(() {
      d.at = DateTime(day.year, day.month, day.day, t.hour, t.minute);
      _preview = null;
    });
  }

  Future<void> _check(ReplacementDraft d) async {
    if (d.incomingUid == null) {
      setState(() => _error = 'Scan the incoming unit first.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      d.condition = _condition.text.trim().isEmpty ? null : _condition.text.trim();
      final p = await ref.read(replacementRepositoryProvider).preview(d);
      setState(() {
        _preview = p;
        _unchecked = false;
      });
    } on Problem catch (p) {
      setState(() {
        _error = p.code == ProblemCode.offline
            ? 'ARGUS cannot be reached to check it. You can save the replacement on this device; ARGUS checks it '
                'when it arrives, and anything that changed meanwhile goes to review.'
            : p.message;
        _unchecked = p.code == ProblemCode.offline;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit(ReplacementDraft d) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      d.evidence = {
        'photos': _photos.length,
        if (!_outgoingIsRecorded && _outgoingScanned != null) 'outgoing_scanned': _outgoingScanned!.uid,
      };
      final queue = ref.read(queueProvider.notifier);
      final command = await queue.enqueue(
        kind: 'replacement.submit',
        key: 'replace:${d.commandUid}',
        target: widget.positionUid,
        seenVersion: d.seenInstallationUid,
        label: 'Replace the unit at the Position',
        payload: {
          'command_uid': d.commandUid,
          'position_uid': d.positionUid,
          'seen_installation_uid': d.seenInstallationUid,
          'outgoing_uid': d.outgoingUid,
          'incoming_uid': d.incomingUid,
          'at': d.at.toUtc().toIso8601String(),
          'precision': d.precision,
          'reason': d.reason,
          'condition': d.condition,
          'work_reference': d.workReference,
          'evidence': d.evidence,
        },
      );
      // Evidence photos go with the incoming unit, whatever the outcome.
      for (final (i, photo) in _photos.indexed) {
        await queue.enqueue(
          kind: 'attachment.upload',
          key: 'replace:${d.commandUid}:photo:$i',
          target: d.incomingUid,
          label: 'Photo of the installed unit',
          payload: {'asset_uid': d.incomingUid},
          attachments: [QueueController.photo(photo)],
        );
      }
      final sent = await queue.sendNow(command);
      if (sent.status == CommandStatus.rejected || sent.status == CommandStatus.expired) {
        throw Problem(ProblemCode.invalid, describe(sent));
      }
      ref.invalidate(assetDetailProvider(widget.positionUid));
      setState(() => _result = sent);
    } on Problem catch (p) {
      setState(() => _error = p.reviewItem != null ? '${p.message} (review item ${p.reviewItem})' : p.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(assetDetailProvider(widget.positionUid));
    final loaded = r.value;
    if (loaded != null && loaded.isPosition) _ensureDraft(loaded);
    return Scaffold(
      appBar: AppBar(title: const Text('Replace the unit')),
      bottomNavigationBar: _actions(),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e),
        data: (a) => a.isPosition ? _body(a, _ensureDraft(a)) : const ProblemView('Only a Position holds a unit.'),
      ),
    );
  }

  Widget _body(AssetDetail a, ReplacementDraft d) {
    final theme = Theme.of(context);
    if (_result != null) return _done(a, _result!);
    final current = a.current.isEmpty ? null : a.current.first;
    final open = a.tickets.where((t) => t.open).toList();
    return ListView(padding: const EdgeInsets.only(bottom: 120), children: [
      ListTile(
        leading: const Icon(Icons.place_outlined),
        title: Text(a.name),
        subtitle: Text('Position · ${a.key}'),
      ),
      const SectionHeader('1 · Installed now'),
      ListTile(
        key: const Key('replace-current'),
        leading: const Icon(Icons.memory),
        title: Text(current?.asset?.label ?? 'Nothing is recorded here'),
        subtitle: current == null ? null : Text('since ${formatWhenDate(current.from?.nominal)}'),
      ),
      if (current != null) ...[
        const SectionHeader('2 · The unit you remove'),
        RadioGroup<bool>(
          groupValue: _outgoingIsRecorded,
          onChanged: (v) => setState(() {
            _outgoingIsRecorded = v ?? true;
            d.outgoingUid = _outgoingIsRecorded ? current.asset?.uid : _outgoingScanned?.uid;
            _preview = null;
          }),
          child: Column(children: [
            RadioListTile<bool>(
                key: const Key('outgoing-recorded'), value: true, title: const Text('It is the recorded unit')),
            RadioListTile<bool>(
                key: const Key('outgoing-other'),
                value: false,
                title: const Text('It is a different unit'),
                subtitle: const Text('The difference goes to review; nothing is corrected silently')),
          ]),
        ),
        if (!_outgoingIsRecorded)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(children: [
              Expanded(child: Text(_outgoingScanned?.title ?? 'Scan the label on the unit you removed.')),
              OutlinedButton.icon(
                  key: const Key('scan-outgoing'),
                  onPressed: () => _scanOutgoing(d),
                  icon: const Icon(Icons.qr_code_scanner),
                  label: const Text('Scan')),
            ]),
          ),
      ],
      const SectionHeader('3 · When and why'),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('At ${formatWhenDate(d.at)} ${TimeOfDay.fromDateTime(d.at).format(context)}')),
            TextButton(onPressed: () => _pickTime(d), child: const Text('Change')),
          ]),
          DropdownButtonFormField<String>(
            key: const Key('replace-reason'),
            isExpanded: true,
            initialValue: d.reason,
            decoration: const InputDecoration(labelText: 'Reason', border: OutlineInputBorder()),
            items: [for (final r in removalReasons) DropdownMenuItem(value: r, child: Text(r))],
            onChanged: (v) {
              d.reason = v ?? d.reason;
              _changed();
            },
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('replace-condition'),
            controller: _condition,
            decoration: const InputDecoration(labelText: 'Condition of the removed unit', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String?>(
            key: const Key('replace-work'),
            isExpanded: true,
            initialValue: d.workReference,
            decoration: const InputDecoration(labelText: 'Work reference (ticket)', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem<String?>(value: null, child: Text('None')),
              for (final t in open) DropdownMenuItem<String?>(value: t.uid, child: Text(t.title, overflow: TextOverflow.ellipsis)),
            ],
            onChanged: (v) {
              d.workReference = v;
              _changed();
            },
          ),
        ]),
      ),
      const SectionHeader('4 · The unit you install'),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
                child: Text(_incoming?.title ?? 'Scan the label on the new unit.',
                    key: const Key('replace-incoming'), style: theme.textTheme.bodyLarge)),
            OutlinedButton.icon(
                key: const Key('scan-incoming'),
                onPressed: () => _scanIncoming(d),
                icon: const Icon(Icons.qr_code_scanner),
                label: const Text('Scan')),
          ]),
          if (_incomingNotFound != null) ...[
            const SizedBox(height: 8),
            Text('“$_incomingNotFound” is not known to ARGUS. Register the unit from its nameplate; it is never '
                'made from the Position\'s name.'),
            const SizedBox(height: 8),
            FilledButton.tonalIcon(
              key: const Key('replace-register'),
              onPressed: () => _register(d),
              icon: const Icon(Icons.add_box_outlined),
              label: const Text('Register this unit'),
            ),
          ],
          const SizedBox(height: 8),
          Wrap(spacing: 8, children: [
            for (final (i, _) in _photos.indexed) Chip(label: Text('Photo ${i + 1}')),
            TextButton.icon(
              key: const Key('replace-photo'),
              onPressed: () async {
                final p = await pickPhoto(context, ref, title: 'Photo of the new unit');
                if (p != null) setState(() => _photos.add(p));
              },
              icon: const Icon(Icons.add_a_photo_outlined),
              label: const Text('Photo of the installed unit'),
            ),
          ]),
        ]),
      ),
      if (_preview != null) ..._previewView(_preview!),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text(_error!, key: const Key('replace-error'), style: TextStyle(color: theme.colorScheme.error)),
        ),
    ]);
  }

  Widget? _actions() {
    final d = _draft;
    if (d == null || _result != null) return null;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          Expanded(
            child: OutlinedButton(
                key: const Key('replace-check'), onPressed: _busy ? null : () => _check(d), child: const Text('Check')),
          ),
          const SizedBox(width: 12),
          Expanded(
            flex: 2,
            child: FilledButton(
              key: const Key('replace-submit'),
              onPressed: _busy || ((_preview == null || _preview!.refused) && !_unchecked) ? null : () => _submit(d),
              child: Text(_unchecked && _preview == null
                  ? 'Save for later'
                  : (_preview?.outcome == 'propose' ? 'Submit for review' : 'Replace')),
            ),
          ),
        ]),
      ),
    );
  }

  List<Widget> _previewView(ReplacementPreview p) {
    final theme = Theme.of(context);
    return [
      const SectionHeader('5 · What ARGUS checked'),
      NoticeBar(
        key: const Key('replace-outcome'),
        icon: p.refused ? Icons.block : (p.outcome == 'propose' ? Icons.rate_review_outlined : Icons.check_circle_outline),
        severe: p.refused,
        text: switch (p.outcome) {
          'apply' => 'Ready: the old Installation ends and the new one starts, in one step.',
          'propose' => 'This goes to review: ${p.reasons.join('; ')}.',
          _ => 'This cannot be submitted. See below.',
        },
      ),
      for (final c in p.checks)
        ListTile(
          dense: true,
          leading: Icon(c.blocking ? Icons.error_outline : Icons.warning_amber,
              color: c.blocking ? theme.colorScheme.error : theme.colorScheme.tertiary),
          title: Text(c.message),
        ),
      SectionHeader('Behind this Position', trailing: 'confirmed graph'),
      if (p.accessPoints.isEmpty && p.segments.isEmpty && p.hiddenSegments == 0)
        const ListTile(dense: true, title: Text('No Access Points or bus segments are recorded behind it.')),
      for (final ap in p.accessPoints)
        ListTile(dense: true, leading: const Icon(Icons.lan_outlined), title: Text(ap.label), subtitle: const Text('Access Point')),
      for (final s in p.segments)
        ListTile(
          dense: true,
          leading: Icon(s.needsConfirmation ? Icons.warning_amber : Icons.cable,
              color: s.safetyClass != 'none' ? theme.colorScheme.error : null),
          title: Text(s.name),
          subtitle: Text([
            if (s.safetyClass != 'none') 'safety class ${s.safetyClass}',
            s.needsConfirmation ? 'port to be confirmed by a steward' : 'attaches to the new unit',
          ].join(' · ')),
        ),
      if (p.hiddenSegments > 0)
        ListTile(
            dense: true,
            leading: const Icon(Icons.lock_outline),
            title: Text('${p.hiddenSegments} segment(s) you cannot see are behind it; they are checked too.')),
      for (final t in p.openTickets)
        ListTile(dense: true, leading: const Icon(Icons.confirmation_number_outlined), title: Text(t.title)),
      for (final doc in p.documents)
        ListTile(
            dense: true,
            leading: const Icon(Icons.description_outlined),
            title: Text(doc.title),
            onTap: () => context.push('/document/${doc.uid}')),
    ];
  }

  Widget _done(AssetDetail a, PendingCommand c) {
    final applied = c.status == CommandStatus.accepted && c.note == 'Replaced.';
    final title = switch (c.status) {
      CommandStatus.accepted => applied ? 'Replaced' : 'Submitted for review',
      CommandStatus.conflict => 'Sent to review',
      _ => 'Saved on this device',
    };
    final text = switch (c.status) {
      CommandStatus.accepted => applied
          ? 'The new Installation is recorded. ARGUS is updating the relations behind the Position; ports that '
              'need a steward will show in the review queue.'
          : 'An approver confirms it. Nothing is changed until then. ${c.note ?? ''}',
      CommandStatus.conflict => 'The Position changed since you looked. Nothing was applied; your replacement and '
          'its evidence are waiting in the review queue.',
      _ => 'ARGUS cannot be reached. The replacement is sent when it can, and checked against the Position then.',
    };
    return ListView(padding: const EdgeInsets.all(16), children: [
      Icon(applied ? Icons.check_circle : (c.open ? Icons.cloud_upload_outlined : Icons.rate_review),
          size: 56, color: Theme.of(context).colorScheme.primary),
      const SizedBox(height: 12),
      Text(title, key: const Key('replace-done'), textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 8),
      Text(text, textAlign: TextAlign.center),
      const SizedBox(height: 24),
      FilledButton(onPressed: () => context.pushReplacement('/asset/${a.uid}'), child: const Text('Back to the Position')),
    ]);
  }
}
