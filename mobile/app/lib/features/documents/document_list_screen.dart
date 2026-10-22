import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../domain/models.dart';
import '../../data/browse_repository.dart';
import '../../widgets/common.dart';
import '../../widgets/sort_menu.dart';
import '../../widgets/type_tree.dart';
import '../shell/app_shell.dart';

/// The workspace's documents, searchable by title or code. One with nothing published yet is marked so —
/// a draft is never something to work from (flutter-app-design §5.5).
class DocumentListScreen extends ConsumerStatefulWidget {
  const DocumentListScreen({super.key});

  @override
  ConsumerState<DocumentListScreen> createState() => _DocumentListScreenState();
}

class _DocumentListScreenState extends ConsumerState<DocumentListScreen> {
  String _q = '';
  String? _type;
  ListOrder _order = ListOrder.byUpdate;

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(documentListProvider);
    final tree = ref.watch(typeTreeProvider('documents')).value;
    final counts = <String, int>{};
    for (final d in r.value ?? const <DocumentListItem>[]) {
      if (d.documentTypeUid != null && !d.retired) {
        counts[d.documentTypeUid!] = (counts[d.documentTypeUid!] ?? 0) + 1;
      }
    }
    final inType = _type == null || tree == null ? null : tree.subtree(_type!);
    return Scaffold(
      appBar: AppBar(
        leading: const ShellMenuButton(),
        title: const Text('Documents'),
        actions: [
          IconButton(
            key: const Key('documents-dictate'),
            tooltip: 'Dictate a document',
            icon: const Icon(Icons.mic_none),
            onPressed: () => context.push('/documents/reshape?dictate=1'),
          ),
          IconButton(
            key: const Key('documents-reshape'),
            tooltip: 'Rework from raw text',
            icon: const Icon(Icons.auto_fix_high),
            onPressed: () => context.push('/documents/reshape'),
          ),
          SortMenu(order: _order, onChanged: (o) => setState(() => _order = o)),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('documents-new'),
        heroTag: 'documents-new', // the tabs stay mounted together: each its own hero
        onPressed: () => context.push('/documents/new'),
        icon: const Icon(Icons.add),
        label: const Text('New document'),
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: TextField(
            key: const Key('documents-search'),
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search by title or code'),
            onChanged: (v) => setState(() => _q = v.trim().toLowerCase()),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: TypeFilterButton(
              tree: tree,
              selected: _type,
              counts: counts,
              onSelected: (t) => setState(() => _type = t),
            ),
          ),
        ),
        Expanded(
          child: r.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(documentListProvider)),
            data: (all) {
              final shown = all
                  .where((d) => !d.retired)
                  .where((d) =>
                      _q.isEmpty || d.title.toLowerCase().contains(_q) || d.code.toLowerCase().contains(_q))
                  .where((d) => inType == null || inType.contains(d.documentTypeUid))
                  .toList()
                ..sort((a, b) => _order.compare(a, b,
                    name: (d) => d.title, created: (d) => d.createdAt, updated: (d) => d.updatedAt));
              if (shown.isEmpty) return const Center(child: Text('No documents match.'));
              return RefreshIndicator(
                onRefresh: () async => ref.invalidate(documentListProvider),
                child: ListView.separated(
                  key: const Key('documents-list'),
                  padding: const EdgeInsets.only(bottom: 88),
                  itemCount: shown.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, i) => _DocumentTile(shown[i]),
                ),
              );
            },
          ),
        ),
      ]),
    );
  }
}

class _DocumentTile extends ConsumerWidget {
  const _DocumentTile(this.d);

  final DocumentListItem d;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final here = ref.watch(workspaceIdProvider);
    final shared = !d.shared ? null : (d.workspaceId == null || d.workspaceId == here ? 'shared' : 'shared from ${d.workspaceId}');
    return ListTile(
      key: Key('document-${d.uid}'),
      leading: Icon(d.published ? Icons.description_outlined : Icons.edit_note,
          color: d.published ? theme.colorScheme.primary : theme.colorScheme.outline),
      title: Text(d.title, maxLines: 2, overflow: TextOverflow.ellipsis),
      subtitle: Text(keyed(ref.watch(showKeysProvider), d.code, [d.published ? 'published' : 'not published yet', shared])),
      onTap: () => context.push('/document/${d.uid}'),
    );
  }
}
