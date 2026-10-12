import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show ProviderListenable;
import 'package:go_router/go_router.dart';

import '../core/problem.dart';
import '../domain/capture.dart' show DocumentSeed;
import '../domain/models.dart' show RecordKind;
import '../features/ask/ask_screen.dart';
import '../features/assets/asset_list_screen.dart';
import '../features/graph/graph_record_screen.dart';
import '../features/graph/graph_screen.dart';
import '../features/search/query_screen.dart';
import '../features/places/location_reviews_screen.dart';
import '../features/places/nearby_screen.dart';
import '../widgets/in_workspace.dart';
import '../features/settings/settings_screen.dart';
import '../features/shell/app_shell.dart';
import '../features/auth/signin_screen.dart';
import '../features/capture/register_screen.dart';
import '../features/installations/replace_screen.dart';
import '../features/review/review_screen.dart';
import '../features/sync/outbox_screen.dart';
import '../features/notifications/inbox_screen.dart';
import '../features/tickets/report_screen.dart';
import '../features/auth/update_screen.dart';
import '../features/auth/workspace_screen.dart';
import '../features/diagnostics/diagnostics_screen.dart';
import '../features/documents/document_screen.dart';
import '../features/documents/document_list_screen.dart';
import '../features/documents/document_write_screen.dart';
import '../features/tickets/ticket_edit_screen.dart';
import '../features/tickets/ticket_list_screen.dart';
import '../features/home/home_screen.dart';
import '../features/records/asset_edit_screen.dart';
import '../features/records/asset_screen.dart';
import '../features/records/resolve_screen.dart';
import '../features/scan/scan_screen.dart';
import '../features/tickets/ticket_screen.dart';
import 'providers.dart';

/// A place to return to after sign-in: only a path inside the app, never another origin.
String? safeReturn(String? from) {
  if (from == null || !from.startsWith('/') || from.startsWith('//')) return null;
  if (from.startsWith('/signin') || from.startsWith('/splash') || from.startsWith('/update')) return null;
  return from;
}

final _uid = RegExp(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$');
bool isUid(String s) => _uid.hasMatch(s);

/// Routes (flutter-app-design §7). The universal-link paths are the web's paths, so a link or a
/// label opens the same record in either client. Links other than /asset go through the server's
/// resolver, which also decides what this person may see (I-MOB-6).
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);
  ref.listen(updateRequiredProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  String? redirect(GoRouterState st) {
    final path = st.uri.path;
    final here = st.uri.toString();
    if (ref.read(updateRequiredProvider) != null) return path == '/update' ? null : '/update';

    final s = ref.read(sessionProvider);
    String withFrom(String to, String from) => '$to?from=${Uri.encodeComponent(from)}';
    final from = safeReturn(st.uri.queryParameters['from']);
    if (!s.hasValue && !s.hasError) return path == '/splash' ? null : withFrom('/splash', here);

    final session = s.value;
    if (session == null) {
      if (path == '/signin') return null;
      return withFrom('/signin', path == '/splash' ? (from ?? '/') : here);
    }
    if (session.workspaceId == null) {
      if (path == '/workspace') return null;
      return withFrom('/workspace', (path == '/splash' || path == '/signin') ? (from ?? '/') : here);
    }
    if (path == '/signin' || path == '/splash' || path == '/update') return from ?? '/';
    return null;
  }

  return GoRouter(
    initialLocation: '/',
    refreshListenable: refresh,
    debugLogDiagnostics: kDebugMode,
    redirect: (_, st) => redirect(st),
    routes: [
      GoRoute(path: '/splash', builder: (_, _) => const SplashScreen()),
      GoRoute(path: '/signin', builder: (_, _) => const SignInScreen()),
      GoRoute(path: '/update', builder: (_, _) => const UpdateScreen()),
      GoRoute(
          path: '/workspace',
          builder: (_, st) => WorkspaceScreen(returnTo: safeReturn(st.uri.queryParameters['from']))),
      // The six destinations of the navigation bar, each keeping its place (features/shell/app_shell.dart).
      StatefulShellRoute.indexedStack(
        builder: (_, _, shell) => AppShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/', builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/tickets', builder: (_, _) => const TicketListScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/documents', builder: (_, _) => const DocumentListScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/assets', builder: (_, _) => const AssetListScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/graph', builder: (_, _) => const GraphScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/ask', builder: (_, _) => const AskScreen())]),
        ],
      ),
      GoRoute(path: '/settings', builder: (_, _) => const SettingsScreen()),
      GoRoute(
          path: '/graph/:kind/:uid',
          builder: (_, st) => GraphRecordScreen(
              kind: RecordKind.values.firstWhere((k) => k.name == st.pathParameters['kind'],
                  orElse: () => RecordKind.asset),
              uid: st.pathParameters['uid']!,
              title: st.uri.queryParameters['title'] ?? st.pathParameters['uid']!)),
      GoRoute(path: '/scan', builder: (_, st) => ScanScreen(pick: st.uri.queryParameters['pick'] == '1')),
      GoRoute(path: '/diagnostics', builder: (_, _) => const DiagnosticsScreen()),
      GoRoute(path: '/inbox', builder: (_, _) => const InboxScreen()),
      GoRoute(path: '/report/:uid', builder: (_, st) => ReportScreen(subjectUid: st.pathParameters['uid']!)),
      GoRoute(
          path: '/register',
          builder: (_, st) =>
              RegisterScreen(
                  label: st.uri.queryParameters['label'],
                  pick: st.uri.queryParameters['pick'] == '1',
                  photoFirst: st.uri.queryParameters['photo'] == '1')),
      GoRoute(path: '/replace/:uid', builder: (_, st) => ReplaceScreen(positionUid: st.pathParameters['uid']!)),
      GoRoute(path: '/reviews', builder: (_, _) => const ReviewScreen()),
      GoRoute(path: '/nearby', builder: (_, _) => const NearbyScreen()),
      GoRoute(path: '/location-reviews', builder: (_, _) => const LocationReviewsScreen()),
      GoRoute(
          path: '/query',
          builder: (_, st) => QueryScreen(
              entity: st.uri.queryParameters['entity'] ?? 'tickets', jql: st.uri.queryParameters['jql'])),
      GoRoute(path: '/outbox', builder: (_, _) => const OutboxScreen()),
      GoRoute(
          path: '/asset/:uid',
          builder: (_, st) => InWorkspace(
              workspaceId: st.uri.queryParameters['ws'], child: () => AssetScreen(uid: st.pathParameters['uid']!))),
      GoRoute(path: '/asset/:uid/edit', builder: (_, st) => AssetEditScreen(uid: st.pathParameters['uid']!)),
      GoRoute(path: '/ticket/:uid/edit', builder: (_, st) => TicketEditScreen(uid: st.pathParameters['uid']!)),
      GoRoute(
          path: '/documents/new',
          builder: (_, st) => DocumentWriteScreen(
              assetUid: st.uri.queryParameters['asset'], seed: st.extra is DocumentSeed ? st.extra as DocumentSeed : null)),
      GoRoute(
          path: '/document/:uid/revision/:rev/edit',
          builder: (_, st) =>
              DocumentWriteScreen(documentUid: st.pathParameters['uid'], revisionUid: st.pathParameters['rev'])),
      // A document code or a Jira key in the link is resolved first; a uid opens directly.
      GoRoute(
          path: '/document/:id',
          builder: (_, st) => InWorkspace(
              workspaceId: st.uri.queryParameters['ws'],
              child: () => OpenOrResolve(
                  path: st.uri.path,
                  detail: documentDetailProvider(st.pathParameters['id']!),
                  screen: () => DocumentScreen(uid: st.pathParameters['id']!)))),
      GoRoute(
          path: '/ticket/:id',
          builder: (_, st) => InWorkspace(
              workspaceId: st.uri.queryParameters['ws'],
              child: () => OpenOrResolve(
                  path: st.uri.path,
                  detail: ticketDetailProvider(st.pathParameters['id']!),
                  screen: () => TicketScreen(uid: st.pathParameters['id']!)))),
      for (final kind in const ['position', 'installation', 'review', 'lookup'])
        GoRoute(path: '/$kind/:id', builder: (_, st) => ResolveScreen(path: st.uri.path)),
    ],
  );
});

/// A link inside the app carries a record's uid; a label or a web link may carry its code instead (DOC-0002,
/// a Jira key). A uid is not always a UUID — an imported record keeps its source's (`olog-sparc-sparc-151`) —
/// so the id is opened as a uid first, and only one that is no record's uid is resolved as a code.
class OpenOrResolve extends ConsumerWidget {
  const OpenOrResolve({super.key, required this.path, required this.detail, required this.screen});

  final String path;
  final ProviderListenable<AsyncValue<Object?>> detail;
  final Widget Function() screen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (isUid(path.split('/').last)) return screen();
    final e = ref.watch(detail).error;
    if (e is Problem && e.code == ProblemCode.notFound) return ResolveScreen(path: path);
    return screen();
  }
}
