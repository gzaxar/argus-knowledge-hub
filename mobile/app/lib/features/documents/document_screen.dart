import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../widgets/follow_button.dart';
import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../app/queue.dart';
import '../../data/command_queue.dart';
import '../../domain/capture.dart';
import '../../domain/models.dart' show RecordKind;
import '../../widgets/attach_menu.dart';
import '../../widgets/attachment_open.dart';
import '../../widgets/common.dart';
import '../../widgets/related_by_meaning.dart';
import '../../widgets/rich_content.dart';
import '../../widgets/type_tree.dart';
import '../../widgets/export_menu.dart';

/// A procedure or document. The field must never mistake a draft or an outdated revision for the
/// one to work from, so the state is said before the content (flutter-app-design §5.5).
class DocumentScreen extends ConsumerWidget {
  const DocumentScreen({super.key, required this.uid});

  final String uid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(documentDetailProvider(uid));
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
          title: Text((ref.watch(showKeysProvider) ? r.value?.code : r.value?.title) ?? r.value?.code ?? 'Document',
              maxLines: 1, overflow: TextOverflow.ellipsis),
          actions: [
            if (r.value != null) FollowButton(subject: 'document', uid: uid),
            if (r.value != null) ExportMenu(kind: ExportKind.document, uid: uid, name: r.value!.code),
          ]),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(documentDetailProvider(uid))),
        data: (d) => ListView(padding: const EdgeInsets.only(bottom: 32), children: [
          if (d.supersededBy != null)
            NoticeBar(
              key: const Key('doc-superseded'),
              icon: Icons.block,
              severe: true,
              text: 'Superseded. Do not work from this document.',
            )
          else if (d.revisionState == null)
            const NoticeBar(icon: Icons.block, severe: true, text: 'No current revision. There is nothing to work from.')
          else if (!d.approved)
            NoticeBar(
                key: const Key('doc-not-approved'),
                icon: Icons.edit_note,
                severe: true,
                text: 'Revision ${d.revisionNumber} is ${d.revisionState}, not approved. Do not work from it.')
          else if (d.outdated)
            NoticeBar(
                key: const Key('doc-overdue'),
                icon: Icons.warning_amber,
                text: 'Periodic review was due on ${formatWhenDate(d.nextReviewDue)}. Check with the owner before relying on it.'),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(d.title, key: const Key('doc-title'), style: theme.textTheme.headlineSmall),
              const SizedBox(height: 4),
              TypeBreadcrumb(tree: ref.watch(typeTreeProvider('documents')).value, schemaUid: d.documentTypeUid),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                StatusChip(d.authorityLevel),
                if (d.revisionNumber != null) StatusChip('rev. ${d.revisionNumber}'),
                if (d.revisionState != null)
                  StatusChip(d.revisionState!, tone: d.approved ? theme.colorScheme.primary : theme.colorScheme.error),
              ]),
              if (d.supersededBy != null) ...[
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: () => context.push('/document/${d.supersededBy}'),
                  icon: const Icon(Icons.arrow_forward),
                  label: const Text('Open the document that replaces it'),
                ),
              ],
            ]),
          ),
          _Workflow(uid: uid),
          _Files(uid: uid),
          RelatedByMeaning(kind: RecordKind.document, uid: uid),
          if (d.steps.isNotEmpty) ...[
            const SectionHeader('Steps'),
            for (final (i, s) in d.steps.indexed)
              ListTile(leading: CircleAvatar(radius: 14, child: Text('${i + 1}')), title: Text(s)),
          ],
          if ((d.body ?? '').isNotEmpty) ...[
            const SectionHeader('Content'),
            Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: RichContent(d.body!)),
          ],
        ]),
      ),
    );
  }
}

/// Where work on the document stands: the revision being written or decided on, and the one step that
/// moves it on — the same draft → review → approval → publication the web follows, with the server deciding
/// who may take each step (an author cannot approve their own revision).
class _Workflow extends ConsumerStatefulWidget {
  const _Workflow({required this.uid});

  final String uid;

  @override
  ConsumerState<_Workflow> createState() => _WorkflowState();
}

class _WorkflowState extends ConsumerState<_Workflow> {
  bool _busy = false;

  Future<void> _run(String done, Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
      ref.invalidate(documentRevisionsProvider(widget.uid));
      ref.invalidate(documentDetailProvider(widget.uid));
      ref.invalidate(documentListProvider);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final revs = ref.watch(documentRevisionsProvider(widget.uid)).value;
    if (revs == null) return const SizedBox.shrink();
    final repo = ref.read(documentRepositoryProvider);
    final open = revs.where((r) => r.open).firstOrNull;
    final published = revs.where((r) => r.state == 'published').firstOrNull;
    if (open == null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Wrap(spacing: 8, runSpacing: 4, children: [
            OutlinedButton.icon(
              key: const Key('doc-new-revision'),
              onPressed: _busy ? null : () => _run('A new draft revision was started.', () => repo.newRevision(widget.uid, published)),
              icon: const Icon(Icons.edit_note),
              label: const Text('Start a new revision'),
            ),
            OutlinedButton.icon(
              key: const Key('doc-reshape-revision'),
              onPressed: _busy
                  ? null
                  : () {
                      final type = ref.read(documentDetailProvider(widget.uid)).value?.documentTypeUid;
                      context.push(Uri(path: '/documents/reshape', queryParameters: {
                        'document': widget.uid,
                        'type': ?type,
                      }).toString());
                    },
              icon: const Icon(Icons.auto_fix_high),
              label: const Text('From raw text'),
            ),
          ]),
        ),
      );
    }
    final (label, next) = switch (open.state) {
      'draft' => ('Draft', 'Edit it, then send it for review.'),
      'in_review' => ('In review', 'Waiting for someone other than its author to approve it.'),
      _ => ('Approved', 'Publish it to make it the revision to work from.'),
    };
    return Card(
      key: const Key('doc-workflow'),
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Revision ${open.number} · $label', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text([if (open.authoredBy != null) 'by ${open.authoredBy}', next].join(' — ')),
          if ((open.reviewComment ?? '').isNotEmpty) ...[
            const SizedBox(height: 8),
            NoticeBar(icon: Icons.feedback_outlined, text: 'Review: ${open.reviewComment}'),
          ],
          if ((open.body ?? '').isNotEmpty)
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: const Text('Its text'),
              children: [RichContent(open.body!)],
            ),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (open.state == 'draft') ...[
              OutlinedButton.icon(
                key: const Key('doc-edit-draft'),
                onPressed: _busy ? null : () => context.push('/document/${widget.uid}/revision/${open.uid}/edit'),
                icon: const Icon(Icons.edit),
                label: const Text('Edit draft'),
              ),
              FilledButton(
                key: const Key('doc-submit'),
                onPressed: _busy ? null : () => _run('Sent for review.', () => repo.submit(widget.uid, open.uid)),
                child: const Text('Send for review'),
              ),
            ],
            if (open.state == 'in_review')
              FilledButton(
                key: const Key('doc-approve'),
                onPressed: _busy ? null : () => _run('Approved.', () => repo.approve(widget.uid, open.uid)),
                child: const Text('Approve'),
              ),
            if (open.state == 'approved')
              FilledButton(
                key: const Key('doc-publish'),
                onPressed: _busy ? null : () => _run('Published.', () => repo.publish(widget.uid, open.uid)),
                child: const Text('Publish'),
              ),
          ]),
        ]),
      ),
    );
  }
}


/// The files of the revision to work from, and of the draft being written — to which the field adds what
/// it saw: a photo, a video, a recorded note, a place. A published revision's files are what it was
/// approved with, and stay as they are.
class _Files extends ConsumerWidget {
  const _Files({required this.uid});

  final String uid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final revs = ref.watch(documentRevisionsProvider(uid)).value;
    if (revs == null) return const SizedBox.shrink();
    final published = revs.where((r) => r.state == 'published').firstOrNull;
    final draft = revs.where((r) => r.state == 'draft').firstOrNull;
    final current = published == null
        ? const <AttachmentInfo>[]
        : ref.watch(revisionAttachmentsProvider((uid, published.uid))).value ?? const <AttachmentInfo>[];
    final drafted = draft == null
        ? const <AttachmentInfo>[]
        : ref.watch(revisionAttachmentsProvider((uid, draft.uid))).value ?? const <AttachmentInfo>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SectionHeader('Files', trailing: '${current.length + drafted.length}'),
      for (final f in current) AttachmentTile(f),
      if (draft != null) ...[
        if (drafted.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text('In the draft (revision ${draft.number})', style: Theme.of(context).textTheme.labelMedium),
          ),
        for (final f in drafted) AttachmentTile(f),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              key: const Key('doc-attach'),
              onPressed: () async {
                final sent = await attachTo(context, ref, AttachTarget.document(uid, draft.uid));
                if (sent == null || !context.mounted) return;
                if (sent.status == CommandStatus.accepted) ref.invalidate(revisionAttachmentsProvider((uid, draft.uid)));
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(sent.status == CommandStatus.accepted
                        ? '${sent.label.split(' for ').first} added to the draft.'
                        : describe(sent))));
              },
              icon: const Icon(Icons.attach_file),
              label: const Text('Attach to the draft'),
            ),
          ),
        ),
      ] else if (current.isEmpty)
        const ListTile(title: Text('No files. Start a new revision to add some.')),
    ]);
  }
}
