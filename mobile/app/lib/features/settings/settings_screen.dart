import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/caching_client.dart';
import '../../core/problem.dart';
import '../../domain/capture.dart';
import '../../widgets/common.dart';
import 'server_dialog.dart';

/// What the person can set about the app itself, as opposed to the records: how it looks, and what it
/// keeps on the device.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    final config = ref.watch(configProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(children: [
        const SectionHeader('Appearance'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: SegmentedButton<ThemeMode>(
            key: const Key('settings-theme'),
            segments: const [
              ButtonSegment(value: ThemeMode.system, icon: Icon(Icons.brightness_auto), label: Text('System')),
              ButtonSegment(value: ThemeMode.light, icon: Icon(Icons.light_mode), label: Text('Light')),
              ButtonSegment(value: ThemeMode.dark, icon: Icon(Icons.dark_mode), label: Text('Dark')),
            ],
            selected: {mode},
            onSelectionChanged: (s) => ref.read(themeModeProvider.notifier).set(s.first),
          ),
        ),
        SwitchListTile(
          key: const Key('settings-show-keys'),
          title: const Text('Show keys'),
          subtitle: const Text('Equipment and documents with their key (SPARC-IP-01, PROC-0042); '
              'off: by name and title only'),
          value: ref.watch(showKeysProvider),
          onChanged: (v) => ref.read(showKeysProvider.notifier).set(v),
        ),
        const SectionHeader('Server'),
        const _Server(),
        const _Notifications(),
        const SectionHeader('On this device'),
        ListTile(
          leading: const Icon(Icons.offline_pin_outlined),
          title: const Text('Saved copies for offline use'),
          subtitle: Text('Records you open are kept, encrypted, for ${config.offlineRetentionDays} days, and shown '
              'when ARGUS cannot be reached. What you just saw is shown again for ${freshCopies.inSeconds} '
              'seconds without asking ARGUS; pull down on a list to refresh it.'),
          isThreeLine: true,
        ),
        ListTile(
          key: const Key('settings-clear-cache'),
          leading: const Icon(Icons.delete_sweep_outlined),
          title: const Text('Remove saved copies'),
          subtitle: const Text('Unsent changes are kept.'),
          onTap: () async {
            await ref.read(cacheStoreProvider).clear(CachingClient.prefix);
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved copies removed.')));
            }
          },
        ),
      ]),
    );
  }
}


/// What the person hears about, per workspace, and whether the phone shows it while the app is closed.
class _Notifications extends ConsumerStatefulWidget {
  const _Notifications();

  @override
  ConsumerState<_Notifications> createState() => _NotificationsState();
}

class _NotificationsState extends ConsumerState<_Notifications> {
  bool? _phone;
  final _saving = <String>{};

  @override
  void initState() {
    super.initState();
    ref.read(phoneNotifierProvider).enabled.then((on) {
      if (mounted) setState(() => _phone = on);
    });
  }

  Future<void> _setPhone(bool on) async {
    final notifier = ref.read(phoneNotifierProvider);
    if (on) {
      final allowed = await notifier.enable(ref.read(configProvider));
      if (!allowed && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Notifications are not allowed for ARGUS Field. Allow them in the system settings.')));
      }
      setState(() => _phone = allowed);
    } else {
      await notifier.disable();
      setState(() => _phone = false);
    }
  }

  Future<void> _set(WorkspaceSubscription s) async {
    setState(() => _saving.add(s.workspaceId));
    try {
      await ref.read(notificationRepositoryProvider).subscribe(s);
      ref.invalidate(subscriptionsProvider);
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _saving.remove(s.workspaceId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final notifier = ref.watch(phoneNotifierProvider);
    final subs = ref.watch(subscriptionsProvider);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SectionHeader('Notifications'),
      if (notifier.supported)
        SwitchListTile(
          key: const Key('settings-phone-notifications'),
          secondary: const Icon(Icons.notifications_active_outlined),
          title: const Text('Show news on this phone'),
          subtitle: const Text('Checked about every 15 minutes while the app is closed.'),
          value: _phone ?? false,
          onChanged: _phone == null ? null : _setPhone,
        ),
      const Padding(
        padding: EdgeInsets.fromLTRB(16, 4, 16, 4),
        child: Text('Besides the tickets you report, are assigned or watch, tell me about:'),
      ),
      subs.when(
        loading: () => const Padding(padding: EdgeInsets.all(16), child: LinearProgressIndicator()),
        error: (e, _) => ListTile(title: Text('$e')),
        data: (all) => Column(children: [
          for (final s in all)
            ExpansionTile(
              key: Key('settings-subscription-${s.workspaceId}'),
              leading: const Icon(Icons.workspaces_outline),
              title: Text(s.workspaceName),
              subtitle: Text(_summary(s)),
              children: [
                for (final (key, label, value, change) in [
                  ('tickets', 'New tickets', s.tickets, (bool v) => s.copyWith(tickets: v)),
                  ('documents', 'New and published documents', s.documents, (bool v) => s.copyWith(documents: v)),
                  ('assets', 'New equipment', s.assets, (bool v) => s.copyWith(assets: v)),
                ])
                  SwitchListTile(
                    key: Key('subscribe-${s.workspaceId}-$key'),
                    title: Text(label),
                    value: value,
                    onChanged: _saving.contains(s.workspaceId) ? null : (v) => _set(change(v)),
                  ),
              ],
            ),
        ]),
      ),
    ]);
  }
}

String _summary(WorkspaceSubscription s) {
  final what = [if (s.tickets) 'tickets', if (s.documents) 'documents', if (s.assets) 'equipment'];
  return what.isEmpty ? 'Nothing new' : 'New ${what.join(', ')}';
}


/// The ARGUS server in use, whether it answers, and changing it.
class _Server extends ConsumerWidget {
  const _Server();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final base = ref.watch(activeConfigProvider).apiBase;
    final reachable = ref.watch(reachabilityProvider).reachable;
    final verified = ref.watch(sessionProvider.select((s) => s.value?.verified ?? true));
    return ListTile(
      key: const Key('settings-server'),
      leading: Icon(reachable ? Icons.dns_outlined : Icons.cloud_off),
      title: Text(base),
      subtitle: Text([
        reachable ? 'Answering' : 'Not answering: the app shows the copies it kept',
        if (!verified) 'sign-in not yet confirmed',
      ].join(' · ')),
      trailing: const Icon(Icons.edit_outlined),
      onTap: () async {
        if (await showServerDialog(context, ref) && context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Now using ${ref.read(activeConfigProvider).apiBase}.')));
        }
      },
    );
  }
}
