import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../data/command_queue.dart';
import '../../core/problem.dart';
import '../../domain/capture.dart';
import '../../domain/models.dart';
import '../../widgets/attach_menu.dart';
import '../../widgets/attachment_open.dart';
import '../../widgets/common.dart';
import '../../widgets/related_by_meaning.dart';
import '../../widgets/type_tree.dart';
import '../../widgets/rich_content.dart';
import '../../widgets/export_menu.dart';
import '../../widgets/photo_text.dart';

/// A ticket in the field (flutter-app-design §9): read it, comment, add a photo, and move it
/// through the transitions the server's workflow allows. A closure of a safety ticket from here
/// is only proposed; a person confirms it online (A70).
class TicketScreen extends ConsumerStatefulWidget {
  const TicketScreen({super.key, required this.uid});

  final String uid;

  @override
  ConsumerState<TicketScreen> createState() => _TicketScreenState();
}

class _TicketScreenState extends ConsumerState<TicketScreen> {
  final _comment = TextEditingController();
  String _commentUid = const Uuid().v4();
  bool _busy = false;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  void _say(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  void _reload() {
    ref.invalidate(ticketDetailProvider(widget.uid));
    ref.invalidate(commentsProvider(widget.uid));
    ref.invalidate(transitionsProvider(widget.uid));
    ref.invalidate(attachmentsProvider(widget.uid));
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on Problem catch (p) {
      if (p.code == ProblemCode.stale) {
        _reload();
        _say('Someone changed this ticket meanwhile. It was reloaded; check it and try again.');
      } else {
        _say(p.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Keep the command, send it now if ARGUS can be reached, and say what happened.
  Future<PendingCommand> _command(Future<PendingCommand> Function(QueueController q) make) async {
    final queue = ref.read(queueProvider.notifier);
    final sent = await queue.sendNow(await make(queue));
    if (sent.lastCode == 'stale' && sent.status == CommandStatus.rejected) {
      // Refused while the person looks at it: reload and let them decide again, rather than keep it.
      await queue.discard(sent.id);
      _reload();
      _say('Someone changed this ticket meanwhile. It was reloaded; check it and try again.');
      return sent;
    }
    if (sent.status != CommandStatus.accepted || sent.note != null) _say(describe(sent));
    return sent;
  }

  Future<void> _send() => _run(() async {
        final text = _comment.text.trim();
        if (text.isEmpty) return;
        final uid = _commentUid;
        _commentUid = const Uuid().v4(); // the next comment is another command
        _comment.clear();
        final sent = await _command((q) => q.enqueue(
            kind: 'ticket.comment',
            key: 'comment:$uid',
            target: widget.uid,
            label: 'Comment: $text',
            payload: {'ticket_uid': widget.uid, 'comment_uid': uid, 'body': text},
            dependsOn: _createOf(q)));
        if (sent.status == CommandStatus.accepted) ref.invalidate(commentsProvider(widget.uid));
      });

  /// A command about a ticket reported offline waits for the ticket itself (A64).
  List<String> _createOf(QueueController q) => [
        for (final c in q.commands)
          if (c.kind == 'ticket.create' && c.target == widget.uid && c.status != CommandStatus.accepted) c.id,
      ];

  /// A photo, a video, a recorded note or where the person is (widgets/attach_menu.dart).
  Future<void> _attach() => _run(() async {
        final q = ref.read(queueProvider.notifier);
        final sent = await attachTo(context, ref, AttachTarget.ticket(widget.uid), dependsOn: _createOf(q));
        if (sent == null) return;
        if (sent.status == CommandStatus.accepted) {
          ref.invalidate(attachmentsProvider(widget.uid));
          _say('${sent.label.split(' for ').first} added.');
        } else {
          _say(describe(sent));
        }
      });

  Future<void> _move(TicketDetail t, TransitionOption o) async {
    String? comment;
    String? resolution;
    if (o.requires.contains('comment') || o.requires.contains('resolution') || o.closes) {
      final r = await showDialog<(String, String)>(context: context, builder: (_) => _MoveDialog(o));
      if (r == null) return;
      (comment, resolution) = (r.$1.isEmpty ? null : r.$1, r.$2.isEmpty ? null : r.$2);
    }
    await _run(() async {
      final sent = await _command((q) => q.enqueue(
          kind: 'ticket.transition',
          key: 'move:${widget.uid}:${t.version}:${o.to}',
          target: widget.uid,
          seenVersion: '${t.version}',
          label: 'Move “${t.title}” to ${o.toName}',
          payload: {'ticket_uid': widget.uid, 'to': o.to, 'version': t.version, 'comment': comment,
            'resolution': resolution}));
      if (sent.status == CommandStatus.accepted) {
        _reload();
        if (sent.note == null) _say('Moved to ${o.toName}.');
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(ticketDetailProvider(widget.uid));
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Ticket'), actions: [
        if (r.hasValue)
          IconButton(
            key: const Key('ticket-edit'),
            tooltip: 'Edit',
            icon: const Icon(Icons.edit_outlined),
            onPressed: () => context.push('/ticket/${widget.uid}/edit'),
          ),
        if (r.hasValue)
          ExportMenu(
            kind: ExportKind.ticket,
            uid: widget.uid,
            name: (r.value!.attributes['argus_source_key'] as String?) ?? r.value!.title,
          ),
      ]),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) {
          final pending = ref.watch(pendingForProvider(widget.uid)).where((c) => c.kind == 'ticket.create').firstOrNull;
          return pending != null
              ? _PendingTicket(pending)
              : ProblemView(e, onRetry: () => ref.invalidate(ticketDetailProvider(widget.uid)));
        },
        data: (t) => RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(padding: const EdgeInsets.only(bottom: 32), children: [
            if (t.proposedTransition != null)
              NoticeBar(
                key: const Key('ticket-proposed'),
                icon: Icons.hourglass_top,
                text: 'Closing was proposed from the field (to ${t.proposedTransition!['to']}). '
                    'It takes effect when a person confirms it on the web.',
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t.title, key: const Key('ticket-title'), style: theme.textTheme.headlineSmall),
                const SizedBox(height: 4),
                TypeBreadcrumb(tree: ref.watch(typeTreeProvider('tickets')).value, schemaUid: t.schemaUid),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 6, children: [
                  StatusChip(t.state, tone: theme.colorScheme.primary),
                  if (t.priority != null) StatusChip(t.priority!),
                  if (t.impact != null)
                    StatusChip(ref.watch(schemaAttributesProvider(t.schemaUid ?? '')).value
                            ?.where((d) => d.key == 'argus_impact').firstOrNull?.choiceValue(t.impact) ??
                        t.impact!),
                  if (t.occurredFrom?.nominal != null)
                    StatusChip('occurred ${formatWhenDate(t.occurredFrom!.nominal)}'),
                ]),
                if (t.assetUid != null) ...[
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: () => context.push('/asset/${t.assetUid}'),
                    icon: const Icon(Icons.memory),
                    label: const Text('Open the affected record'),
                  ),
                ],
                const SizedBox(height: 16),
                (t.description ?? '').isEmpty ? const Text('No description.') : RichContent(t.description!),
              ]),
            ),
            _Unsent(uid: widget.uid),
            _Transitions(uid: widget.uid, onMove: (o) => _move(t, o), busy: _busy),
            _Attachments(uid: widget.uid, onAdd: _busy ? null : _attach),
            _Comments(uid: widget.uid),
            RelatedByMeaning(kind: RecordKind.ticket, uid: widget.uid),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    key: const Key('ticket-comment'),
                    controller: _comment,
                    minLines: 1,
                    maxLines: 4,
                    decoration: InputDecoration(
                        hintText: 'Add a comment',
                        border: const OutlineInputBorder(),
                        suffixIcon: PhotoTextButton(key: const Key('photo-text-comment'), controller: _comment)),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                    key: const Key('ticket-comment-send'),
                    onPressed: _busy ? null : _send,
                    icon: const Icon(Icons.send)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _Transitions extends ConsumerWidget {
  const _Transitions({required this.uid, required this.onMove, required this.busy});

  final String uid;
  final void Function(TransitionOption) onMove;
  final bool busy;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final moves = ref.watch(transitionsProvider(uid)).value ?? const [];
    if (moves.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SectionHeader('Move to'),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          for (final o in moves)
            OutlinedButton(
              key: Key('move-${o.to}'),
              onPressed: busy ? null : () => onMove(o),
              child: Text(o.name == 'Move' ? o.toName : '${o.name} → ${o.toName}'),
            ),
        ]),
      ),
    ]);
  }
}

class _Attachments extends ConsumerWidget {
  const _Attachments({required this.uid, required this.onAdd});

  final String uid;
  final VoidCallback? onAdd;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final files = ref.watch(attachmentsProvider(uid)).value ?? const <AttachmentInfo>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionHeader('Photos and files', trailing: '${files.length}'),
      for (final f in files) AttachmentTile(f),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: TextButton.icon(
            key: const Key('ticket-add-photo'),
            onPressed: onAdd,
            icon: const Icon(Icons.attach_file),
            label: const Text('Attach photo, video, note or place')),
      ),
    ]);
  }
}

class _Comments extends ConsumerWidget {
  const _Comments({required this.uid});

  final String uid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final comments = ref.watch(commentsProvider(uid)).value ?? const <Comment>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionHeader('Comments', trailing: '${comments.length}'),
      for (final c in comments)
        ListTile(
          dense: true,
          title: Text(c.body),
          subtitle: Text([c.author, if (c.at != null) formatWhenDate(c.at)].join(' · ')),
        ),
    ]);
  }
}

class _MoveDialog extends StatefulWidget {
  const _MoveDialog(this.option);

  final TransitionOption option;

  @override
  State<_MoveDialog> createState() => _MoveDialogState();
}

class _MoveDialogState extends State<_MoveDialog> {
  final _comment = TextEditingController();
  final _resolution = TextEditingController();

  @override
  void dispose() {
    _comment.dispose();
    _resolution.dispose();
    super.dispose();
  }

  bool get _complete =>
      (!widget.option.requires.contains('comment') || _comment.text.trim().isNotEmpty) &&
      (!widget.option.requires.contains('resolution') || _resolution.text.trim().isNotEmpty);

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text('Move to ${widget.option.toName}'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
            key: const Key('move-comment'),
            controller: _comment,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
                labelText: widget.option.requires.contains('comment') ? 'Comment (required)' : 'Comment'),
          ),
          if (widget.option.requires.contains('resolution') || widget.option.closes)
            TextField(
              key: const Key('move-resolution'),
              controller: _resolution,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                  labelText: widget.option.requires.contains('resolution') ? 'Resolution (required)' : 'Resolution'),
            ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
            key: const Key('move-confirm'),
            onPressed: _complete ? () => Navigator.pop(context, (_comment.text.trim(), _resolution.text.trim())) : null,
            child: const Text('Move'),
          ),
        ],
      );
}


/// A ticket reported on this device and not yet accepted: shown only to its author (I-MOB-3).
class _PendingTicket extends StatelessWidget {
  const _PendingTicket(this.command);

  final PendingCommand command;

  @override
  Widget build(BuildContext context) {
    final p = command.payload;
    return ListView(padding: const EdgeInsets.all(16), children: [
      NoticeBar(
        key: const Key('ticket-pending'),
        icon: Icons.cloud_upload_outlined,
        severe: command.needsPerson,
        text: command.needsPerson
            ? 'Not yet in ARGUS: ${describe(command)}'
            : 'Not yet in ARGUS. It is on this device only, and is sent when ARGUS can be reached.',
      ),
      const SizedBox(height: 16),
      Text('${p['title']}', style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 12),
      Text('${p['description'] ?? ''}'),
    ]);
  }
}

/// Changes to this ticket kept on the device and not yet accepted.
class _Unsent extends ConsumerWidget {
  const _Unsent({required this.uid});

  final String uid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pending = ref.watch(pendingForProvider(uid)).where((c) => c.kind != 'ticket.create').toList();
    if (pending.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionHeader('Not yet sent', trailing: '${pending.length}'),
      for (final c in pending)
        ListTile(
          key: Key('unsent-${c.id}'),
          dense: true,
          leading: Icon(c.needsPerson ? Icons.error_outline : Icons.cloud_upload_outlined),
          title: Text(c.label),
          subtitle: Text(c.needsPerson ? describe(c) : 'pending'),
          onTap: () => context.push('/outbox'),
        ),
    ]);
  }
}
