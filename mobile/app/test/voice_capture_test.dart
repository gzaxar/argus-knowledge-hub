import 'dart:convert';

import 'package:argus_field/app/providers.dart';
import 'package:argus_field/app/queue.dart';
import 'package:argus_field/features/ask/voice.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'harness.dart';

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

ProviderContainer _container(Running app) => ProviderScope.containerOf(app.tester.element(find.byType(MaterialApp)));

/// A voice that "hears" the next of [heard] when the microphone is pressed.
class SpeakingVoice implements Voice {
  SpeakingVoice(this.heard);
  final List<String> heard;
  @override
  bool get canListenWhileSpeaking => false;
  @override
  Future<bool> canListen() async => true;
  @override
  Future<void> listen(void Function(String words, bool last) onWords,
      {void Function(double level)? onLevel, void Function(VoiceError error)? onError}) async {
    final w = heard.isEmpty ? '' : heard.removeAt(0);
    onWords(w.split(' ').first, false);                       // the live transcript, as it is heard
    onWords(w, true);
  }

  @override
  Future<void> stopListening() async {}
  @override
  Future<void> speak(String text, {void Function()? onWord}) async {}
  @override
  Future<void> quiet() async {}
  @override
  Future<void> setRate(double rate) async {}
}

const _types = [
  {'uid': 'ws:argus-ticket:bug', 'name': 'Bug'},
  {'uid': 'ws:argus-ticket:story', 'name': 'Story'},
];

Map<String, Object?> _proposal({
  String kind = 'ticket',
  Map<String, Object?> ticket = const {},
  Map<String, Object?> activity = const {},
  String? clarification,
  List<Map<String, Object?>> similar = const [],
}) => {
      'kind': kind,
      'explanation': kind == 'ticket' ? 'A failure reported.' : 'Work done.',
      'clarification': clarification,
      'evidence': ['pressure alarm is active'],
      'ticket': {'title': 'Vacuum pump failed', 'description': 'The vacuum pump failed last night.',
        'type_uid': 'ws:argus-ticket:bug', 'type': 'Bug', 'category': 'fault', 'impact': null,
        'occurred_at': '2026-10-21T00:00:00+02:00', 'uncertain': ['impact'], ...ticket},
      'activity': {'title': 'Replaced the filter', 'description': 'I replaced the filter yesterday.',
        'status': 'completed', 'timezone': 'Europe/Rome', 'all_day': true, 'actual_end': '2026-10-21T00:00:00+02:00',
        'uncertain': [], 'about_open_ticket': false, ...activity},
      'similar_tickets': similar,
      'ticket_types': _types,
      'categories': [{'id': 'fault', 'value': 'Fault'}, {'id': 'request', 'value': 'Request'}],
      'impacts': [{'id': 'safety', 'value': 'Safety'}],
      'model': 'm',
    };

Future<Running> _capture(WidgetTester tester, List<String> heard) async {
  final app = await start(tester, overrides: [
    voiceProvider.overrideWithValue(SpeakingVoice(heard)),
    deviceTimezoneProvider.overrideWith((_) async => 'Europe/Rome'),
  ]);
  app.server.routes['POST /v1/issues'] = _json({'uid': 'x'}, 201);
  await app.go('/capture');
  await tester.pumpAndSettle();
  return app;
}

void main() {
  testWidgets('a fault said aloud is proposed as a ticket of an installed type, and created only when confirmed',
      (tester) async {
    final app = await _capture(tester, ['The vacuum pump failed last night; the pressure alarm is active.']);
    app.server.routes['POST /v1/capture/classify'] = _json(_proposal());
    await app.tap('capture-mic');
    expect(find.widgetWithText(TextField, 'The vacuum pump failed last night; the pressure alarm is active.'),
        findsOneWidget, reason: 'the transcript, editable');
    await app.tap('capture-propose');

    final asked = app.server.sent('POST', '/v1/capture/classify').single;
    expect(asked['timezone'], 'Europe/Rome');
    expect(asked['transcript'], startsWith('The vacuum pump failed'));
    expect(find.text('Proposed: ticket'), findsOneWidget);
    expect(find.text('impact'), findsOneWidget, reason: 'what is uncertain is shown');
    expect(app.server.sent('POST', '/v1/issues'), isEmpty, reason: 'nothing is created before confirming');

    await app.tap('capture-confirm');
    final created = app.server.sent('POST', '/v1/issues').single;
    expect(created['schema_uid'], 'ws:argus-ticket:bug');
    expect(created['title'], 'Vacuum pump failed');
    expect(created['asset_uid'], isNull, reason: 'it works without an asset');
    expect((created['attributes'] as Map)['argus_category'], 'fault');
    expect((created['attributes'] as Map).containsKey('priority'), isFalse);
    expect(find.byKey(const Key('capture-created')), findsOneWidget);
    expect(find.byKey(const Key('capture-correct')), findsOneWidget);
  });

  testWidgets('work done yesterday becomes a completed activity, with its transcript as provenance and one key',
      (tester) async {
    final app = await _capture(tester, ['I replaced the filter yesterday and checked the pressure.']);
    app.server.routes['POST /v1/capture/classify'] = _json(_proposal(kind: 'activity'));
    app.server.routes['POST /v1/activities'] = _json({'id': 'a', 'title': 'Replaced the filter', 'status': 'completed'}, 201);
    await app.tap('capture-mic');
    await app.tap('capture-propose');
    expect(find.text('Proposed: activity'), findsOneWidget);
    await app.tap('capture-confirm');

    final sent = app.server.sent('POST', '/v1/activities').single;
    expect(sent['status'], 'completed');
    // The same instant as proposed — written in whatever zone the machine running the test is in.
    expect(DateTime.parse('${sent['actual_end']}').isAtSameMomentAs(DateTime.parse('2026-10-21T00:00:00+02:00')), isTrue);
    expect(sent['all_day'], true);
    expect(sent['timezone'], 'Europe/Rome');
    expect((sent['provenance'] as Map)['transcript'], 'I replaced the filter yesterday and checked the pressure.');
    final request = app.server.requests.lastWhere((r) => r.url.path == '/v1/activities');
    expect(request.headers['Idempotency-Key'], 'activity:${sent['uid']}');
  });

  testWidgets('an ambiguous capture asks one question, and the answer goes with the words', (tester) async {
    final app = await _capture(tester, ['the pump thing']);
    app.server.routes['POST /v1/capture/classify'] =
        _json(_proposal(kind: 'uncertain', clarification: 'Is this a problem to report, or work you did?'));
    await app.tap('capture-mic');
    await app.tap('capture-propose');
    expect(find.text('Ticket or activity? Choose below.'), findsOneWidget);
    expect(find.byKey(const Key('capture-confirm')), findsNothing, reason: 'nothing to confirm until it is chosen');
    await app.type('capture-clarify-answer', 'work I did this morning');
    app.server.routes['POST /v1/capture/classify'] = _json(_proposal(kind: 'activity'));
    await app.tap('capture-clarify-send');
    final second = app.server.sent('POST', '/v1/capture/classify').last;
    expect(second['clarification'], {'question': 'Is this a problem to report, or work you did?', 'answer': 'work I did this morning'});
    expect(find.text('Proposed: activity'), findsOneWidget);
  });

  testWidgets('an open ticket that looks the same: the words are added to it instead of a duplicate', (tester) async {
    final app = await _capture(tester, ['The vacuum pump pressure alarm is back.']);
    app.server.routes['POST /v1/capture/classify'] = _json(_proposal(similar: [
      {'uid': 't-1', 'title': 'Vacuum pump pressure alarm', 'state': 'new', 'score': 0.8},
    ]));
    app.server.routes['POST /v1/issues/t-1/comments'] = _json({'uid': 'c'}, 201);
    await app.tap('capture-mic');
    await app.tap('capture-propose');
    await tester.dragUntilVisible(find.byKey(const Key('capture-similar-t-1')), find.byKey(const Key('capture-list')),
        const Offset(0, -200));
    await app.tap('capture-similar-t-1');
    await tester.dragUntilVisible(find.byKey(const Key('capture-confirm')), find.byKey(const Key('capture-list')),
        const Offset(0, -200));
    await app.tap('capture-confirm');
    expect(app.server.sent('POST', '/v1/issues'), isEmpty);
    expect(app.server.sent('POST', '/v1/issues/t-1/comments').single['body'], 'The vacuum pump pressure alarm is back.');
  });

  testWidgets('without the assistant the words stay and the person fills it in', (tester) async {
    final app = await _capture(tester, ['I am starting the inspection now.']);
    app.server.routes['POST /v1/capture/classify'] = _json({'detail': 'No AI endpoint is configured'}, 409);
    app.server.routes['POST /v1/activities'] = _json({'id': 'a', 'title': 'x', 'status': 'planned'}, 201);
    await app.tap('capture-mic');
    await app.tap('capture-propose');
    expect(find.textContaining('No AI endpoint is configured'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'I am starting the inspection now.'), findsOneWidget);
    await tester.tap(find.text('Activity'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, 'I am starting the inspection now'), findsWidgets, reason: 'a title from the words');
    await tester.dragUntilVisible(find.byKey(const Key('capture-confirm')), find.byKey(const Key('capture-list')),
        const Offset(0, -200));
    await app.tap('capture-confirm');
    expect(app.server.sent('POST', '/v1/activities'), hasLength(1));
  });

  testWidgets('offline: kept as a draft, nothing guessed; back online it is proposed from the draft', (tester) async {
    final app = await _capture(tester, ['Inspect the filters next Monday.']);
    await app.tap('capture-mic');
    app.server.offline = true;
    await app.tap('capture-propose');
    expect(find.byKey(const Key('capture-draft-saved')), findsOneWidget);
    expect(app.server.sent('POST', '/v1/activities'), isEmpty);
    expect(app.server.sent('POST', '/v1/issues'), isEmpty);

    app.server.offline = false;
    app.server.routes['POST /v1/capture/classify'] = _json(_proposal(kind: 'activity', activity: {
      'title': 'Inspect the filters', 'status': 'planned', 'all_day': true,
      'planned_start': '2026-10-26T00:00:00+01:00', 'actual_end': null}));
    await app.go('/');
    await app.go('/capture');
    await tester.pumpAndSettle();
    final draft = find.byWidgetPredicate((w) => w.key is ValueKey && '${(w.key as ValueKey).value}'.startsWith('capture-draft-capture.draft.'));
    expect(draft, findsOneWidget);
    await tester.tap(draft);
    await tester.pumpAndSettle();
    expect(app.server.sent('POST', '/v1/capture/classify').single['transcript'], 'Inspect the filters next Monday.');
    expect(find.text('Proposed: activity'), findsOneWidget);
  });

  testWidgets('a confirmed activity that cannot be sent is retried with the same uid and key: one activity',
      (tester) async {
    final app = await _capture(tester, ['I replaced the filter yesterday.']);
    app.server.routes['POST /v1/capture/classify'] = _json(_proposal(kind: 'activity'));
    await app.tap('capture-mic');
    await app.tap('capture-propose');
    app.server.offline = true;
    await app.tap('capture-confirm');
    expect(find.textContaining('Saved on the phone'), findsOneWidget);

    app.server.offline = false;
    app.server.routes['POST /v1/activities'] = _json({'id': 'a', 'title': 'x', 'status': 'completed'}, 201);
    await _container(app).read(queueProvider.notifier).sync(force: true);
    await _container(app).read(queueProvider.notifier).sync(force: true);
    await tester.pumpAndSettle();
    final sent = app.server.requests.where((r) => r.url.path == '/v1/activities' && r.method == 'POST').toList();
    expect(sent, hasLength(1), reason: 'sent once it could be; not again once accepted');
    expect(sent.single.headers['Idempotency-Key'], startsWith('activity:'));
  });
}
