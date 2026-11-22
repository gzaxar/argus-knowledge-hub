import 'dart:convert';

import 'local_store.dart';

/// The ARGUS servers this phone may talk to (flutter-app-design §6): the build's default, one the person chose
/// in Settings, and those it worked with lately. Only addresses are kept here — they survive a sign-out, so the
/// next sign-in still knows where ARGUS moved.
class BackendChoice {
  const BackendChoice({this.chosen, this.recent = const [], this.lastWorkspaceId, this.lastWorkspaceName});

  /// Set in Settings; null: the build's default.
  final String? chosen;

  /// The servers a sign-in was confirmed by, newest first.
  final List<String> recent;

  /// The workspace last worked in, to open in when no server can be reached at sign-in.
  final String? lastWorkspaceId;
  final String? lastWorkspaceName;

  /// Where to try a sign-in, in order: the chosen server, the last one that answered, the build's default.
  List<String> candidates(String defaultBase) =>
      {?chosen, ...recent.take(1), normalizeBackend(defaultBase)}.toList();
}

/// `argus.example.org`, `https://argus.example.org/v1/` → `https://argus.example.org`.
String normalizeBackend(String raw) {
  var s = raw.trim();
  if (s.isEmpty) return s;
  if (!s.contains('://')) s = 'https://$s';
  s = s.replaceAll(RegExp(r'/+$'), '');
  if (s.endsWith('/v1')) s = s.substring(0, s.length - 3);
  return s.replaceAll(RegExp(r'/+$'), '');
}

class BackendStore {
  BackendStore(this.store);

  final LocalStore store;
  static const _chosen = 'argus.backend.chosen';
  static const _recent = 'argus.backend.recent';
  static const _workspace = 'argus.backend.last-workspace';

  Future<BackendChoice> load() async {
    try {
      final recent = await store.read(_recent);
      final ws = await store.read(_workspace);
      final w = ws == null ? null : jsonDecode(ws) as Map<String, dynamic>;
      return BackendChoice(
        chosen: await store.read(_chosen),
        recent: recent == null ? const [] : (jsonDecode(recent) as List).cast<String>(),
        lastWorkspaceId: w?['id'] as String?,
        lastWorkspaceName: w?['name'] as String?,
      );
    } catch (_) {
      return const BackendChoice();
    }
  }

  Future<void> choose(String? base) => base == null ? store.delete(_chosen) : store.write(_chosen, base);

  Future<void> remember(String base) async {
    final now = await load();
    final recent = [base, ...now.recent.where((r) => r != base)].take(5).toList();
    await store.write(_recent, jsonEncode(recent));
  }

  Future<void> rememberWorkspace(String id, String name) =>
      store.write(_workspace, jsonEncode({'id': id, 'name': name}));
}
