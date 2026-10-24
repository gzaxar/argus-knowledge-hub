import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../core/problem.dart';
import '../../domain/capture.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';
import '../capture/proposal_tile.dart';
import '../../widgets/photo_text.dart';

/// Reporting a problem where it happens (flutter-app-design §9).
///
/// - The subject is the Position or unit scanned; involved Equipment is derived by the server
///   from the Installation at the occurrence time.
/// - An operational incident says when it happened, with the precision known (I-TKT-4).
/// - The assistant drafts from the person's words, but nothing it proposes is used until the
///   person takes it. Causes stay hypotheses (§23.7).
/// - The guide shows similar open tickets before a new one is made.
class ReportScreen extends ConsumerStatefulWidget {
  const ReportScreen({super.key, required this.subjectUid});

  final String subjectUid;

  @override
  ConsumerState<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends ConsumerState<ReportScreen> {
  // One command, one key: a retry after a lost answer is the same ticket (§3.2).
  final _uid = const Uuid().v4();
  final _words = TextEditingController();
  final _title = TextEditingController();
  final _description = TextEditingController();
  TicketKind? _kind;
  WhenInput? _when;
  String? _impact;
  final _photos = <PickedPhoto>[];
  AssistResult? _assist;
  final _taken = <String>{};
  List<GuideCheck> _checks = const [];
  bool _similarSeen = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _words.dispose();
    _title.dispose();
    _description.dispose();
    super.dispose();
  }

  Map<String, Object?> get _attributes => {
        if (_when != null) 'occurred_from': _when!.toJson(),
        'argus_impact': ?(_impactDef == null ? _impact : _impactDef!.choiceValue(_impact)),
      };

  Map<String, Object?> get _draft => {
        'uid': _uid,
        'title': _title.text.trim(),
        'description': _description.text.trim(),
        'asset_uid': widget.subjectUid,
        'schema_uid': ?_kind?.uid,
        'attributes': _attributes,
      };

  Future<void> _draftWithAi() async {
    if (_words.text.trim().isEmpty) {
      setState(() => _error = 'Say in your own words what happened first.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await ref.read(intakeRepositoryProvider).assistTicket(_words.text.trim(), _draft);
      setState(() => _assist = r);
    } on Problem catch (p) {
      setState(() => _error = 'The assistant is not available (${p.message}). Fill in the report by hand; nothing is lost.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Operational impact, as the chosen kind defines it (its options are the workspace's, never a list of
  /// the app's own: a list kept here goes stale the day the type changes, and the server refuses its values).
  AttributeDef? get _impactDef => _kind == null
      ? null
      : ref.read(schemaAttributesProvider(_kind!.uid)).value?.where((d) => d.key == 'argus_impact').firstOrNull;

  void _take(Proposal p, List<TicketKind> kinds) {
    setState(() {
      _taken.add(p.field);
      switch (p.field) {
        case 'title':
          _title.text = p.value.toString();
        case 'description':
          _description.text = p.value.toString();
        case 'schema_uid':
          _kind = kinds.where((k) => k.uid == p.value).firstOrNull ?? _kind;
        case 'attributes.argus_impact':
          // The assistant names the option by its id; what is kept is the option's value, as the type has it.
          // Without the type (offline), the proposal is kept as it is: the server reads an id as its value.
          final def = _impactDef;
          _impact = def == null ? p.value?.toString() : (def.choiceValue(p.value) ?? _impact);
        case 'attributes.occurred_from':
          final w = When.fromJson(p.value);
          if (w?.nominal != null) {
            final precision =
                WhenPrecision.values.where((e) => e.name == w!.precision).firstOrNull ?? WhenPrecision.instant;
            _when = WhenInput(w!.nominal!, precision);
          }
      }
    });
  }

  Future<void> _addPhoto() async {
    final photo = await ref.read(photoSourceProvider).take();
    if (photo != null) setState(() => _photos.add(photo));
  }

  Future<void> _pickWhen(WhenPrecision precision) async {
    final now = DateTime.now();
    final day = await showDatePicker(
        context: context, firstDate: DateTime(now.year - 2), lastDate: now, initialDate: _when?.at ?? now);
    if (day == null || !mounted) return;
    var at = day;
    if (precision == WhenPrecision.instant) {
      final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(_when?.at ?? now));
      if (t == null) return;
      at = DateTime(day.year, day.month, day.day, t.hour, t.minute);
    }
    setState(() => _when = WhenInput(at, precision));
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_title.text.trim().isEmpty) {
        throw Problem(ProblemCode.invalid, 'Say in one line what is wrong.');
      }
      if ((_kind?.isIncident ?? false) && _when == null) {
        throw Problem(ProblemCode.invalid, 'Say when it happened. The day is enough if you do not know the time.');
      }
      // The guide needs ARGUS; offline, the report is kept and checked by the server when it arrives.
      try {
        final checks = await ref.read(intakeRepositoryProvider).guideTicket(_draft);
        setState(() => _checks = checks);
        if (checks.any((c) => c.blocking)) return;
        if (!_similarSeen && checks.any((c) => c.id == 'similar')) {
          setState(() => _similarSeen = true);
          return; // shown above the button; a second press reports anyway
        }
      } on Problem catch (p) {
        if (p.code != ProblemCode.offline) rethrow;
      }
      final queue = ref.read(queueProvider.notifier);
      final create = await queue.enqueue(
        kind: 'ticket.create',
        key: 'ticket:$_uid',
        target: _uid,
        label: 'Report: ${_title.text.trim()}',
        payload: {
          'uid': _uid,
          'title': _title.text.trim(),
          'description': _description.text.trim(),
          'asset_uid': widget.subjectUid,
          'schema_uid': _kind?.uid,
          'attributes': _attributes,
        },
      );
      for (final (i, photo) in _photos.indexed) {
        await queue.enqueue(
          kind: 'attachment.upload',
          key: 'photo:$_uid:$i',
          target: _uid,
          label: 'Photo for “${_title.text.trim()}”',
          payload: {'ticket_uid': _uid},
          attachments: [QueueController.photo(photo)],
          dependsOn: [create.id], // the ticket first, then its photos (A64)
        );
      }
      if (_assist != null) {
        await queue.enqueue(
          kind: 'intake.outcome',
          key: 'outcome:$_uid',
          label: 'What was kept of the assistant’s draft',
          payload: {
            'run_id': _assist!.runId,
            'record_uid': _uid,
            'final': {
              'title': _title.text.trim(),
              'description': _description.text.trim(),
              'schema_uid': ?_kind?.uid,
              for (final e in _attributes.entries) 'attributes.${e.key}': e.value,
            },
          },
          dependsOn: [create.id],
        );
      }
      final sent = await queue.sendNow(create);
      if (sent.needsPerson) throw Problem(ProblemCode.invalid, describe(sent));
      ref.invalidate(assetDetailProvider(widget.subjectUid));
      if (!mounted) return;
      if (sent.open) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describe(sent))));
      }
      context.pushReplacement('/ticket/$_uid');
    } on Problem catch (p) {
      setState(() => _error = p.field != null ? '${p.message} (${p.field})' : p.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final subject = ref.watch(assetDetailProvider(widget.subjectUid));
    final kinds = ref.watch(ticketKindsProvider);
    final theme = Theme.of(context);
    final kindList = kinds.value ?? const <TicketKind>[];
    _kind ??= kindList.where((k) => k.isIncident).firstOrNull;
    final impact = _kind == null
        ? null
        : ref.watch(schemaAttributesProvider(_kind!.uid)).value?.where((d) => d.key == 'argus_impact').firstOrNull;
    final a = subject.value;
    final similarOpen = (a?.tickets ?? const <TicketSummary>[]).where((t) => t.open).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Report a problem')),
      body: ListView(padding: const EdgeInsets.only(bottom: 120), children: [
        if (a != null)
          ListTile(
            leading: Icon(a.isPosition ? Icons.place_outlined : Icons.memory),
            title: Text(a.name),
            subtitle: Text('${a.isPosition ? 'Position' : 'Equipment'} · ${a.key}'),
          ),
        if (similarOpen.isNotEmpty) ...[
          SectionHeader('Already open here', trailing: '${similarOpen.length}'),
          for (final t in similarOpen.take(3))
            ListTile(
              dense: true,
              leading: const Icon(Icons.confirmation_number_outlined),
              title: Text(t.title),
              subtitle: const Text('If it is the same problem, add a comment there instead.'),
              onTap: () => context.push('/ticket/${t.uid}'),
            ),
        ],
        const SectionHeader('In your own words'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: TextField(
            key: const Key('report-words'),
            controller: _words,
            minLines: 2,
            maxLines: 5,
            decoration: InputDecoration(
                hintText: 'What did you see, when, and what did you already try?',
                border: const OutlineInputBorder(),
                suffixIcon: PhotoTextButton(key: const Key('photo-text-report-words'), controller: _words)),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key('report-assist'),
              onPressed: _busy ? null : _draftWithAi,
              icon: const Icon(Icons.auto_awesome),
              label: const Text('Draft the report from this'),
            ),
          ),
        ),
        if (_assist != null) ..._proposals(_assist!, kindList),
        const SectionHeader('The ticket'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Column(children: [
            TextField(
              key: const Key('report-title'),
              controller: _title,
              decoration: const InputDecoration(labelText: 'What is wrong, in one line', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('report-description'),
              controller: _description,
              minLines: 3,
              maxLines: 8,
              decoration: InputDecoration(
                  labelText: 'Details',
                  border: const OutlineInputBorder(),
                  suffixIcon: PhotoTextButton(key: const Key('photo-text-report-description'), controller: _description)),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: const Key('report-kind'),
              initialValue: _kind?.uid,
              decoration: const InputDecoration(labelText: 'Kind', border: OutlineInputBorder()),
              items: [for (final k in kindList) DropdownMenuItem(value: k.uid, child: Text(k.name))],
              onChanged: (v) => setState(() => _kind = kindList.where((k) => k.uid == v).firstOrNull),
            ),
            const SizedBox(height: 12),
            if (impact != null && impact.options.isNotEmpty)
              DropdownButtonFormField<String>(
                key: Key('report-impact-${_kind?.uid}'),
                initialValue: impact.choiceValue(_impact),
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Operational impact', border: OutlineInputBorder()),
                items: [
                  const DropdownMenuItem(value: null, child: Text('—')),
                  for (final o in {for (final o in impact.options) o.value})
                    DropdownMenuItem(value: o, child: Text(o)),
                ],
                onChanged: (v) => setState(() => _impact = v),
              ),
          ]),
        ),
        SectionHeader('When it happened', trailing: (_kind?.isIncident ?? false) ? 'required' : null),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            ChoiceChip(
              key: const Key('when-now'),
              label: const Text('Just now'),
              selected: false,
              onSelected: (_) => setState(() => _when = WhenInput(DateTime.now(), WhenPrecision.instant)),
            ),
            ActionChip(label: const Text('Exact time'), onPressed: () => _pickWhen(WhenPrecision.instant)),
            ActionChip(label: const Text('A day'), onPressed: () => _pickWhen(WhenPrecision.day)),
            ActionChip(label: const Text('A month'), onPressed: () => _pickWhen(WhenPrecision.month)),
          ]),
        ),
        if (_when != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(_whenText(_when!), key: const Key('when-chosen'), style: theme.textTheme.bodyLarge),
          ),
        SectionHeader('Photos', trailing: '${_photos.length}'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            for (final (i, p) in _photos.indexed)
              Stack(children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.memory(p.bytes, width: 88, height: 88, fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => Container(
                          width: 88, height: 88, color: theme.colorScheme.surfaceContainerHighest,
                          child: const Icon(Icons.image_outlined))),
                ),
                Positioned(
                  right: 0,
                  top: 0,
                  child: IconButton.filledTonal(
                      iconSize: 16,
                      onPressed: () => setState(() => _photos.removeAt(i)),
                      icon: const Icon(Icons.close)),
                ),
              ]),
            OutlinedButton.icon(
              key: const Key('report-photo'),
              onPressed: _busy ? null : _addPhoto,
              icon: const Icon(Icons.add_a_photo_outlined),
              label: const Text('Add photo'),
            ),
          ]),
        ),
        if (_checks.isNotEmpty) ...[
          const SectionHeader('Before you send'),
          for (final c in _checks.where((c) => c.level != 'info')) _check(c),
        ],
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(_error!, key: const Key('report-error'), style: TextStyle(color: theme.colorScheme.error)),
          ),
      ]),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: FilledButton.icon(
            key: const Key('report-submit'),
            onPressed: _busy ? null : _submit,
            icon: _busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.send),
            label: Text(_similarSeen && _checks.any((c) => c.id == 'similar') ? 'Report anyway' : 'Send report'),
          ),
        ),
      ),
    );
  }

  List<Widget> _proposals(AssistResult r, List<TicketKind> kinds) {
    final open = r.proposals.values.where((p) => !_taken.contains(p.field)).toList();
    return [
      SectionHeader('Suggested by the assistant', trailing: open.isEmpty ? null : 'not used until you take them'),
      if (r.redacted > 0)
        const NoticeBar(icon: Icons.password, text: 'Something that looked like a password was removed before the assistant saw it.'),
      for (final p in open) ProposalTile(p, onTake: () => _take(p, kinds)),
      if (open.length > 1)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              key: const Key('report-take-all'),
              onPressed: () {
                for (final p in open) {
                  _take(p, kinds);
                }
              },
              child: const Text('Use all suggestions'),
            ),
          ),
        ),
      for (final h in r.hypotheses)
        ListTile(
          dense: true,
          leading: const Icon(Icons.help_outline),
          title: Text(h),
          subtitle: const Text('Unconfirmed hypothesis: not a cause until someone confirms it on the web'),
        ),
      for (final d in r.dropped)
        ListTile(
            dense: true,
            leading: const Icon(Icons.block),
            title: Text('Not used: ${ProposalTile.fieldName(d.field)}'),
            subtitle: Text(d.reason)),
    ];
  }

  Widget _check(GuideCheck c) {
    final scheme = Theme.of(context).colorScheme;
    return ListTile(
      key: Key('check-${c.id}'),
      leading: Icon(c.blocking ? Icons.error_outline : Icons.warning_amber,
          color: c.blocking ? scheme.error : scheme.tertiary),
      title: Text(c.message),
      subtitle: c.links.isEmpty
          ? null
          : Wrap(spacing: 6, children: [
              for (final l in c.links)
                ActionChip(
                  label: Text(l.name),
                  onPressed: () => context.push(l.path.startsWith('/tickets/') ? '/ticket/${l.uid}' : '/asset/${l.uid}'),
                ),
            ]),
    );
  }

  static String _whenText(WhenInput w) {
    final l = w.at.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return switch (w.precision) {
      WhenPrecision.instant => '${l.year}-${two(l.month)}-${two(l.day)} ${two(l.hour)}:${two(l.minute)}',
      WhenPrecision.day => 'On ${l.year}-${two(l.month)}-${two(l.day)} (time not known)',
      WhenPrecision.month => 'In ${l.year}-${two(l.month)} (day not known)',
    };
  }
}
