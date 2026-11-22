// Where the app finds ARGUS (core/backends.dart): the server a session works with, others tried at sign-in when
// one does not answer, working offline when none does, and choosing a server in Settings.
import 'package:argus_field/app/app.dart';
import 'package:argus_field/app/providers.dart';
import 'package:argus_field/core/backends.dart';
import 'package:argus_field/core/config.dart';
import 'package:argus_field/core/problem.dart';
import 'package:argus_field/core/session.dart';
import 'package:argus_field/features/auth/auth_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

ProviderContainer _container(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(ArgusFieldApp)));

Future<void> _signInWithToken(WidgetTester tester) async {
  await tester.enterText(find.byKey(const Key('signin-token')), 'tok');
  await tester.tap(find.byKey(const Key('signin-token-submit')));
  await tester.pumpAndSettle();
}

/// The sign-in service is down: a renewal neither succeeds nor is refused.
class _UnreachableAuth implements Authenticator {
  int asked = 0;
  @override
  bool get supportsOidc => false;
  @override
  Future<Session> signInWithOidc([String provider = 'main']) => throw UnimplementedError();
  @override
  Future<Session?> refresh(Session s) async {
    asked++;
    throw Problem(ProblemCode.offline, 'The sign-in service cannot be reached.');
  }

  @override
  Future<void> endSession(Session s) async {}
}

void main() {
  test('a production build takes only HTTPS servers of its own domain', () {
    const prod = AppConfig(environment: 'production', apiBase: 'https://argus-hub-api.lnf.infn.it',
        linkHost: 'x', oidcIssuer: '', oidcClientId: '', oidcRedirect: '', appVersion: '1');
    expect(prod.backendProblem('https://argus-hub-api.lnf.infn.it'), isNull);
    expect(prod.backendProblem('https://argus.cloud.infn.it'), isNull, reason: 'another INFN host');
    expect(prod.backendProblem('http://argus.lnf.infn.it'), contains('HTTPS'));
    expect(prod.backendProblem('https://evil.example.org'), contains('infn.it'));
    expect(testConfig.backendProblem('http://10.0.2.2:8080'), isNull, reason: 'a development build takes any');
    expect(normalizeBackend('argus.lnf.infn.it/v1/'), 'https://argus.lnf.infn.it');
  });

  testWidgets('a server that does not answer the sign-in gives way to the next one', (tester) async {
    final r = await start(tester, stored: const {'argus.backend.chosen': 'https://moved.argus.test'},
        prepare: (s) => s.unreachableHosts.add('moved.argus.test'));
    await _signInWithToken(tester);
    final session = _container(tester).read(sessionProvider).value!;
    expect(session.apiBase, 'https://argus.test', reason: "the build's default answered");
    expect(session.verified, isTrue);
    expect(r.server.requests.any((q) => q.url.path == '/v1/devices' && q.url.host == 'argus.test'), isTrue);
    expect(find.byKey(Key('workspace-$workspaceId')), findsOneWidget);
  });

  testWidgets('with no server answering, the app opens offline where the person last worked, and confirms the '
      'sign-in when ARGUS is back', (tester) async {
    final r = await start(tester, stored: const {
      'argus.backend.last-workspace': '{"id":"$workspaceId","name":"Slice"}',
    }, prepare: (s) => s.offline = true);
    await _signInWithToken(tester);
    expect(find.byKey(const Key('signin-error')), findsOneWidget);
    await tester.tap(find.byKey(const Key('signin-continue-offline')));
    await tester.pumpAndSettle();
    final c = _container(tester);
    expect(c.read(sessionProvider).value!.verified, isFalse);
    expect(c.read(sessionProvider).value!.workspaceId, workspaceId);
    expect(find.byKey(const Key('home-search')), findsOneWidget, reason: 'in the app, on what it kept');

    r.server.offline = false;
    await c.read(sessionProvider.notifier).confirmPending();
    await tester.pumpAndSettle();
    final s = c.read(sessionProvider).value!;
    expect(s.verified, isTrue);
    expect(s.deviceId, isNotNull, reason: 'the device registered once ARGUS answered');
  });

  testWidgets('with no server and no workspace remembered, there is no going in offline', (tester) async {
    await start(tester, stored: const {}, prepare: (s) => s.offline = true);
    await _signInWithToken(tester);
    expect(find.byKey(const Key('signin-error')), findsOneWidget);
    expect(find.byKey(const Key('signin-continue-offline')), findsNothing);
  });

  testWidgets('a renewal the sign-in service cannot answer keeps the session', (tester) async {
    final auth = _UnreachableAuth();
    await start(tester, stored: {
      'argus.session': '{"accessToken":"tok","authType":"oidc","refreshToken":"r","expiresAt":"2020-01-01T00:00:00Z",'
          '"workspaceId":"$workspaceId","workspaceName":"Slice","deviceId":"dev-1"}',
    }, overrides: [authenticatorProvider.overrideWithValue(auth)]);
    final c = _container(tester);
    await c.read(sessionProvider.notifier).ensureFresh();
    await tester.pumpAndSettle();
    expect(auth.asked, greaterThan(0));
    expect(c.read(sessionProvider).value, isNotNull, reason: 'not signed out for want of a network');
    expect(find.byKey(const Key('signin-token')), findsNothing);
  });

  testWidgets('Settings moves the app to another server, which must accept the person', (tester) async {
    final r = await start(tester);
    await r.go('/settings');
    expect(find.text('https://argus.test'), findsOneWidget);
    await r.tap('settings-server');
    await tester.enterText(find.byKey(const Key('server-url')), 'https://new.argus.test');
    await r.tap('server-use');
    final s = _container(tester).read(sessionProvider).value!;
    expect(s.apiBase, 'https://new.argus.test');
    expect(r.server.requests.any((q) => q.url.host == 'new.argus.test' && q.url.path == '/v1/devices'), isTrue,
        reason: 'registered on the new server');
    expect(s.workspaceId, workspaceId, reason: 'the same workspace');
    r.server.requests.clear();
    await r.go('/tickets');
    expect(r.server.requests.where((q) => q.url.path.startsWith('/v1/')).every((q) => q.url.host == 'new.argus.test'),
        isTrue);
  });

  testWidgets('a server that does not answer is not switched to', (tester) async {
    final r = await start(tester, prepare: (s) => s.unreachableHosts.add('down.argus.test'));
    await r.go('/settings');
    await r.tap('settings-server');
    await tester.enterText(find.byKey(const Key('server-url')), 'https://down.argus.test');
    await r.tap('server-use');
    expect(find.byKey(const Key('server-error')), findsOneWidget);
    expect(_container(tester).read(sessionProvider).value!.apiBase, isNull, reason: 'still the default');
  });
}
