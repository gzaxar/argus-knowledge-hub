import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../domain/capture.dart';
import 'package:uuid/uuid.dart';

import '../../widgets/follow_button.dart';
import '../../widgets/location_section.dart';
import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../data/command_queue.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/auth_image.dart';
import '../../widgets/attach_menu.dart';
import '../../widgets/attachment_open.dart';
import '../../widgets/common.dart';
import '../../widgets/related_by_meaning.dart';
import '../../widgets/rich_content.dart';
import 'relation_graph_screen.dart';

/// Equipment or a Position, next to the machine: what it is, what is installed there now (or
/// where this unit is installed), what it connects to, the open tickets and documents that
/// concern it, its files, and its recent activity (flutter-app-design §5.3).
class AssetScreen extends ConsumerWidget {
  const AssetScreen({super.key, required this.uid});

  final String uid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(assetDetailProvider(uid));
    return Scaffold(
      appBar: AppBar(title: Text(r.value?.name ?? 'Record'), actions: [
        if (r.value != null) FollowButton(subject: 'asset', uid: uid),
        if (r.value != null && r.value!.recordStatus != 'Merged')
          IconButton(
            key: const Key('asset-edit'),
            tooltip: 'Edit',
            icon: const Icon(Icons.edit_outlined),
            onPressed: () => context.push('/asset/$uid/edit'),
          ),
      ]),
      floatingActionButton: r.value == null
          ? null
          : FloatingActionButton.extended(
              key: const Key('asset-report'),
              onPressed: () => context.push('/report/$uid'),
              icon: const Icon(Icons.report_problem_outlined),
              label: const Text('Report a problem'),
            ),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(assetDetailProvider(uid))),
        data: (a) => RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(assetCommentsProvider(uid));
            ref.invalidate(assetHistoryProvider(uid));
            ref.invalidate(assetAttachmentsProvider(uid));
            final _ = await ref.refresh(assetDetailProvider(uid).future);
          },
          child: _AssetBody(a),
        ),
      ),
    );
  }
}

class _AssetBody extends ConsumerStatefulWidget {
  const _AssetBody(this.a);

  final AssetDetail a;

  @override
  ConsumerState<_AssetBody> createState() => _AssetBodyState();
}

class _AssetBodyState extends ConsumerState<_AssetBody> {
  final _comment = TextEditingController();
  String _commentKey = const Uuid().v4();
  bool _sending = false;

  AssetDetail get a => widget.a;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  Future<void> _sendComment() async {
    final text = _comment.text.trim();
    if (text.isEmpty) return;
    final session = ref.read(sessionProvider).value;
    setState(() => _sending = true);
    try {
      await ref.read(assetRepositoryProvider).comment(a.uid, _commentKey, session?.userLabel ?? 'field app', text);
      _comment.clear();
      _commentKey = const Uuid().v4();
      ref.invalidate(assetCommentsProvider(a.uid));
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final current = a.current;
    final attrs = a.attributes.entries.where((e) => e.value != null && e.value.toString().isNotEmpty).toList();
    final defsByKey = {for (final d in ref.watch(schemaAttributesProvider(a.schemaUid)).value ?? const []) d.key: d};
    final openTickets = a.tickets.where((t) => t.open).toList();
    final comments = ref.watch(assetCommentsProvider(a.uid)).value ?? const [];
    final history = ref.watch(assetHistoryProvider(a.uid)).value ?? const [];
    final attachments = ref.watch(assetAttachmentsProvider(a.uid)).value ?? const [];
    final activity = [
      ...comments.map((c) => _Activity(at: c.at, icon: Icons.chat_bubble_outline, author: c.author, text: c.body)),
      ...history.map((h) => _Activity(at: h.at, icon: Icons.history, author: h.author, text: h.details, kind: h.type)),
    ]..sort((x, y) => (y.at ?? DateTime(0)).compareTo(x.at ?? DateTime(0)));

    return ListView(key: const Key('asset-body-list'), padding: const EdgeInsets.only(bottom: 32), children: [
      if (a.recordStatus == 'Merged')
        const NoticeBar(icon: Icons.merge_type, text: 'This record was merged into another. Use the surviving record.', severe: true),
      if (a.restricted != null)
        NoticeBar(icon: Icons.lock_outline, text: 'Restricted: ${a.restricted}. Do not share its details.'),
      if (a.processing)
        const NoticeBar(icon: Icons.sync, text: 'ARGUS is still processing recent changes. Relations may be incomplete.'),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (a.avatarIconUid != null) ...[
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: AuthImage(a.avatarIconUid!, width: 56, height: 56, fit: BoxFit.cover),
            ),
            const SizedBox(width: 12),
          ],
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(a.name, key: const Key('asset-name'), style: theme.textTheme.headlineSmall),
              const SizedBox(height: 6),
              Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                StatusChip(a.isPosition ? 'Position' : 'Equipment', tone: theme.colorScheme.primary),
                StatusChip(a.type),
                if (a.recordStatus != 'Active') StatusChip(a.recordStatus, tone: theme.colorScheme.error),
                if (ref.watch(showKeysProvider)) SelectableText(a.key, style: theme.textTheme.bodySmall),
              ]),
              if (a.typePath.length > 1) ...[
                const SizedBox(height: 6),
                Text(a.typePath.join(' › '), style: theme.textTheme.bodySmall),
              ],
            ]),
          ),
        ]),
      ),
      _Labels(asset: a),
      SectionHeader(a.isPosition ? 'Installed here now' : 'Installed at now'),
      if (current.isEmpty)
        ListTile(
          leading: const Icon(Icons.remove_circle_outline),
          title: Text(a.isPosition ? 'Nothing is recorded as installed here.' : 'Not recorded as installed anywhere.'),
        )
      else
        for (final i in current) _installation(context, i),
      if (a.isPosition)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key('asset-replace'),
              onPressed: () => context.push('/replace/${a.uid}'),
              icon: const Icon(Icons.swap_horiz),
              label: Text(current.isEmpty ? 'Install a unit' : 'Replace the unit'),
            ),
          ),
        ),
      if (a.installations.length > current.length)
        ExpansionTile(
          title: Text('History (${a.installations.length - current.length})'),
          children: [for (final i in a.installations.where((i) => !current.contains(i))) _installation(context, i)],
        ),
      SectionHeader('Connections', trailing: '${a.relations.length}'),
      if (a.relations.isEmpty)
        const ListTile(title: Text('Nothing else is connected to this record.'))
      else ...[
        if (a.outbound.isNotEmpty) _RelationGroup(title: 'Outbound', items: a.outbound, icon: Icons.call_made),
        if (a.inbound.isNotEmpty) _RelationGroup(title: 'Inbound', items: a.inbound, icon: Icons.call_received),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key('asset-graph'),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => RelationGraphScreen(rootUid: a.uid, rootName: a.name))),
              icon: const Icon(Icons.hub_outlined),
              label: const Text('View as a graph'),
            ),
          ),
        ),
      ],
      SectionHeader('Open tickets', trailing: '${openTickets.length} of ${a.tickets.length}'),
      if (openTickets.isEmpty) const ListTile(title: Text('No open tickets.')),
      for (final t in openTickets)
        ListTile(
          leading: const Icon(Icons.confirmation_number_outlined),
          title: Text(t.title, maxLines: 2, overflow: TextOverflow.ellipsis),
          subtitle: Text([t.state, if (t.priority != null) t.priority].join(' · ')),
          onTap: () => context.push('/ticket/${t.uid}'),
        ),
      SectionHeader('Documents', trailing: '${a.documents.length}'),
      if (a.documents.isEmpty) const ListTile(title: Text('No documents apply.')),
      for (final d in a.documents)
        ListTile(
          leading: Icon(d.reviewOverdue ? Icons.warning_amber : Icons.description_outlined,
              color: d.reviewOverdue ? theme.colorScheme.error : null),
          title: Text(keyed(ref.watch(showKeysProvider), d.code, [d.title]), maxLines: 2, overflow: TextOverflow.ellipsis),
          subtitle: Text([d.state ?? 'no revision', if (d.reviewOverdue) 'review overdue'].join(' · ')),
          onTap: () => context.push('/document/${d.uid}'),
        ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            key: const Key('asset-write-document'),
            onPressed: () => context.push('/documents/new?asset=${a.uid}'),
            icon: const Icon(Icons.note_add_outlined),
            label: const Text('Write a document about it'),
          ),
        ),
      ),
      LocationSection(uid: a.uid),
      RelatedByMeaning(kind: RecordKind.asset, uid: a.uid),
      SectionHeader('Files', trailing: '${attachments.length}'),
      if (attachments.isEmpty) const ListTile(title: Text('No files yet.')),
      if (attachments.isNotEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            for (final f in attachments) _attachmentTile(context, f),
          ]),
        ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            key: const Key('asset-attach'),
            onPressed: () async {
              final sent = await attachTo(context, ref, AttachTarget.asset(a.uid));
              if (sent == null || !context.mounted) return;
              if (sent.status == CommandStatus.accepted) {
                ref.invalidate(assetAttachmentsProvider(a.uid));
                refreshAsset(ref, a.uid);
              }
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text(sent.status == CommandStatus.accepted
                      ? '${sent.label.split(' for ').first} added.'
                      : describe(sent))));
            },
            icon: const Icon(Icons.attach_file),
            label: const Text('Attach photo, video, note or place'),
          ),
        ),
      ),
      if (attrs.isNotEmpty) ...[
        const SectionHeader('Attributes'),
        for (final e in attrs)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(defsByKey[e.key]?.name ?? e.key, style: theme.textTheme.labelMedium?.copyWith(color: theme.colorScheme.outline)),
              const SizedBox(height: 2),
              defsByKey[e.key]?.type == 'reference' && e.value is String
                  ? _ReferenceValue(e.value as String)
                  : e.value is Map || e.value is List
                      ? SelectableText(e.value.toString())
                      : RichContent('${e.value}'),
            ]),
          ),
      ],
      const SectionHeader('Activity'),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(children: [
          Expanded(
            child: TextField(
              key: const Key('asset-comment-field'),
              controller: _comment,
              decoration: const InputDecoration(hintText: 'Add a comment…', isDense: true),
              onSubmitted: (_) => _sendComment(),
            ),
          ),
          IconButton(
            key: const Key('asset-comment-send'),
            icon: _sending
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.send),
            onPressed: _sending ? null : _sendComment,
          ),
        ]),
      ),
      if (activity.isEmpty) const ListTile(title: Text('Nothing recorded yet.')),
      for (final e in activity)
        ListTile(
          leading: Icon(e.icon),
          title: Text(e.text, maxLines: 4, overflow: TextOverflow.ellipsis),
          subtitle: Text([e.author, if (e.kind != null) e.kind!, if (e.at != null) formatWhenDate(e.at)].join(' · ')),
        ),
    ]);
  }

  Widget _attachmentTile(BuildContext context, AttachmentInfo f) {
    final isImage = (f.mimeType ?? '').startsWith('image/');
    return InkWell(
      key: Key('attachment-${f.uid}'),
      onTap: () => openAttachment(context, ref, f),
      child: Container(
        width: 84,
        height: 84,
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(8), border: Border.all(color: Theme.of(context).dividerColor)),
        clipBehavior: Clip.antiAlias,
        child: isImage
            ? AuthImage(f.uid, width: 84, height: 84)
            : Center(
                child: Padding(
                  padding: const EdgeInsets.all(6),
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Icon(iconOf(f.mimeType)),
                    Text(f.filename, maxLines: 2, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
                  ]),
                ),
              ),
      ),
    );
  }

  Widget _installation(BuildContext context, InstallationInfo i) {
    final other = a.isPosition ? i.asset : i.position;
    final when = [
      if (i.from?.nominal != null) 'since ${formatWhenDate(i.from!.nominal)}',
      if (i.until?.nominal != null) 'until ${formatWhenDate(i.until!.nominal)}',
    ].join(' ');
    return ListTile(
      leading: Icon(a.isPosition ? Icons.memory : Icons.place_outlined),
      title: Text(other?.label ?? 'Unknown'),
      subtitle: Text([
        i.temporalState,
        if (i.status != 'Confirmed') i.status,
        if (i.certainty == 'possible') 'uncertain dates',
        if (when.isNotEmpty) when,
      ].join(' · ')),
      onTap: other?.uid == null ? null : () => context.push('/asset/${other!.uid}'),
    );
  }
}

/// A reference attribute's stored uid, shown by the name of what it points at and tappable to open it —
/// not the bare uid a reference is stored as (flutter-app-design §5.4, mirroring the web's attribute
/// view, which resolves a reference the same way).
class _ReferenceValue extends ConsumerWidget {
  const _ReferenceValue(this.uid);

  final String uid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final brief = ref.watch(assetBriefProvider(uid));
    return brief.when(
      loading: () => Text(uid, style: Theme.of(context).textTheme.bodySmall),
      error: (_, _) => SelectableText(uid),
      data: (b) => b == null
          ? SelectableText(uid)
          : InkWell(
              onTap: () => context.push('/asset/${b.uid}'),
              child: Text(b.label, style: TextStyle(color: Theme.of(context).colorScheme.primary, decoration: TextDecoration.underline)),
            ),
    );
  }
}

class _Activity {
  const _Activity({required this.at, required this.icon, required this.author, required this.text, this.kind});
  final DateTime? at;
  final IconData icon;
  final String author;
  final String text;
  final String? kind;
}

class _RelationGroup extends StatelessWidget {
  const _RelationGroup({required this.title, required this.items, required this.icon});

  final String title;
  final List<RelationItem> items;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final byRelation = <String, List<RelationItem>>{};
    for (final r in items) {
      byRelation.putIfAbsent(r.relation, () => []).add(r);
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.labelLarge),
        for (final entry in byRelation.entries) ...[
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 2),
            child: Text(entry.key.replaceAll('_', ' '), style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Theme.of(context).colorScheme.outline)),
          ),
          for (final r in entry.value)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(icon, size: 18),
              title: Text(r.name),
              subtitle: Text(r.type),
              onTap: () => context.push('/asset/${r.uid}'),
            ),
        ],
      ]),
    );
  }
}


/// What a scan finds this record by — its QR code, serial, barcode… — and putting another on it: typed, or
/// read from the label in front of you.
class _Labels extends ConsumerWidget {
  const _Labels({required this.asset});

  final AssetDetail asset;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final labels = ref.watch(assetLabelsProvider(asset.uid)).value ?? const <AssetLabelInfo>[];
    final kinds = AssetLabelInfo.kinds.keys.toList();
    final sorted = [...labels]..sort((x, y) {
        int rank(String t) => kinds.contains(t) ? kinds.indexOf(t) : kinds.length;
        return rank(x.type).compareTo(rank(y.type));
      });
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SectionHeader('Labels', trailing: '${labels.length}'),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Wrap(spacing: 8, runSpacing: 4, children: [
          for (final l in sorted)
            InputChip(
              key: Key('label-${l.uid}'),
              avatar: Icon(l.type == 'qrcode' ? Icons.qr_code_2 : Icons.label_outline, size: 18),
              label: Text('${l.kindLabel}: ${l.value}'),
              onDeleted: () => _remove(context, ref, l),
            ),
          ActionChip(
            key: const Key('label-add'),
            avatar: const Icon(Icons.add, size: 18),
            label: const Text('Add label'),
            onPressed: () => _add(context, ref),
          ),
        ]),
      ),
    ]);
  }

  Future<void> _remove(BuildContext context, WidgetRef ref, AssetLabelInfo l) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Remove this label?'),
        content: Text('${l.kindLabel} ${l.value} will no longer find ${asset.name}.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialog, false), child: const Text('Keep')),
          FilledButton(key: const Key('label-remove-confirm'), onPressed: () => Navigator.pop(dialog, true),
              child: const Text('Remove')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(assetRepositoryProvider).removeLabel(asset.uid, l.uid);
    } on Problem catch (p) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    }
    refreshAsset(ref, asset.uid);
  }

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _AddLabelSheet(assetUid: asset.uid),
    );
    if (added == true) refreshAsset(ref, asset.uid);
  }
}

class _AddLabelSheet extends ConsumerStatefulWidget {
  const _AddLabelSheet({required this.assetUid});

  final String assetUid;

  @override
  ConsumerState<_AddLabelSheet> createState() => _AddLabelSheetState();
}

class _AddLabelSheetState extends ConsumerState<_AddLabelSheet> {
  final _value = TextEditingController();
  String _type = 'qrcode';
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _value.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final path = await context.push<String>('/scan?pick=1');
    if (path == null || !mounted) return;
    // What the scanner read: a label's value as printed, or a link to a record in ARGUS, kept whole.
    final value = path.startsWith('/lookup/') ? Uri.decodeComponent(path.substring('/lookup/'.length)) : path;
    setState(() => _value.text = value);
  }

  Future<void> _save() async {
    final value = _value.text.trim();
    if (value.isEmpty) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(assetRepositoryProvider).addLabel(widget.assetUid, const Uuid().v4(), _type, value);
      if (mounted) Navigator.pop(context, true);
    } on Problem catch (p) {
      if (mounted) setState(() => _error = p.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Add a label', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: const Key('label-type'),
            initialValue: _type,
            decoration: const InputDecoration(labelText: 'Kind', border: OutlineInputBorder()),
            items: [
              for (final e in AssetLabelInfo.kinds.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
            ],
            onChanged: (v) => setState(() => _type = v ?? _type),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('label-value'),
            controller: _value,
            decoration: InputDecoration(
              labelText: 'Value',
              border: const OutlineInputBorder(),
              errorText: _error,
              suffixIcon: IconButton(
                key: const Key('label-scan'),
                tooltip: 'Read it from the label',
                icon: const Icon(Icons.qr_code_scanner),
                onPressed: _scan,
              ),
            ),
            onSubmitted: (_) => _save(),
          ),
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('label-save'),
            onPressed: _saving ? null : _save,
            child: Text(_saving ? 'Saving…' : 'Add label'),
          ),
        ]),
      );
}
