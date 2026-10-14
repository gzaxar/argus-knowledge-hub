import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';
import '../shell/app_shell.dart';

/// Home: find a record by scanning its label or by typing (flutter-app-design §5.1).
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  final _query = TextEditingController();
  Timer? _debounce;
  String _q = '';

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _changed(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () => setState(() => _q = v.trim()));
  }

  void _submit(String v) {
    final text = v.trim();
    if (text.isEmpty) return;
    // Enter on a label value (a key, an inventory number, a Jira key) goes straight to lookup.
    context.push('/lookup/${Uri.encodeComponent(text)}');
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider).value;
    return Scaffold(
      appBar: AppBar(
        leading: const ShellMenuButton(),
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('ARGUS Field'),
          if (session?.workspaceName != null)
            Text(session!.workspaceName!, style: Theme.of(context).textTheme.labelMedium),
        ]),
        actions: [
          const _Unsent(),
          const _InboxBell(),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('home-scan'),
        heroTag: 'home-scan', // the tabs stay mounted together: each its own hero
        onPressed: () => context.push('/scan'),
        icon: const Icon(Icons.qr_code_scanner),
        label: const Text('Scan label'),
      ),
      body: Column(children: [
        const _UpdateBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: TextField(
            key: const Key('home-search'),
            controller: _query,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search),
              hintText: 'Key, name, serial, ticket or document',
              border: const OutlineInputBorder(),
              suffixIcon: _query.text.isEmpty
                  ? IconButton(
                      key: const Key('home-advanced-search'),
                      tooltip: 'Advanced query',
                      icon: const Icon(Icons.manage_search),
                      onPressed: () => context.push('/query'))
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _query.clear();
                        setState(() => _q = '');
                      }),
            ),
            onChanged: _changed,
            onSubmitted: _submit,
          ),
        ),
        Expanded(child: _q.length < 2 ? const _Cockpit() : _Results(q: _q)),
      ]),
    );
  }
}

/// Signing out wipes the device (§5.6). Unsent changes would be lost: the person sees them first.
Future<void> signOut(BuildContext context, WidgetRef ref) async {
  final unsent = ref.read(queueProvider.notifier).unsent;
  if (unsent.isNotEmpty) {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Sign out and lose unsent changes?'),
        content: Text('These are on this device only and would be removed:\n'
            '${unsent.map((c) => '• ${c.label}').join('\n')}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Stay signed in')),
          FilledButton(
              key: const Key('signout-anyway'),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Sign out anyway')),
        ],
      ),
    );
    if (ok != true) return;
  }
  await ref.read(sessionProvider.notifier).signOut();
}

class _Unsent extends ConsumerWidget {
  const _Unsent();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final all = ref.watch(queueProvider).value ?? const [];
    final n = all.where((c) => c.open || c.needsPerson).length;
    if (n == 0) return const SizedBox.shrink();
    return IconButton(
      key: const Key('home-outbox'),
      tooltip: 'Unsent changes',
      onPressed: () => context.push('/outbox'),
      icon: Badge(label: Text('$n'), child: const Icon(Icons.cloud_upload_outlined)),
    );
  }
}

class _InboxBell extends ConsumerWidget {
  const _InboxBell();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = (ref.watch(notificationsProvider).value ?? const []).where((n) => !n.read).length;
    return IconButton(
      key: const Key('home-inbox'),
      tooltip: 'Notifications',
      onPressed: () => context.push('/inbox'),
      icon: Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: const Icon(Icons.notifications_none)),
    );
  }
}

/// The operations cockpit, what home shows before a search — the web's home, from the same overview: the
/// counts that need attention, what is assigned to me, the equipment tickets pile up on, the documents due
/// for review or approval, open tickets by state, and recent activity. A section the person may not read is
/// absent. Without the overview (offline, or not yet loaded) the scanning hint still shows.
class _Cockpit extends ConsumerWidget {
  const _Cockpit();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(cockpitProvider);
    final c = r.value;
    final review = c == null
        ? const <CockpitItem>[]
        : [...c.reviewOverdue, ...c.awaitingReview.where((d) => !c.reviewOverdue.any((o) => o.uid == d.uid))];
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(cockpitProvider);
        ref.invalidate(myWorkProvider);
        ref.invalidate(notificationsProvider);
      },
      child: ListView(key: const Key('home-cockpit'), padding: const EdgeInsets.only(bottom: 88), children: [
        if (r.isLoading && c == null) const LinearProgressIndicator(),
        if (c == null) const _Hint(),
        const _PhoneNewsOffer(),
        if (c != null) ...[
          _Kpis(c),
          _MyWork(fallback: c.mine),
          if (c.openTickets != null) ...[
            const SectionHeader('Equipment needing attention'),
            if (c.hotspots.isEmpty) const _Empty('No equipment has open tickets.'),
            for (final a in c.hotspots) _CockpitTile(a),
          ],
          if (c.inReview != null) ...[
            SectionHeader('Knowledge health',
                trailing: (c.notLinked ?? 0) > 0 ? '${c.notLinked} not linked to equipment' : null),
            if (review.isEmpty) const _Empty('No document is overdue for review or waiting for approval.'),
            for (final d in review.take(8))
              _CockpitTile(d, warning: c.reviewOverdue.contains(d) ? 'review overdue' : 'waiting for approval'),
          ],
          if (c.openTickets != null) ...[
            const SectionHeader('Open tickets by state'),
            if (c.byState.isEmpty) const _Empty('No open tickets.'),
            _ByState(c.byState),
          ],
          const SectionHeader('Recent activity'),
          if (c.recent.isEmpty) const _Empty('Nothing yet.'),
          for (final x in c.recent) _CockpitTile(x, showWhen: true),
        ],
      ]),
    );
  }
}

/// The counts at the top of the web's cockpit, each leading to where the work is.
class _Kpis extends StatelessWidget {
  const _Kpis(this.c);

  final Cockpit c;

  @override
  Widget build(BuildContext context) {
    final error = Theme.of(context).colorScheme.error;
    final tiles = [
      if (c.openTickets != null) ...[
        _Kpi(key: const Key('cockpit-open-tickets'), label: 'Open tickets', value: c.openTickets!,
            hint: c.totalTickets == null ? null : '${c.totalTickets} in total', to: '/tickets'),
        _Kpi(label: 'Unassigned', value: c.unassigned ?? 0, hint: 'nobody on it', to: '/tickets',
            alert: (c.unassigned ?? 0) > 0 ? error : null),
        _Kpi(label: 'No equipment', value: c.withoutAsset ?? 0, hint: 'open, no asset', to: '/tickets',
            alert: (c.withoutAsset ?? 0) > 0 ? Colors.amber.shade800 : null),
      ],
      if (c.inReview != null) ...[
        _Kpi(label: 'Awaiting approval', value: c.inReview!, hint: 'revisions in review', to: '/documents'),
        _Kpi(label: 'Reviews overdue', value: c.reviewOverdue.length, hint: 'past review date', to: '/documents',
            alert: c.reviewOverdue.isNotEmpty ? error : null),
      ],
      if (c.assets != null) _Kpi(label: 'Assets', value: c.assets!, hint: 'in this workspace'),
    ];
    if (tiles.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: LayoutBuilder(builder: (context, box) {
        final columns = box.maxWidth >= 560 ? 6 : 3;
        final width = (box.maxWidth - 8 * (columns - 1)) / columns;
        return Wrap(spacing: 8, runSpacing: 8, children: [
          for (final t in tiles) SizedBox(width: width, child: t),
        ]);
      }),
    );
  }
}

class _Kpi extends StatelessWidget {
  const _Kpi({super.key, required this.label, required this.value, this.hint, this.to, this.alert});

  final String label;
  final int value;
  final String? hint;
  final String? to;
  final Color? alert;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: to == null ? null : () => context.go(to!),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: theme.textTheme.labelSmall),
            Text('$value', style: theme.textTheme.headlineSmall?.copyWith(color: alert)),
            if (hint != null)
              Text(hint!, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
          ]),
        ),
      ),
    );
  }
}

/// Open tickets per state, largest first, each with a bar of its share.
class _ByState extends StatelessWidget {
  const _ByState(this.byState);

  final Map<String, int> byState;

  @override
  Widget build(BuildContext context) {
    final entries = byState.entries.where((e) => e.value > 0).toList()..sort((a, b) => b.value.compareTo(a.value));
    final total = entries.fold<int>(0, (n, e) => n + e.value);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(key: const Key('cockpit-by-state'), children: [
        for (final e in entries)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(children: [
              SizedBox(width: 110, child: Text(e.key.replaceAll('_', ' '), overflow: TextOverflow.ellipsis)),
              Expanded(child: LinearProgressIndicator(value: e.value / total, minHeight: 6,
                  borderRadius: BorderRadius.circular(3))),
              SizedBox(width: 40, child: Text('${e.value}', textAlign: TextAlign.right)),
            ]),
          ),
      ]),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
        child: Text(text, style: TextStyle(color: Theme.of(context).colorScheme.outline)),
      );
}

/// The person's open tickets in every workspace — assigned to them, reported by them, watched — whichever
/// workspace the app is in; one from another workspace opens there. Until it loads (or offline), this
/// workspace's own "assigned to me".
class _MyWork extends ConsumerWidget {
  const _MyWork({required this.fallback});

  final List<CockpitItem> fallback;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(myWorkProvider).value ?? fallback;
    if (items.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SectionHeader('Your tickets', trailing: '${items.length}'),
      for (final t in items.take(12)) _CockpitTile(t),
      if (items.length > 12)
        ListTile(
          dense: true,
          title: Text('${items.length - 12} more in the Tickets tab of each workspace'),
        ),
    ]);
  }
}

/// News on this phone is off until the person turns it on; until then the cockpit offers it, once.
class _PhoneNewsOffer extends ConsumerStatefulWidget {
  const _PhoneNewsOffer();

  @override
  ConsumerState<_PhoneNewsOffer> createState() => _PhoneNewsOfferState();
}

class _PhoneNewsOfferState extends ConsumerState<_PhoneNewsOffer> {
  static const _dismissedKey = 'argus.notify.offer-dismissed';
  bool _show = false;

  @override
  void initState() {
    super.initState();
    _decide();
  }

  Future<void> _decide() async {
    final notifier = ref.read(phoneNotifierProvider);
    if (!notifier.supported || await notifier.enabled) return;
    final dismissed = await ref.read(localStoreProvider).read(_dismissedKey);
    if (mounted && dismissed != '1') setState(() => _show = true);
  }

  Future<void> _dismiss() async {
    await ref.read(localStoreProvider).write(_dismissedKey, '1');
    if (mounted) setState(() => _show = false);
  }

  @override
  Widget build(BuildContext context) {
    if (!_show) return const SizedBox.shrink();
    return Card(
      key: const Key('home-news-offer'),
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Be told on this phone when a ticket is assigned to you, or something you follow changes — '
              'also while the app is closed.'),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: _dismiss, child: const Text('Not now')),
            FilledButton.tonal(
              key: const Key('home-news-on'),
              onPressed: () async {
                final on = await ref.read(phoneNotifierProvider).enable(ref.read(configProvider));
                if (on) await _dismiss();
                if (!on && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                      content: Text('Notifications are not allowed for ARGUS Field in the phone\'s settings.')));
                }
              },
              child: const Text('Turn on'),
            ),
          ]),
        ]),
      ),
    );
  }
}

class _CockpitTile extends ConsumerWidget {
  const _CockpitTile(this.item, {this.warning, this.showWhen = false});

  final CockpitItem item;
  final String? warning;
  final bool showWhen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final icon = switch (item.kind) {
      RecordKind.ticket => Icons.confirmation_number_outlined,
      RecordKind.document => Icons.description_outlined,
      _ => Icons.memory,
    };
    return ListTile(
      key: Key('cockpit-${item.kind.name}-${item.uid}'),
      dense: true,
      leading: Icon(icon, color: warning != null ? theme.colorScheme.error : null),
      title: Text(item.label, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text([
        ?warning,
        keyed(ref.watch(showKeysProvider), item.key, [item.sub]),
      ].where((e) => e.isNotEmpty).join(' · ')),
      trailing: item.count != null
          ? Badge(label: Text('${item.count}'))
          : showWhen && item.at != null
              ? Text(_ago(item.at!), style: theme.textTheme.bodySmall)
              : null,
      onTap: () => context.push(item.path),
    );
  }
}

String _ago(DateTime at) {
  final d = DateTime.now().difference(at);
  if (d.inMinutes < 1) return 'now';
  if (d.inHours < 1) return '${d.inMinutes} min';
  if (d.inDays < 1) return '${d.inHours} h';
  if (d.inDays < 30) return '${d.inDays} d';
  return formatWhenDate(at);
}

/// A newer release is out: offer to download it (an APK installs over this one as an update). Dismissed for
/// this run only — it comes back on the next start until the app is updated.
class _UpdateBanner extends ConsumerStatefulWidget {
  const _UpdateBanner();

  @override
  ConsumerState<_UpdateBanner> createState() => _UpdateBannerState();
}

class _UpdateBannerState extends ConsumerState<_UpdateBanner> {
  bool _dismissed = false;

  @override
  Widget build(BuildContext context) {
    final update = ref.watch(updateCheckProvider).value;
    if (update == null || _dismissed) return const SizedBox.shrink();
    return MaterialBanner(
      key: const Key('home-update'),
      leading: const Icon(Icons.system_update),
      content: Text('Version ${update.version} is available.'),
      actions: [
        TextButton(onPressed: () => setState(() => _dismissed = true), child: const Text('Later')),
        FilledButton(
          key: const Key('home-update-download'),
          onPressed: () => launchUrl(Uri.parse(update.url), mode: LaunchMode.externalApplication),
          child: const Text('Download'),
        ),
      ],
    );
  }
}

class _Hint extends StatelessWidget {
  const _Hint();

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            'Scan the label on the equipment or its position, or type at least two characters.\n'
            'Press Enter to look up an exact label value, such as an old Jira key.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ),
      );
}

class _Results extends ConsumerWidget {
  const _Results({required this.q});

  final String q;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(searchProvider(q));
    return r.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(searchProvider(q))),
      data: (res) => res.isEmpty
          ? Center(child: Text('Nothing matches "$q".'))
          : ListView(padding: const EdgeInsets.only(bottom: 96), children: [
              if (res.assets.isNotEmpty) ...[
                SectionHeader('Assets', trailing: '${res.assets.length}'),
                for (final t in res.assets) _hit(context, t, Icons.memory),
              ],
              if (res.tickets.isNotEmpty) ...[
                SectionHeader('Tickets', trailing: '${res.tickets.length}'),
                for (final t in res.tickets) _hit(context, t, Icons.confirmation_number_outlined),
              ],
              if (res.documents.isNotEmpty) ...[
                SectionHeader('Documents', trailing: '${res.documents.length}'),
                for (final t in res.documents) _hit(context, t, Icons.description_outlined),
              ],
            ]),
    );
  }

  Widget _hit(BuildContext context, LinkTarget t, IconData icon) => Consumer(
        builder: (context, ref, _) {
          final sub = keyed(ref.watch(showKeysProvider), t.key, [t.subtitle]);
          return ListTile(
            leading: Icon(icon),
            title: Text(t.title ?? t.uid, maxLines: 2, overflow: TextOverflow.ellipsis),
            subtitle: sub.isEmpty ? null : Text(sub),
            onTap: () => context.push(t.route),
          );
        },
      );
}
