import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/providers.dart';
import '../home/home_screen.dart' show signOut;

/// The app's frame: six destinations along the bottom, each keeping its place while another is open, and a
/// drawer for everything about the person and the app rather than the records — account and workspace,
/// settings, about, help. A record opened from any of them covers the frame, as a page of its own.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  static const destinations = [
    (key: 'nav-home', icon: Icons.dashboard_outlined, selected: Icons.dashboard, label: 'Home'),
    (key: 'nav-tickets', icon: Icons.confirmation_number_outlined, selected: Icons.confirmation_number, label: 'Tickets'),
    (key: 'nav-documents', icon: Icons.description_outlined, selected: Icons.description, label: 'Docs'),
    (key: 'nav-assets', icon: Icons.memory_outlined, selected: Icons.memory, label: 'Assets'),
    (key: 'nav-graph', icon: Icons.hub_outlined, selected: Icons.hub, label: 'Graph'),
    (key: 'nav-ask', icon: Icons.smart_toy_outlined, selected: Icons.smart_toy, label: 'Ask'),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      key: shellScaffoldKey,
      drawer: const AppDrawer(),
      body: _NewsWhileOpen(child: shell),
      bottomNavigationBar: NavigationBar(
        key: const Key('nav-bar'),
        selectedIndex: shell.currentIndex,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        onDestinationSelected: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
        destinations: [
          for (final d in destinations)
            NavigationDestination(
                key: Key(d.key), icon: Icon(d.icon), selectedIcon: Icon(d.selected), label: d.label),
        ],
      ),
    );
  }
}

/// The frame's scaffold, so a destination's own app bar can open the drawer that belongs to the frame.
final shellScaffoldKey = GlobalKey<ScaffoldState>();

/// The menu button a destination's app bar leads with.
class ShellMenuButton extends StatelessWidget {
  const ShellMenuButton({super.key});

  @override
  Widget build(BuildContext context) => IconButton(
        key: const Key('nav-menu'),
        tooltip: 'Menu',
        icon: const Icon(Icons.menu),
        onPressed: () => shellScaffoldKey.currentState?.openDrawer(),
      );
}

class AppDrawer extends ConsumerWidget {
  const AppDrawer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider).value;
    final config = ref.watch(configProvider);
    final features = ref.watch(workspaceFeaturesProvider).value;
    final hasMap = features == null || features.contains('map');
    final theme = Theme.of(context);
    void open(String path) {
      Navigator.pop(context);
      context.push(path);
    }

    return NavigationDrawer(
      key: const Key('app-drawer'),
      selectedIndex: null,
      children: [
        DrawerHeader(
          decoration: BoxDecoration(color: theme.colorScheme.primaryContainer),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.end, children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.asset('assets/branding/argus_icon.png', width: 48, height: 48),
            ),
            const SizedBox(height: 8),
            Text('ARGUS Field', style: theme.textTheme.titleLarge?.copyWith(color: theme.colorScheme.onPrimaryContainer)),
            if (session?.userLabel != null)
              Text(session!.userLabel!, style: TextStyle(color: theme.colorScheme.onPrimaryContainer)),
            if (session?.workspaceName != null)
              Text('Workspace: ${session!.workspaceName}',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onPrimaryContainer)),
          ]),
        ),
        const _Section('Account'),
        _Item('drawer-workspace', Icons.swap_horiz, 'Switch workspace', () => open('/workspace')),
        _Item('drawer-inbox', Icons.notifications_none, 'Notifications', () => open('/inbox')),
        _Item('drawer-outbox', Icons.cloud_upload_outlined, 'Unsent changes', () => open('/outbox')),
        _Item('drawer-reviews', Icons.rule, 'Review items', () => open('/reviews')),
        _Item('drawer-signout', Icons.logout, 'Sign out', () {
          Navigator.pop(context);
          signOut(context, ref);
        }),
        const Divider(indent: 28, endIndent: 28),
        const _Section('App'),
        _Item('drawer-activities', Icons.event_note_outlined, 'Activities', () => open('/activities')),
        _Item('drawer-capture', Icons.mic_none, 'Capture by voice', () => open('/capture')),
        _Item('drawer-query', Icons.manage_search, 'Advanced query', () => open('/query')),
        if (hasMap) ...[
          _Item('drawer-nearby', Icons.near_me_outlined, 'Near me', () => open('/nearby')),
          _Item('drawer-location-reviews', Icons.edit_location_alt_outlined, 'Locations to review',
              () => open('/location-reviews')),
        ],
        _Item('drawer-settings', Icons.settings_outlined, 'Settings', () => open('/settings')),
        _Item('drawer-help', Icons.help_outline, 'Help', () {
          Navigator.pop(context);
          launchUrl(Uri.https(config.linkHost.isEmpty ? Uri.parse(config.apiBase).host : config.linkHost, '/help'),
              mode: LaunchMode.externalApplication);
        }),
        _Item('drawer-about', Icons.info_outline, 'About and diagnostics', () => open('/diagnostics')),
        _Item('drawer-privacy', Icons.privacy_tip_outlined, 'Privacy policy', () {
          Navigator.pop(context);
          launchUrl(config.privacyPolicy, mode: LaunchMode.externalApplication);
        }),
        Padding(
          padding: const EdgeInsets.fromLTRB(28, 16, 28, 16),
          child: Text('Version ${config.appVersion}', style: theme.textTheme.bodySmall),
        ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title);
  final String title;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(28, 16, 16, 8),
        child: Text(title, style: Theme.of(context).textTheme.titleSmall),
      );
}

class _Item extends StatelessWidget {
  const _Item(this.k, this.icon, this.label, this.onTap);
  final String k;
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: ListTile(
          key: Key(k),
          leading: Icon(icon),
          title: Text(label),
          shape: const StadiumBorder(),
          onTap: onTap,
        ),
      );
}


/// While the app is open — when it comes back to the front, and every couple of minutes — it asks for news:
/// the bell, "Your tickets" and, when the person turned it on, a phone notification for what is new. The
/// background check (phone_notifications.dart) covers the app closed.
class _NewsWhileOpen extends ConsumerStatefulWidget {
  const _NewsWhileOpen({required this.child});

  final Widget child;

  @override
  ConsumerState<_NewsWhileOpen> createState() => _NewsWhileOpenState();
}

class _NewsWhileOpenState extends ConsumerState<_NewsWhileOpen> with WidgetsBindingObserver {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final every = ref.read(phoneNotifierProvider).whileOpenEvery;
    if (every != null) _timer = Timer.periodic(every, (_) => _check());
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _check();
  }

  Future<void> _check() async {
    if (!mounted) return;
    await ref.read(phoneNotifierProvider).checkNow(ref.read(configProvider));
    if (!mounted) return;
    ref.invalidate(notificationsProvider);
    ref.invalidate(myWorkProvider);
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
