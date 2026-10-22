import 'dart:convert';

import 'package:argus_field/app/providers.dart';
import 'package:argus_field/features/ask/voice.dart';
import 'package:argus_field/features/ask/voice_orb.dart';
import 'package:argus_field/features/ask/voice_turns.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'harness.dart';

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

http.Response _events(List<Map<String, Object?>> events) => http.Response.bytes(
    utf8.encode(events.map((e) => 'data: ${jsonEncode(e)}\n\n').join()), 200,
    headers: {'content-type': 'text/event-stream'});

final _answer = _events([
  {'type': 'conversation', 'id': 'conv-1', 'title': 'Pump'},
  {'type': 'text', 'text': 'The pump is in sector 1.'},
  {'type': 'done', 'answer': 'The pump is in sector 1.', 'steps': [], 'stopped': 'answered', 'error': null, 'seconds': 1},
]);

/// A voice the test speaks for, one word at a time if it likes.
class TestVoice implements Voice {
  void Function(String, bool)? words;
  int listens = 0, stops = 0;
  final said = <String>[];

  @override
  bool get canListenWhileSpeaking => false;
  @override
  Future<bool> canListen() async => true;
  @override
  Future<void> listen(void Function(String words, bool last) onWords,
      {void Function(double level)? onLevel, void Function(VoiceError error)? onError}) async {
    listens++;
    words = onWords;
    onLevel?.call(0.6);
  }

  @override
  Future<void> stopListening() async {
    stops++;
    words = null;
  }

  @override
  Future<void> speak(String text, {void Function()? onWord}) async {
    said.add(text);
    onWord?.call();
  }

  @override
  Future<void> quiet() async {}
  @override
  Future<void> setRate(double rate) async {}
}

Future<(Running, TestVoice)> _handsFree(WidgetTester tester, {bool reduced = true, http.Response? chat}) async {
  if (reduced) {
    tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
  }
  final voice = TestVoice();
  final app = await start(tester, overrides: [voiceProvider.overrideWithValue(voice)]);
  app.server.routes['GET /v1/ai/status'] = _json({'configured': true, 'enabled': true, 'validated': true, 'model': 'm'});
  app.server.routes['POST /v1/ai/chat'] = chat ?? _answer;
  await app.tap('nav-ask');
  if (reduced) {
    await app.tap('ask-handsfree');
  } else {
    await tester.tap(find.byKey(const Key('ask-handsfree')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }
  return (app, voice);
}

void main() {
  testWidgets('what is being said shows as it is heard, and is sent only when the turn ends', (tester) async {
    final (app, voice) = await _handsFree(tester);
    voice.words!('where is the', false);
    await tester.pumpAndSettle();
    expect(find.text('“where is the”'), findsOneWidget);
    expect(app.server.sent('POST', '/v1/ai/chat'), isEmpty);

    voice.words!('where is the pump', true);
    await tester.pumpAndSettle();
    expect(app.server.sent('POST', '/v1/ai/chat').single['question'], 'where is the pump');
    expect(voice.said.single, 'The pump is in sector 1.');
  });

  testWidgets('with reduced motion the orb is still, with an icon for its state', (tester) async {
    await _handsFree(tester);
    expect(find.byIcon(Icons.mic), findsWidgets, reason: 'listening, shown by an icon as well as the label');
    expect(find.text('Listening'), findsOneWidget);
    expect(tester.binding.hasScheduledFrame, isFalse, reason: 'nothing animates');
  });

  testWidgets('the orb moves while on screen, and leaving the tab ends hands-free and its animation', (tester) async {
    final (app, voice) = await _handsFree(tester, reduced: false);
    expect(tester.binding.transientCallbackCount, greaterThan(0), reason: 'the orb is animating');
    await tester.pump(const Duration(seconds: 1));
    expect(find.byType(VoiceOrb), findsOneWidget);

    await tester.tap(find.byKey(const Key('nav-documents')));
    await tester.pumpAndSettle(); // settles: off screen, nothing ticks
    expect(voice.stops, greaterThan(0), reason: 'the microphone is closed');
    await tester.tap(find.byKey(const Key('nav-ask')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ask-handsfree-panel')), findsNothing, reason: 'it does not come back by itself');
    expect(app.server.sent('POST', '/v1/ai/chat'), isEmpty);
  });

  testWidgets('ARGUS unreachable: its own message, the conversation kept, and Retry asks again', (tester) async {
    final (app, voice) = await _handsFree(tester, chat: _json({'detail': 'boom'}, 500));
    voice.words!('where is the pump', true);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ask-handsfree-error')), findsOneWidget);
    expect(find.text('where is the pump'), findsOneWidget, reason: 'the question stays in the conversation');
    app.server.routes['POST /v1/ai/chat'] = _answer;
    await app.tap('ask-handsfree-retry');
    expect(app.server.sent('POST', '/v1/ai/chat'), hasLength(2));
    expect(voice.said.single, 'The pump is in sector 1.');
  });

  testWidgets('on a small phone the panel fits', (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final (_, voice) = await _handsFree(tester);
    voice.words!('a long question that goes on and on about the vacuum of the linac and its ion pumps', false);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('ask-orb')), findsOneWidget);
  });

  testWidgets('the orb draws every state, moving and still', (tester) async {
    for (final reduced in [false, true]) {
      for (final state in TurnState.values) {
        await tester.pumpWidget(MediaQuery(
          data: MediaQueryData(disableAnimations: reduced),
          child: MaterialApp(home: Center(child: VoiceOrb(state: state, level: 0.4, words: 2, label: state.name))),
        ));
        await tester.pump(const Duration(milliseconds: 500));
        expect(tester.takeException(), isNull, reason: '$state reduced=$reduced');
        expect(find.bySemanticsLabel(state.name), findsOneWidget);
      }
    }
    await tester.pumpWidget(const SizedBox());
  });
}
