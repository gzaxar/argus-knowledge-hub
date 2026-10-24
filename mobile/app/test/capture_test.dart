import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fake_server.dart';
import 'harness.dart';

void main() {
  testWidgets('an incident is reported on the Position, with the AI draft taken, its time and a photo',
      (tester) async {
    final app = await start(tester);
    await app.go('/asset/$positionUid');
    await app.tap('asset-report');
    expect(find.text('Report a problem'), findsWidgets);
    expect(find.text('Pressure spike on gun ion pump'), findsOneWidget); // already open here

    await app.type('report-words', 'The gun ion pump tripped at 03:10 tonight after an alarm, beam lost.');
    await app.tap('report-assist');
    // Proposals are shown, not applied.
    expect(find.byKey(const Key('proposal-title')), findsOneWidget);
    expect(find.textContaining('90% sure'), findsOneWidget);
    final list = find.byType(Scrollable).first;
    await tester.scrollUntilVisible(find.byKey(const Key('report-title')), 200, scrollable: list);
    expect(tester.widget<TextField>(find.byKey(const Key('report-title'))).controller!.text, isEmpty);
    await tester.scrollUntilVisible(find.textContaining('Unconfirmed hypothesis'), -200, scrollable: list);
    expect(find.textContaining('Unconfirmed hypothesis'), findsOneWidget);

    await app.tap('report-take-all');
    await tester.scrollUntilVisible(find.byKey(const Key('report-title')), 200, scrollable: list);
    expect(tester.widget<TextField>(find.byKey(const Key('report-title'))).controller!.text,
        'Gun ion pump tripped, beam lost');
    await tester.scrollUntilVisible(find.byKey(const Key('when-chosen')), 200, scrollable: list);
    expect(find.byKey(const Key('when-chosen')), findsOneWidget);

    await app.tap('report-photo');
    expect(app.photos.taken, 1);

    // The guide finds a similar open ticket: shown first, then "Report anyway".
    await app.tap('report-submit');
    expect(find.byKey(const Key('check-similar')), findsOneWidget);
    expect(app.server.sent('POST', '/v1/issues'), isEmpty);
    await app.tap('report-submit');
    final errs = find.byKey(const Key('report-error'));
    if (errs.evaluate().isNotEmpty) fail(tester.widget<Text>(errs).data!);
    final [created] = app.server.sent('POST', '/v1/issues');
    expect(created['asset_uid'], positionUid);
    expect(created['schema_uid'], 'slice-20463f:operational-incident');
    expect(created['attributes']['occurred_from']['precision'], 'instant');
    // The assistant named the option by id; what is sent is its value, as the type defines it.
    expect(created['attributes']['argus_impact'], 'Beam down');
    final post = app.server.requests.firstWhere((r) => r.method == 'POST' && r.url.path == '/v1/issues');
    expect(post.headers['Idempotency-Key'], 'ticket:${created['uid']}');
    // The photo went up in pieces, was completed and attached to the new ticket.
    expect(app.server.requests.where((r) => r.method == 'PUT' && r.url.path == '/v1/uploads/up-1'), isNotEmpty);
    expect(app.server.requests.any((r) => r.url.path == '/v1/uploads/up-1/attach/ticket/${created['uid']}'), isTrue);
    // What the person kept is recorded against the run.
    final run = (fixtureJson('assist_ticket') as Map)['run_id'];
    final [outcome] = app.server.sent('POST', '/v1/intake/runs/$run/outcome');
    expect(outcome['record_uid'], created['uid']);
    expect(find.byKey(const Key('ticket-title')), findsOneWidget);
  });

  testWidgets('an incident without its time is not sent', (tester) async {
    final app = await start(tester);
    await app.go('/report/$positionUid');
    await app.type('report-title', 'Gauge reads zero');
    await app.tap('report-submit');
    expect(find.textContaining('Say when it happened'), findsOneWidget);
    expect(app.server.sent('POST', '/v1/issues'), isEmpty);
  });

  testWidgets('a comment is sent once with its own key, and a closing from the field is only proposed',
      (tester) async {
    final app = await start(tester);
    await app.go('/ticket/$ticketUid');
    await app.type('ticket-comment', 'Controller reset, pump back at 3e-9.');
    await app.tap('ticket-comment-send');
    final [c] = app.server.sent('POST', '/v1/issues/$ticketUid/comments');
    expect(c['body'], 'Controller reset, pump back at 3e-9.');
    expect(c['author'], isNull); // the server knows who is signed in
    final req = app.server.requests.lastWhere((r) => r.method == 'POST' && r.url.path == '/v1/issues/$ticketUid/comments');
    expect(req.headers['Idempotency-Key'], 'comment:${c['uid']}');

    app.server.routes['POST /v1/issues/$ticketUid/transition'] = http.Response(fixture('ticket'), 202,
        headers: {'content-type': 'application/json'});
    await app.tap('move-resolved');
    await app.type('move-comment', 'Reset and tested');
    await app.tap('move-confirm');
    final move = app.server.requests.lastWhere((r) => r.url.path == '/v1/issues/$ticketUid/transition');
    expect(move.headers['If-Match'], '"1"');
    expect(jsonDecode(move.body)['to'], 'resolved');
    expect(find.textContaining('Proposed: a person confirms it on the web'), findsOneWidget);
  });

  testWidgets('a move against a changed ticket reloads it and says so', (tester) async {
    final app = await start(tester);
    await app.go('/ticket/$ticketUid');
    app.server.routes['POST /v1/issues/$ticketUid/transition'] = http.Response(
        '{"detail":"x","problem":{"code":"stale","error":"changed","current":{"version":2}}}', 409,
        headers: {'content-type': 'application/json'});
    await app.tap('move-in_progress');
    expect(find.textContaining('changed this ticket meanwhile'), findsOneWidget);
  });

  testWidgets('a unit is registered from its nameplate: proposals taken, checked, saved with the photo',
      (tester) async {
    final app = await start(tester);
    await app.go('/register');
    await app.tap('register-photo');
    expect(find.byKey(const Key('proposal-attributes.serial')), findsOneWidget);
    expect(find.textContaining('read in “serial 77120”'), findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const Key('register-attr-serial'))).controller!.text, isEmpty);
    await app.tap('register-take-all');
    expect(tester.widget<TextField>(find.byKey(const Key('register-attr-serial'))).controller!.text, '77120');
    await app.tap('register-save');
    final [asset] = app.server.sent('POST', '/v1/assets');
    expect(asset['schema_uid'], 'slice-20463f:argus-object:ion-pump');
    expect(asset['attributes'], {'manufacturer': 'Agilent', 'model': 'VacIon Plus 75', 'serial': '77120'});
    expect(asset['key'], isNull); // the server gives the key
    expect(app.server.requests.any((r) => r.url.path == '/v1/uploads/up-1/attach/asset/${asset['uid']}'), isTrue);
    final run = (fixtureJson('assist_asset_photo') as Map)['run_id'];
    expect(app.server.sent('POST', '/v1/intake/runs/$run/outcome'), hasLength(1));
  });

  testWidgets('an unknown label offers registration, with the label as the serial', (tester) async {
    final app = await start(tester);
    await app.go('/lookup/SN-4411');
    await app.tap('resolve-register');
    expect(tester.widget<TextField>(find.byKey(const Key('register-attr-serial'))).controller!.text, 'SN-4411');
  });

  testWidgets('the inbox shows what is unread and opens the ticket', (tester) async {
    final app = await start(tester);
    await app.go('/');
    expect(find.text('1'), findsOneWidget); // the badge
    await app.tap('home-inbox');
    await app.tap('notification-12');
    expect(app.server.requests.any((r) => r.url.path == '/v1/notifications/everywhere/12/read'), isTrue);
    expect(find.byKey(const Key('ticket-title')), findsOneWidget);
  });
}
