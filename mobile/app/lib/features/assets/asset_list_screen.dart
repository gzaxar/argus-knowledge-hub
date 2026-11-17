import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/browse_repository.dart';
import '../../widgets/common.dart';
import '../../widgets/sort_menu.dart';
import '../../widgets/type_tree.dart';
import '../shell/app_shell.dart';

/// The workspace's equipment, a page at a time: searched by key or name, narrowed to a type and everything
/// below it, sorted by name or by when it was created or last changed.
class AssetListScreen extends ConsumerStatefulWidget {
  const AssetListScreen({super.key});

  @override
  ConsumerState<AssetListScreen> createState() => _AssetListScreenState();
}

class _AssetListScreenState extends ConsumerState<AssetListScreen> {
  final _rows = <AssetRow>[];
  final _scroll = ScrollController();
  Timer? _typing;
  String _q = '';
  String? _type;
  ListOrder _order = const ListOrder(SortBy.name);
  int _total = 0;
  bool _loading = false;
  Object? _error;
  int _generation = 0; // a reload started after this page was asked for makes the page obsolete

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 400) _more();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _reload());
  }

  @override
  void dispose() {
    _scroll.dispose();
    _typing?.cancel();
    super.dispose();
  }

  Future<void> _reload() async {
    _generation++;
    setState(() {
      _rows.clear();
      _total = 0;
      _error = null;
      _loading = false;
    });
    await _more();
  }

  Future<void> _more() async {
    if (_loading || (_rows.isNotEmpty && _rows.length >= _total)) return;
    final generation = _generation;
    setState(() => _loading = true);
    try {
      final page = await ref
          .read(browseRepositoryProvider)
          .assets(schemaUid: _type, q: _q, order: _order, offset: _rows.length);
      if (!mounted || generation != _generation) return;
      setState(() {
        _rows.addAll(page.rows);
        _total = page.total;
      });
    } catch (e) {
      if (mounted && generation == _generation) setState(() => _error = e);
    } finally {
      if (mounted && generation == _generation) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tree = ref.watch(typeTreeProvider('objects')).value;
    final counts = ref.watch(assetTypeCountsProvider).value ?? const {};
    ref.listen(workspaceIdProvider, (_, _) => _reload());
    return Scaffold(
      appBar: AppBar(
        leading: const ShellMenuButton(),
        title: const Text('Assets'),
        actions: [
          SortMenu(order: _order, onChanged: (o) {
            _order = o;
            _reload();
          }),
          IconButton(
            key: const Key('assets-register'),
            tooltip: 'Register equipment',
            icon: const Icon(Icons.add_box_outlined),
            onPressed: () => context.push('/register'),
          ),
          PopupMenuButton<String>(
            key: const Key('assets-menu'),
            tooltip: 'More',
            onSelected: (to) => context.push(to),
            itemBuilder: (_) => const [
              PopupMenuItem(
                key: Key('assets-census'),
                value: '/census',
                child: ListTile(leading: Icon(Icons.dns_outlined), title: Text('Survey a rack'),
                    subtitle: Text('From photos: its units, the rack too'), contentPadding: EdgeInsets.zero),
              ),
            ],
          ),
        ],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: TextField(
            key: const Key('assets-search'),
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search),
              hintText: 'Key, name, label, serial or inventory',
              border: OutlineInputBorder(),
              isDense: true,
            ),
            onChanged: (v) {
              _typing?.cancel();
              _typing = Timer(const Duration(milliseconds: 350), () {
                _q = v;
                _reload();
              });
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Row(children: [
            Flexible(
              child: TypeFilterButton(
                tree: tree,
                selected: _type,
                counts: counts,
                onSelected: (t) {
                  _type = t;
                  _reload();
                },
              ),
            ),
            const SizedBox(width: 8),
            if (_total > 0) Text('$_total', key: const Key('assets-total'), style: Theme.of(context).textTheme.bodySmall),
          ]),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _reload,
            child: _error != null && _rows.isEmpty
                ? ListView(children: [ProblemView(_error!, onRetry: _reload)])
                : ListView.builder(
                    key: const Key('assets-list'),
                    controller: _scroll,
                    physics: const AlwaysScrollableScrollPhysics(),
                    itemCount: _rows.length + 1,
                    itemBuilder: (context, i) {
                      if (i == _rows.length) {
                        if (_loading) {
                          return const Padding(
                              padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()));
                        }
                        if (_rows.isEmpty) {
                          return const Padding(
                              padding: EdgeInsets.all(32), child: Center(child: Text('No equipment matches.')));
                        }
                        return const SizedBox(height: 88);
                      }
                      return _AssetTile(_rows[i], order: _order);
                    },
                  ),
          ),
        ),
      ]),
    );
  }
}

class _AssetTile extends ConsumerWidget {
  const _AssetTile(this.a, {required this.order});

  final AssetRow a;
  final ListOrder order;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final when = order.by == SortBy.created ? a.createdAt : a.updatedAt;
    final retired = a.status == 'Retired';
    return ListTile(
      key: Key('asset-${a.uid}'),
      leading: Icon(Icons.memory, color: retired ? Theme.of(context).colorScheme.outline : null),
      title: Text(a.name.isEmpty ? a.key : a.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(keyed(ref.watch(showKeysProvider), a.key, [a.type, if (a.shared) 'shared', if (retired) 'retired']),
          maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: when == null || order.by == SortBy.name
          ? null
          : Text(formatWhenDate(when), style: Theme.of(context).textTheme.bodySmall),
      onTap: () => context.push('/asset/${a.uid}'),
    );
  }
}
