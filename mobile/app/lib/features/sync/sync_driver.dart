import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/problem.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../data/command_queue.dart';

/// Sends pending commands when it can: at start, when the app comes back, when ARGUS answers
/// again, and every minute while something waits (flutter-app-design §5.3). It also refreshes the
/// person's assigned work into the saved copies, so it is at hand offline (§5.1).
class SyncDriver extends ConsumerStatefulWidget {
  const SyncDriver({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<SyncDriver> createState() => _SyncDriverState();
}

class _SyncDriverState extends ConsumerState<SyncDriver> with WidgetsBindingObserver {
  Timer? _timer;
  DateTime? _prefetched;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _timer = Timer.periodic(const Duration(minutes: 1), (_) => _tick());
    WidgetsBinding.instance.addPostFrameCallback((_) => _tick());
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _tick();
  }

  Future<void> _tick() async {
    if (!mounted) return;
    final session = ref.read(sessionProvider).value;
    if (session?.workspaceId == null) return;
    final queue = ref.read(queueProvider.notifier);
    if (queue.commands.any((c) => c.open)) await queue.sync();
    await _prefetch();
  }

  /// The person's assigned tickets and review items, fetched once an hour so their copies stay fresh.
  Future<void> _prefetch() async {
    if (_prefetched != null && DateTime.now().difference(_prefetched!) < const Duration(hours: 1)) return;
    _prefetched = DateTime.now();
    final api = ref.read(apiServiceProvider);
    try {
      await api.json((c) => api.issues(c).listIssuesWithHttpInfo(mine: true));
      await ref.read(reviewRepositoryProvider).mine();
    } catch (_) {
      _prefetched = null; // try again next time
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(reachabilityProvider, (before, now) {
      if (before?.reachable == false && now.reachable) _tick();
    });
    return widget.child;
  }
}

/// Across the top of every screen while ARGUS cannot be reached.
class OfflineBanner extends ConsumerWidget {
  const OfflineBanner({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reachable = ref.watch(reachabilityProvider).reachable;
    final waiting = (ref.watch(queueProvider).value ?? const <PendingCommand>[]).where((c) => c.open).length;
    final unconfirmed = ref.watch(sessionProvider.select((s) => s.value != null && !s.value!.verified));
    final renew = ref.watch(renewalNeededProvider);
    return Column(children: [
      if (renew)
        Material(
          color: Theme.of(context).colorScheme.errorContainer,
          child: SafeArea(
            bottom: false,
            child: ListTile(
              key: const Key('renewal-banner'),
              dense: true,
              leading: const Icon(Icons.key_off_outlined),
              title: const Text('ARGUS needs you to sign in again. What this phone keeps stays.'),
              trailing: TextButton(
                key: const Key('renewal-signin'),
                onPressed: () async {
                  try {
                    await ref.read(sessionProvider.notifier).renewBySigningIn();
                  } on Problem catch (p) {
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
                    }
                  }
                },
                child: const Text('Sign in'),
              ),
            ),
          ),
        ),
      if (unconfirmed && reachable)
        Material(
          color: Theme.of(context).colorScheme.secondaryContainer,
          child: const SafeArea(
            bottom: false,
            child: Padding(
              padding: EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: Text('Confirming your sign-in with ARGUS…', key: Key('unconfirmed-banner')),
            ),
          ),
        ),
      if (!reachable)
        Material(
          color: Theme.of(context).colorScheme.tertiaryContainer,
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: Row(children: [
                const Icon(Icons.cloud_off, size: 18),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    key: const Key('offline-banner'),
                    'Offline: showing copies saved on this device${waiting > 0 ? ' · $waiting change(s) waiting' : ''}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ]),
            ),
          ),
        ),
      Expanded(child: child),
    ]);
  }
}
