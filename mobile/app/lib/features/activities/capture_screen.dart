import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../core/problem.dart';
import '../../data/activity_repository.dart';
import '../../data/command_queue.dart' show PendingCommand;
import '../../widgets/common.dart';
import '../ask/voice.dart';
import 'activities_screen.dart';
import '../../widgets/photo_text.dart';

const _draftPrefix = 'capture.draft.';

/// Capture by voice: say what happened or what you will do; the assistant proposes a **ticket** or an
/// **activity**, you correct it, and only your confirmation creates it (backend services/capture.py).
///
/// The phone turns speech into text; only the text goes to ARGUS, and no audio is kept. Without the assistant
/// the text stays and you fill the form yourself; offline, it is kept as a draft to review later — nothing is
/// created from a guess.
class CaptureScreen extends ConsumerStatefulWidget {
  const CaptureScreen({super.key, this.assetUid, this.assetLabel});

  final String? assetUid;
  final String? assetLabel;

  @override
  ConsumerState<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends ConsumerState<CaptureScreen> {
  final _text = TextEditingController();
  final _answer = TextEditingController();
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _system = TextEditingController();
  late final Voice _voice;
  bool _listening = false;
  bool _working = false;
  String? _error;
  String? _notice;
  DateTime _capturedAt = DateTime.now();
  CaptureProposal? _proposal;
  bool _manual = false;
  String? _kind; // ticket | activity
  // Ticket fields.
  String? _typeUid, _category, _impact;
  DateTime? _occurredAt;
  String? _addTo; // an existing ticket to add the words to instead
  // Activity fields.
  String _status = 'planned';
  DateTime? _when;
  bool _allDay = false;
  String? _rrule, _rruleText;
  String? _linkTicket;
  String _visibility = 'workspace';
  ({String kind, String uid, bool queued})? _created;
  List<MapEntry<String, Map<String, dynamic>>> _drafts = [];

  @override
  void initState() {
    super.initState();
    _voice = ref.read(voiceProvider);
    _loadDrafts();
  }

  @override
  void dispose() {
    _voice.stopListening();
    for (final c in [_text, _answer, _title, _description, _system]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadDrafts() async {
    final all = await ref.read(localStoreProvider).readPrefix(_draftPrefix);
    if (!mounted) return;
    setState(() => _drafts = [
          for (final e in all.entries) MapEntry(e.key, Map<String, dynamic>.from(jsonDecode(e.value) as Map)),
        ]..sort((a, b) => '${b.value['captured_at']}'.compareTo('${a.value['captured_at']}')));
  }

  // ------------------------------------------------------------------ hearing

  Future<void> _mic() async {
    if (_listening) {
      await _voice.stopListening();
      setState(() => _listening = false);
      return;
    }
    if (!await _voice.canListen()) {
      setState(() => _error = 'The microphone is not available or not allowed for ARGUS Field.');
      return;
    }
    final before = _text.text.trim();
    setState(() {
      _listening = true;
      _error = null;
      _capturedAt = DateTime.now();
    });
    await _voice.listen((words, last) {
      if (!mounted) return;
      setState(() {
        _text.text = before.isEmpty ? words : '$before $words';
        if (last) _listening = false;
      });
    }, onError: (e) {
      if (!mounted) return;
      setState(() {
        _listening = false;
        _error = e == VoiceError.microphone
            ? 'The microphone is not available or not allowed for ARGUS Field.'
            : 'Speech recognition did not work: type what you wanted to say, or try again.';
      });
    });
  }

  // ------------------------------------------------------------------ proposing

  Future<void> _propose({Map<String, String>? clarification}) async {
    final text = _text.text.trim();
    if (text.isEmpty) return;
    if (_listening) {
      await _voice.stopListening();
      _listening = false;
    }
    setState(() {
      _working = true;
      _error = null;
      _notice = null;
    });
    try {
      final tz = await ref.read(deviceTimezoneProvider.future);
      final p = await ref.read(activityRepositoryProvider).classify(
          transcript: text, capturedAt: _capturedAt, timezone: tz, assetUid: widget.assetUid,
          clarification: clarification);
      if (!mounted) return;
      _apply(p);
    } on Problem catch (p) {
      if (!mounted) return;
      if (p.code == ProblemCode.offline) {
        await _saveDraft(text);
      } else {
        // The assistant is unavailable: the words stay, the person chooses and fills the form.
        setState(() {
          _manual = true;
          _proposal = null;
          _error = '${p.message} You can choose and fill it in yourself.';
          _title.text = text.split(RegExp(r'[.\n]')).first;
          _description.text = text;
        });
      }
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  void _apply(CaptureProposal p) {
    final t = p.ticket, a = p.activity;
    setState(() {
      _proposal = p;
      _manual = false;
      _answer.clear();
      _kind = p.kind == 'uncertain' ? null : p.kind;
      _typeUid = t['type_uid'] as String?;
      _category = t['category'] as String?;
      _impact = t['impact'] as String?;
      _occurredAt = DateTime.tryParse('${t['occurred_at']}')?.toLocal();
      _system.text = '${t['system'] ?? ''}';
      _status = '${a['status'] ?? 'planned'}';
      final when = a['actual_end'] ?? a['actual_start'] ?? a['planned_start'];
      _when = DateTime.tryParse('${when ?? ''}')?.toLocal();
      _allDay = a['all_day'] == true;
      _rrule = a['rrule'] as String?;
      _rruleText = a['recurrence_text'] as String?;
      _linkTicket = a['about_open_ticket'] == true && p.similar.isNotEmpty ? '${p.similar.first['uid']}' : null;
      _addTo = null;
      _syncText();
    });
  }

  void _syncText() {
    final source = _kind == 'activity' ? _proposal?.activity : _proposal?.ticket;
    if (source == null) return;
    _title.text = '${source['title'] ?? ''}';
    _description.text = '${source['description'] ?? ''}';
  }

  Future<void> _saveDraft(String text) async {
    final id = const Uuid().v4();
    await ref.read(localStoreProvider).write('$_draftPrefix$id', jsonEncode({
      'text': text,
      'captured_at': _capturedAt.toIso8601String(),
      'asset_uid': widget.assetUid,
      'asset_label': widget.assetLabel,
    }));
    await _loadDrafts();
    if (mounted) {
      setState(() => _notice = 'Offline: kept as a draft on this phone. Open it when you are back online — nothing '
          'is created until you confirm.');
    }
  }

  Future<void> _openDraft(MapEntry<String, Map<String, dynamic>> d) async {
    setState(() {
      _text.text = '${d.value['text']}';
      _capturedAt = DateTime.tryParse('${d.value['captured_at']}') ?? DateTime.now();
    });
    await ref.read(localStoreProvider).delete(d.key);
    await _loadDrafts();
    await _propose();
  }

  // ------------------------------------------------------------------ confirming

  Future<void> _confirm() async {
    final queue = ref.read(queueProvider.notifier);
    final title = _title.text.trim();
    if (_addTo == null && title.isEmpty) {
      setState(() => _error = 'Give it a title.');
      return;
    }
    setState(() {
      _working = true;
      _error = null;
    });
    final uid = const Uuid().v4();
    try {
      if (_kind == 'ticket' && _addTo != null) {
        final c = await queue.enqueue(kind: 'ticket.comment', key: 'comment:$uid', target: _addTo, label: 'Added to a ticket',
            payload: {'ticket_uid': _addTo, 'comment_uid': uid, 'body': _text.text.trim()});
        await _send(c, 'ticket', _addTo!);
      } else if (_kind == 'ticket') {
        final c = await queue.enqueue(kind: 'ticket.create', key: 'ticket:$uid', target: uid, label: 'Report: $title', payload: {
          'uid': uid,
          'title': title,
          'description': _description.text.trim(),
          'asset_uid': widget.assetUid,
          'schema_uid': _typeUid,
          'attributes': {
            // The option's value is what is stored; the proposal and the list name options by id.
            'argus_category': ?_valueOf(_proposal?.categories, _category),
            'argus_impact': ?_valueOf(_proposal?.impacts, _impact),
            if (_system.text.trim().isNotEmpty) 'argus_system': _system.text.trim(),
            if (_occurredAt != null) 'argus_downtime_start': withOffset(_occurredAt!),
          },
        });
        await _send(c, 'ticket', uid);
      } else {
        final tz = await ref.read(deviceTimezoneProvider.future);
        final when = _when == null ? null : withOffset(_when!);
        final c = await queue.enqueue(kind: 'activity.create', key: 'activity:$uid', target: uid, label: 'Activity: $title', payload: {
          'uid': uid,
          'title': title,
          'description': _description.text.trim(),
          'status': _rrule != null ? 'planned' : _status,
          'timezone': tz,
          'all_day': _allDay,
          'visibility': _visibility,
          'asset_uid': widget.assetUid,
          'ticket_uid': _linkTicket,
          if (_rrule != null) 'rrule': _rrule,
          if (_status == 'planned' || _rrule != null) 'planned_start': when,
          if (_status == 'in_progress' && _rrule == null) 'actual_start': when ?? withOffset(DateTime.now()),
          if (_status == 'completed' && _rrule == null) 'actual_end': when ?? withOffset(DateTime.now()),
          'provenance': {
            'source': 'voice capture',
            'transcript': _text.text.trim(),
            'captured_at': withOffset(_capturedAt),
            'model': _proposal?.model,
            'proposed': _proposal == null ? null : {'kind': _proposal!.kind, 'explanation': _proposal!.explanation},
          },
        });
        await _send(c, 'activity', uid);
      }
    } on Problem catch (p) {
      if (mounted) setState(() => _error = p.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  /// Sent at once when ARGUS can be reached; else it waits in the queue, with the same key at every retry.
  Future<void> _send(PendingCommand c, String kind, String uid) async {
    final sent = await ref.read(queueProvider.notifier).sendNow(c);
    if (sent.needsPerson) throw Problem(ProblemCode.invalid, describe(sent));
    if (!mounted) return;
    setState(() => _created = (kind: kind, uid: uid, queued: sent.open));
    ref.invalidate(activityListProvider);
  }

  // ------------------------------------------------------------------ the screen

  static String? _valueOf(List<Map<String, dynamic>>? options, String? id) {
    if (id == null) return null;
    final o = (options ?? const []).where((o) => '${o['id']}' == id).firstOrNull;
    return o == null ? id : '${o['value'] ?? id}';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = _proposal;
    return Scaffold(
      appBar: AppBar(title: const Text('Capture by voice')),
      body: ListView(key: const Key('capture-list'), padding: const EdgeInsets.all(16), children: [
        if (_created != null) ..._createdView(context) else ...[
          NoticeBar(
            icon: Icons.privacy_tip_outlined,
            text: 'The phone turns your speech into text; only the text is sent to ARGUS, to propose a record. '
                'No audio is kept. Nothing is created until you confirm.',
          ),
          if (widget.assetLabel != null)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text('About ${widget.assetLabel}')),
          const SizedBox(height: 12),
          for (final d in _drafts)
            Card(
              key: Key('capture-draft-${d.key}'),
              child: ListTile(
                leading: const Icon(Icons.drafts_outlined),
                title: Text('${d.value['text']}', maxLines: 2, overflow: TextOverflow.ellipsis),
                subtitle: const Text('Draft kept offline: tap to propose it now'),
                onTap: _working ? null : () => _openDraft(d),
              ),
            ),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: TextField(
                key: const Key('capture-text'),
                controller: _text,
                minLines: 3,
                maxLines: 8,
                maxLength: 4000,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  border: const OutlineInputBorder(),
                  labelText: _listening ? 'Listening…' : 'What happened, or what you will do',
                  hintText: '“The vacuum pump failed last night” · “I replaced the filter yesterday”',
                  suffixIcon: PhotoTextButton(
                      key: const Key('photo-text-capture'), controller: _text, onInserted: () => setState(() {})),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              key: const Key('capture-mic'),
              iconSize: 32,
              tooltip: _listening ? 'Stop listening' : 'Speak',
              style: _listening ? IconButton.styleFrom(backgroundColor: theme.colorScheme.error) : null,
              icon: Icon(_listening ? Icons.stop : Icons.mic),
              onPressed: _working ? null : _mic,
            ),
          ]),
          if (_error != null)
            Padding(padding: const EdgeInsets.only(bottom: 8), child: NoticeBar(icon: Icons.error_outline, text: _error!, severe: true)),
          if (_notice != null)
            Padding(padding: const EdgeInsets.only(bottom: 8), child: NoticeBar(key: const Key('capture-draft-saved'), icon: Icons.save_outlined, text: _notice!)),
          Row(children: [
            Expanded(
              child: FilledButton.icon(
                key: const Key('capture-propose'),
                onPressed: _working || _text.text.trim().isEmpty ? null : () => _propose(),
                icon: _working && p == null
                    ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.auto_awesome),
                label: Text(p == null ? 'Propose' : 'Propose again'),
              ),
            ),
            if (p == null && !_manual) ...[
              const SizedBox(width: 8),
              TextButton(
                key: const Key('capture-manual'),
                onPressed: () => setState(() {
                  _manual = true;
                  _description.text = _text.text.trim();
                  _title.text = _text.text.trim().split(RegExp(r'[.\n]')).first;
                }),
                child: const Text('Fill in myself'),
              ),
            ],
          ]),
          if (p != null || _manual) ..._proposalView(context, p),
        ],
      ]),
    );
  }

  List<Widget> _proposalView(BuildContext context, CaptureProposal? p) {
    final theme = Theme.of(context);
    final uncertain = _kind == 'activity' ? (p?.uncertainActivity ?? const []) : (p?.uncertainTicket ?? const []);
    return [
      const Divider(height: 32),
      if (p != null) ...[
        Text(p.kind == 'uncertain' ? 'Ticket or activity? Choose below.' : 'Proposed: ${p.kind}',
            key: const Key('capture-kind-proposed'), style: theme.textTheme.titleMedium),
        if (p.explanation.isNotEmpty) Text(p.explanation),
        for (final e in p.evidence)
          Text('“$e”', style: theme.textTheme.bodySmall?.copyWith(fontStyle: FontStyle.italic)),
      ],
      if (p?.clarification != null) _clarification(context, p!.clarification!),
      const SizedBox(height: 8),
      SegmentedButton<String>(
        key: const Key('capture-kind'),
        emptySelectionAllowed: true,
        segments: const [
          ButtonSegment(value: 'ticket', icon: Icon(Icons.confirmation_number_outlined), label: Text('Ticket')),
          ButtonSegment(value: 'activity', icon: Icon(Icons.event_note_outlined), label: Text('Activity')),
        ],
        selected: {?_kind},
        onSelectionChanged: (s) => setState(() {
          _kind = s.isEmpty ? null : s.first;
          _syncText();
        }),
      ),
      if (uncertain.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Wrap(spacing: 6, children: [
            const Text('To check:'),
            for (final u in uncertain) Chip(visualDensity: VisualDensity.compact, label: Text(u)),
          ]),
        ),
      if (_kind != null) ...[
        const SizedBox(height: 8),
        TextField(key: const Key('capture-title'), controller: _title, decoration: const InputDecoration(labelText: 'Title *')),
        TextField(
            key: const Key('capture-description'),
            controller: _description,
            minLines: 2,
            maxLines: 6,
            decoration: InputDecoration(
                labelText: 'Description',
                suffixIcon: PhotoTextButton(key: const Key('photo-text-capture-description'), controller: _description))),
        if (_kind == 'ticket') ..._ticketFields(context, p) else ..._activityFields(context, p),
        const SizedBox(height: 16),
        FilledButton(
          key: const Key('capture-confirm'),
          onPressed: _working ? null : _confirm,
          child: Text(_kind == 'ticket'
              ? (_addTo != null ? 'Add to the ticket' : 'Create the ticket')
              : 'Create the activity'),
        ),
      ],
    ];
  }

  Widget _clarification(BuildContext context, String question) => Card(
        key: const Key('capture-clarify'),
        color: Theme.of(context).colorScheme.secondaryContainer,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(question, style: Theme.of(context).textTheme.titleSmall),
            Row(children: [
              Expanded(
                  child: TextField(
                      key: const Key('capture-clarify-answer'),
                      controller: _answer,
                      onChanged: (_) => setState(() {}),
                      decoration: const InputDecoration(hintText: 'Your answer'))),
              IconButton(
                key: const Key('capture-clarify-send'),
                icon: const Icon(Icons.send),
                onPressed: _working || _answer.text.trim().isEmpty
                    ? null
                    : () => _propose(clarification: {'question': question, 'answer': _answer.text.trim()}),
              ),
            ]),
          ]),
        ),
      );

  List<Widget> _ticketFields(BuildContext context, CaptureProposal? p) => [
        DropdownButtonFormField<String?>(
          key: const Key('capture-type'),
          isExpanded: true,
          initialValue: _typeUid,
          decoration: const InputDecoration(labelText: 'Type'),
          items: [
            const DropdownMenuItem(value: null, child: Text('—')),
            for (final t in p?.ticketTypes ?? const <Map<String, dynamic>>[])
              DropdownMenuItem(value: '${t['uid']}', child: Text('${t['name']}', overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (v) => setState(() => _typeUid = v),
        ),
        DropdownButtonFormField<String?>(
          key: const Key('capture-category'),
          isExpanded: true,
          initialValue: _category,
          decoration: const InputDecoration(labelText: 'Category'),
          items: [
            const DropdownMenuItem(value: null, child: Text('—')),
            for (final o in p?.categories ?? const <Map<String, dynamic>>[])
              DropdownMenuItem(value: '${o['id']}', child: Text('${o['value']}')),
          ],
          onChanged: (v) => setState(() => _category = v),
        ),
        DropdownButtonFormField<String?>(
          key: const Key('capture-impact'),
          isExpanded: true,
          initialValue: _impact,
          decoration: const InputDecoration(labelText: 'Operational impact'),
          items: [
            const DropdownMenuItem(value: null, child: Text('—')),
            for (final o in p?.impacts ?? const <Map<String, dynamic>>[])
              DropdownMenuItem(value: '${o['id']}', child: Text('${o['value']}')),
          ],
          onChanged: (v) => setState(() => _impact = v),
        ),
        TextField(controller: _system, decoration: const InputDecoration(labelText: 'System')),
        _dateRow(context, 'Happened', _occurredAt, (d) => setState(() => _occurredAt = d), timeKnown: true),
        if ((p?.similar ?? const []).isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('Open tickets that look the same', style: Theme.of(context).textTheme.titleSmall),
          RadioGroup<String?>(
            groupValue: _addTo,
            onChanged: (v) => setState(() => _addTo = v),
            child: Column(children: [
              const RadioListTile<String?>(key: Key('capture-new-ticket'), value: null, title: Text('Create a new ticket')),
              for (final s in p!.similar)
                RadioListTile<String?>(
                  key: Key('capture-similar-${s['uid']}'),
                  value: '${s['uid']}',
                  title: Text('${s['title']}'),
                  subtitle: Text('Add what you said to it (${s['state']})'),
                ),
            ]),
          ),
        ],
      ];

  List<Widget> _activityFields(BuildContext context, CaptureProposal? p) => [
        const SizedBox(height: 8),
        if (_rrule == null)
          SegmentedButton<String>(
            key: const Key('capture-status'),
            segments: const [
              ButtonSegment(value: 'planned', label: Text('Planned')),
              ButtonSegment(value: 'in_progress', label: Text('Under way')),
              ButtonSegment(value: 'completed', label: Text('Done')),
            ],
            selected: {_status},
            onSelectionChanged: (s) => setState(() => _status = s.first),
          ),
        _dateRow(
            context,
            _rrule != null
                ? 'First on'
                : switch (_status) { 'completed' => 'Done on', 'in_progress' => 'Started', _ => 'Planned for' },
            _when,
            (d) => setState(() => _when = d),
            timeKnown: !_allDay,
            onAllDay: (v) => setState(() => _allDay = v)),
        if (_rrule != null)
          ListTile(
            key: const Key('capture-recurrence'),
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.repeat),
            title: Text(_rruleText ?? _rrule!),
            trailing: TextButton(onPressed: () => setState(() => _rrule = null), child: const Text('Only once')),
          ),
        if ((p?.similar ?? const []).isNotEmpty)
          DropdownButtonFormField<String?>(
            key: const Key('capture-link-ticket'),
            isExpanded: true,
            initialValue: _linkTicket,
            decoration: const InputDecoration(labelText: 'About the ticket (it is not changed)'),
            items: [
              const DropdownMenuItem(value: null, child: Text('—')),
              for (final s in p!.similar)
                DropdownMenuItem(value: '${s['uid']}', child: Text('${s['title']}', overflow: TextOverflow.ellipsis)),
            ],
            onChanged: (v) => setState(() => _linkTicket = v),
          ),
        SwitchListTile(
          key: const Key('capture-private'),
          contentPadding: EdgeInsets.zero,
          value: _visibility == 'private',
          onChanged: (v) => setState(() => _visibility = v ? 'private' : 'workspace'),
          title: const Text('Only for me'),
          subtitle: const Text('Otherwise the workspace sees it'),
        ),
      ];

  Widget _dateRow(BuildContext context, String label, DateTime? value, void Function(DateTime?) set,
      {bool timeKnown = true, void Function(bool)? onAllDay}) {
    String show(DateTime d) {
      final l = MaterialLocalizations.of(context);
      final day = l.formatFullDate(d);
      return timeKnown ? '$day, ${l.formatTimeOfDay(TimeOfDay.fromDateTime(d))}' : '$day (no time)';
    }

    return ListTile(
      key: Key('capture-when-$label'),
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.event_outlined),
      title: Text(value == null ? '$label: not said' : '$label: ${show(value)}'),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        if (onAllDay != null && value != null)
          TextButton(onPressed: () => onAllDay(!_allDay), child: Text(_allDay ? 'Add a time' : 'No time')),
        IconButton(
          icon: const Icon(Icons.edit_calendar_outlined),
          onPressed: () async {
            final now = DateTime.now();
            final d = await showDatePicker(
                context: context,
                initialDate: value ?? now,
                firstDate: DateTime(now.year - 5),
                lastDate: DateTime(now.year + 5));
            if (d == null || !context.mounted) return;
            var t = value == null ? null : TimeOfDay.fromDateTime(value);
            if (timeKnown) t = await showTimePicker(context: context, initialTime: t ?? TimeOfDay.now()) ?? t;
            set(DateTime(d.year, d.month, d.day, t?.hour ?? 0, t?.minute ?? 0));
          },
        ),
      ]),
    );
  }

  List<Widget> _createdView(BuildContext context) {
    final c = _created!;
    final path = c.kind == 'ticket' ? '/ticket/${c.uid}' : '/activity/${Uri.encodeComponent(c.uid)}';
    return [
      NoticeBar(
        key: const Key('capture-created'),
        icon: Icons.check_circle_outline,
        text: c.queued
            ? 'Saved on the phone: it is sent as soon as ARGUS can be reached (Unsent changes).'
            : (c.kind == 'ticket' && _addTo != null ? 'Added to the ticket.' : 'Created.'),
      ),
      const SizedBox(height: 12),
      Wrap(spacing: 8, runSpacing: 8, children: [
        FilledButton.tonal(key: const Key('capture-open'), onPressed: () => context.push(path), child: const Text('Open')),
        OutlinedButton(
          key: const Key('capture-correct'),
          onPressed: () => context.push(c.kind == 'ticket' ? '/ticket/${c.uid}/edit' : path),
          child: const Text('Correct it'),
        ),
        TextButton(
          key: const Key('capture-again'),
          onPressed: () => setState(() {
            _created = null;
            _proposal = null;
            _manual = false;
            _kind = null;
            _text.clear();
          }),
          child: const Text('Capture another'),
        ),
      ]),
    ];
  }
}
