import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';

/// Advanced query: tickets, equipment or documents selected by a query such as
/// `status = Open AND assignee = currentUser() ORDER BY priority DESC`. Without `project = …` it searches
/// this workspace (and what is shared); `project in (a, b)` searches those.
class QueryScreen extends ConsumerStatefulWidget {
  const QueryScreen({super.key, this.entity = 'tickets', this.jql});

  final String entity;
  final String? jql;

  @override
  ConsumerState<QueryScreen> createState() => _QueryScreenState();
}

const _examples = {
  'tickets': [
    'assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC',
    'created >= -7d ORDER BY created DESC',
    'text ~ "vacuum leak" AND status != closed',
    'equipment = SPARC-IP-01',
  ],
  'assets': [
    'type = "Ion Pump" ORDER BY key',
    'label = LNFMAC-128463',
    'serial ~ VPI AND updated >= startOfMonth()',
    'status = Retired',
  ],
  'documents': [
    'status = published ORDER BY updated DESC',
    'status in (draft, in_review)',
    'text ~ bakeout',
    'type = Procedure AND updated >= -30d',
  ],
};

class _QueryScreenState extends ConsumerState<QueryScreen> {
  late String _entity = widget.entity;
  late final _jql = TextEditingController(text: widget.jql ?? '');
  bool _running = false;
  QueryResult? _result;
  Object? _error;

  @override
  void initState() {
    super.initState();
    if ((widget.jql ?? '').isNotEmpty) WidgetsBinding.instance.addPostFrameCallback((_) => _run());
  }

  @override
  void dispose() {
    _jql.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _running = true;
      _error = null;
    });
    try {
      final r = await ref.read(queryRepositoryProvider).run(_entity, _jql.text.trim());
      if (mounted) setState(() => _result = r);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _result = null;
        });
      }
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final showKeys = ref.watch(showKeysProvider);
    final error = _error;
    final position = error is Problem ? error.position : null;
    return Scaffold(
      appBar: AppBar(title: const Text('Advanced query')),
      body: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: SegmentedButton<String>(
            key: const Key('query-entity'),
            segments: const [
              ButtonSegment(value: 'tickets', label: Text('Tickets')),
              ButtonSegment(value: 'assets', label: Text('Equipment')),
              ButtonSegment(value: 'documents', label: Text('Documents')),
            ],
            selected: {_entity},
            onSelectionChanged: (s) => setState(() {
              _entity = s.first;
              _result = null;
              _error = null;
            }),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: TextField(
            key: const Key('query-jql'),
            controller: _jql,
            minLines: 2,
            maxLines: 5,
            style: const TextStyle(fontFamily: 'monospace'),
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _run(),
            decoration: InputDecoration(
              border: const OutlineInputBorder(),
              hintText: _examples[_entity]!.first,
              errorText: error == null
                  ? null
                  : [
                      error is Problem ? error.message : '$error',
                      if (position != null) 'at character ${position + 1}',
                    ].join(' '),
              errorMaxLines: 3,
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: Row(children: [
            Expanded(
              child: Text('Fields: key, summary, status, assignee, created, updated, type, project, text…',
                  style: theme.textTheme.bodySmall),
            ),
            FilledButton.icon(
              key: const Key('query-run'),
              onPressed: _running ? null : _run,
              icon: _running
                  ? const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.search),
              label: const Text('Search'),
            ),
          ]),
        ),
        if (_result == null && error == null) ...[
          const SectionHeader('Examples'),
          for (final e in _examples[_entity]!)
            ListTile(
              dense: true,
              title: Text(e, style: const TextStyle(fontFamily: 'monospace')),
              onTap: () {
                _jql.text = e;
                _run();
              },
            ),
        ],
        if (_result != null) ...[
          SectionHeader(
              _result!.capped ? 'At least ${_result!.total} found' : '${_result!.total} found',
              trailing: _result!.items.length < _result!.total ? 'first ${_result!.items.length}' : null),
          if (_result!.items.isEmpty) const ListTile(title: Text('Nothing matches.')),
          for (final h in _result!.items)
            ListTile(
              key: Key('query-hit-${h.uid}'),
              leading: Icon(switch (h.kind) {
                RecordKind.ticket => Icons.confirmation_number_outlined,
                RecordKind.document => Icons.description_outlined,
                _ => Icons.memory,
              }),
              title: Text(h.title, maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Text(keyed(showKeys, h.kind == RecordKind.ticket ? null : h.key,
                  [h.sub, h.workspaceId == ref.watch(workspaceIdProvider) ? null : h.workspaceName])),
              onTap: () => context.push(h.route),
            ),
        ],
      ]),
    );
  }
}
