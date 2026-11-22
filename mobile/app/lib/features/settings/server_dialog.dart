import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/backends.dart';
import '../../core/problem.dart';

/// Choose the ARGUS server this phone talks to: another address, one used lately, or the build's default.
/// Signed in, the new server must accept the person before it is used; signed out, it is where the next
/// sign-in goes first. Returns whether something changed.
Future<bool> showServerDialog(BuildContext context, WidgetRef ref) async {
  final changed = await showDialog<bool>(context: context, builder: (_) => const _ServerDialog());
  return changed ?? false;
}

class _ServerDialog extends ConsumerStatefulWidget {
  const _ServerDialog();

  @override
  ConsumerState<_ServerDialog> createState() => _ServerDialogState();
}

class _ServerDialogState extends ConsumerState<_ServerDialog> {
  late final TextEditingController _url;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: ref.read(activeConfigProvider).apiBase);
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _use(String? raw) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final config = ref.read(configProvider);
    final base = raw == null ? null : normalizeBackend(raw);
    try {
      final problem = base == null ? null : config.backendProblem(base);
      if (problem != null) throw Problem(ProblemCode.invalid, problem);
      final target = base ?? normalizeBackend(config.apiBase);
      if (!await backendAnswers(ref.read(httpClientProvider), target)) {
        throw Problem(ProblemCode.offline, '$target does not answer as an ARGUS server.');
      }
      await ref.read(sessionProvider.notifier).switchBackend(base);
      if (mounted) Navigator.pop(context, true);
    } on Problem catch (p) {
      setState(() => _error = p.code == ProblemCode.unauthenticated
          ? 'That server does not accept your sign-in. Sign out and sign in there.'
          : p.message);
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final config = ref.watch(configProvider);
    final recent = ref.watch(backendProvider).value?.recent ?? const <String>[];
    final current = ref.watch(activeConfigProvider).apiBase;
    final home = normalizeBackend(config.apiBase);
    return AlertDialog(
      title: const Text('ARGUS server'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(
            key: const Key('server-url'),
            controller: _url,
            enabled: !_busy,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Server address', hintText: 'https://argus.example.org',
                border: OutlineInputBorder()),
            onSubmitted: _busy ? null : _use,
          ),
          const SizedBox(height: 8),
          Text('Your sign-in is sent to this server: use only one your organisation runs.',
              style: Theme.of(context).textTheme.bodySmall),
          for (final r in {home, ...recent}.where((r) => r != current))
            ListTile(
              key: Key('server-recent-$r'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(r == home ? Icons.home_outlined : Icons.history),
              title: Text(r),
              subtitle: r == home ? const Text("This app's default") : null,
              onTap: _busy ? null : () => _use(r == home ? null : r),
            ),
          if (_busy) const Padding(padding: EdgeInsets.only(top: 8), child: LinearProgressIndicator()),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_error!, key: const Key('server-error'),
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          key: const Key('server-use'),
          onPressed: _busy ? null : () => _use(_url.text),
          child: const Text('Use this server'),
        ),
      ],
    );
  }
}
