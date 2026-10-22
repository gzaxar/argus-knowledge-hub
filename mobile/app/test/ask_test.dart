import 'dart:convert';

import 'package:argus_field/app/providers.dart';
import 'package:argus_field/features/ask/voice.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fake_server.dart';
import 'harness.dart';

const _usable = {'configured': true, 'enabled': true, 'validated': true, 'model': 'test-model'};

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

/// The chat's answer as the server streams it: one `data:` line per event.
http.Response _events(List<Map<String, Object?>> events) => http.Response.bytes(
    utf8.encode(events.map((e) => 'data: ${jsonEncode(e)}\n\n').join()), 200,
    headers: {'content-type': 'text/event-stream'});

final _answer = _events([
  {'type': 'conversation', 'id': 'conv-1', 'title': 'How is IP-0001 reset?'},
  {'type': 'text', 'text': 'Let me look.'},
  {'type': 'text_reset'},
  {'type': 'step_start', 'index': 0, 'tool': 'search_records', 'arguments': {'q': 'IP-0001'}},
  {'type': 'step', 'index': 0, 'tool': 'search_records', 'arguments': {},
    'result': jsonEncode([{'uid': ionPumpUid, 'key': 'SLICE-IP-0001', 'name': 'Ion pump'}]), 'error': null,
    'seconds': 0.1, 'summary': '2 records'},
  {'type': 'text', 'text': 'Follow **PROC-12**: '},
  {'type': 'text', 'text': 'switch `SLICE-IP-0001` off, wait a minute.'},
  {'type': 'done', 'answer': 'Follow **PROC-12**: switch `SLICE-IP-0001` off, wait a minute.', 'steps': [], 'stopped': 'answered',
    'error': null, 'seconds': 1.2},
]);

class FakeVoice implements Voice {
  final said = <String>[];
  final heard = <String>[];
  bool allowed = true;

  @override
  Future<bool> canListen() async => allowed;

  @override
  Future<void> listen(void Function(String words, bool last) onWords) async {
    final words = heard.isEmpty ? '' : heard.removeAt(0);
    onWords(words, false);
    onWords(words, true);
  }

  @override
  Future<void> stopListening() async {}

  @override
  Future<void> speak(String text) async => said.add(text);

  @override
  Future<void> quiet() async {}
}

void main() {
  testWidgets('a typed question is answered as it is looked up, and a follow-up continues the conversation',
      (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/ai/status'] = _json(_usable);
    app.server.routes['POST /v1/ai/chat'] = _answer;
    await app.tap('nav-ask');

    await app.type('ask-input', 'How is IP-0001 reset?');
    await app.tap('ask-send');

    expect(find.text('How is IP-0001 reset?'), findsOneWidget);
    expect(find.text('2 records'), findsOneWidget, reason: 'the lookup behind the answer is shown');
    expect(find.textContaining('Follow PROC-12: switch SLICE-IP-0001 off', findRichText: true), findsOneWidget,
        reason: 'the answer is Markdown, rendered: no ** or backticks left in it');
    expect(find.textContaining('**', findRichText: true), findsNothing);
    expect(find.textContaining('Let me look'), findsNothing, reason: 'text before lookups is not the answer');
    expect(app.server.sent('POST', '/v1/ai/chat').single, {'question': 'How is IP-0001 reset?'});

    await app.type('ask-input', 'And after that?');
    await app.tap('ask-send');
    expect(app.server.sent('POST', '/v1/ai/chat').last, {'question': 'And after that?', 'conversation_id': 'conv-1'});
  });

  testWidgets('a spoken question is sent, and hands-free reads the answer aloud and listens again', (tester) async {
    final voice = FakeVoice()..heard.add('How is IP-0001 reset?');
    final app = await start(tester, overrides: [voiceProvider.overrideWithValue(voice)]);
    app.server.routes['GET /v1/ai/status'] = _json(_usable);
    app.server.routes['POST /v1/ai/chat'] = _answer;
    await app.tap('nav-ask');

    await app.tap('ask-handsfree');

    expect(app.server.sent('POST', '/v1/ai/chat').single['question'], 'How is IP-0001 reset?');
    expect(voice.said, ['Follow PROC-12: switch SLICE-IP-0001 off, wait a minute.'], reason: 'read without Markdown marks');
    // It listened again and heard nothing: hands-free ends, no second question is sent.
    expect(app.server.sent('POST', '/v1/ai/chat'), hasLength(1));
    expect(tester.widget<IconButton>(find.byKey(const Key('ask-handsfree'))).isSelected, isFalse);
  });

  testWidgets('a finished answer can be read aloud on request', (tester) async {
    final voice = FakeVoice();
    final app = await start(tester, overrides: [voiceProvider.overrideWithValue(voice)]);
    app.server.routes['GET /v1/ai/status'] = _json(_usable);
    app.server.routes['POST /v1/ai/chat'] = _answer;
    await app.tap('nav-ask');
    await app.type('ask-input', 'How is IP-0001 reset?');
    await app.tap('ask-send');

    expect(voice.said, isEmpty);
    await app.tap('ask-read-aloud');
    expect(voice.said, ['Follow PROC-12: switch SLICE-IP-0001 off, wait a minute.']);
  });

  testWidgets('an answer is rated: down asks what was wrong, and is sent once', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/ai/status'] = _json(_usable);
    app.server.routes['POST /v1/ai/chat'] = _answer;
    app.server.routes['POST /v1/ai/conversations/conv-1/feedback'] = _json({'rating': 'down', 'reported': true});
    await app.tap('nav-ask');
    await app.type('ask-input', 'How is IP-0001 reset?');
    await app.tap('ask-send');

    await app.tap('ask-rate-down');
    await app.type('ask-feedback-comment', 'It named the wrong pump.');
    await app.tap('ask-feedback-send');

    expect(app.server.sent('POST', '/v1/ai/conversations/conv-1/feedback').single,
        {'answer_index': 0, 'rating': 'down', 'comment': 'It named the wrong pump.'});
    expect(find.textContaining('without your name'), findsOneWidget);
    expect(find.byKey(const Key('ask-rate-up')), findsNothing, reason: 'an answer is rated once');
  });

  testWidgets('without a usable AI endpoint the assistant says why instead of offering itself', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/ai/status'] = _json({
      'configured': false, 'enabled': false, 'validated': false,
      'reason': 'No AI endpoint is configured for this workspace.',
    });
    await app.tap('nav-ask');

    expect(find.text('No AI endpoint is configured for this workspace.'), findsOneWidget);
    expect(find.byKey(const Key('ask-input')), findsNothing);
  });

  testWidgets('a refused question says why, and the person can ask again', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/ai/status'] = _json(_usable);
    app.server.routes['POST /v1/ai/chat'] = _json({'detail': 'AI features are switched off for this workspace'}, 409);
    await app.tap('nav-ask');
    await app.type('ask-input', 'Anything?');
    await app.tap('ask-send');

    expect(find.text('AI features are switched off for this workspace'), findsOneWidget);
    expect(find.byKey(const Key('ask-send')), findsOneWidget);
  });

  test('what is read aloud has no Markdown, links or code', () {
    expect(spoken('## Steps\n- **Open** [PROC-12](/document/x)\n- `reset` it\n```\ncode\n```'),
        'Steps\nOpen PROC-12\nreset it');
  });

  testWidgets('a record the answer cites is a link to it', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/ai/status'] = _json(_usable);
    app.server.routes['POST /v1/ai/chat'] = _answer;
    await app.tap('nav-ask');
    await app.type('ask-input', 'How is IP-0001 reset?');
    await app.tap('ask-send');

    await tester.tapOnText(find.textRange.ofSubstring('SLICE-IP-0001'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ask-input')), findsNothing, reason: 'the record opened over the chat');
    expect(app.server.requests.any((q) => q.url.path == '/v1/assets/$ionPumpUid'), isTrue);
  });
}
