import 'dart:convert';

import 'package:argus_field/features/ask/ask_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fake_server.dart';
import 'harness.dart';

http.Response _json(Object body) =>
    http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json'});

Future<Running> _ask(WidgetTester tester) async {
  final r = await start(tester);
  r.server.routes['GET /v1/ai/status'] = _json({'configured': true, 'enabled': true, 'validated': true, 'model': 'm'});
  await r.tap('nav-ask');
  return r;
}

void main() {
  test('a title from the first words', () {
    expect(firstLineOf('Venting sector 3. Close the gate valve first.'), 'Venting sector 3');
    expect(firstLineOf('# Bake-out\nHeat it'), 'Bake-out');
    expect(firstLineOf('x' * 100).length, 78);
  });

  Future<void> dictated(WidgetTester tester, {required bool keep}) async {
    final r = await _ask(tester);
    const type = 'ws:argus-document:procedure';
    r.server.routes['GET /v1/schemas'] = _json([...(fixtureJson('schemas') as List),
      {'uid': type, 'workspace_id': 'ws', 'name': 'Procedure', 'applies_to': 'documents', 'attributes': []}]);
    r.server.routes['GET /v1/document-templates/resolve'] = _json({'ref': 'official:procedure', 'scope': 'official',
      'id': 'procedure', 'version': 1, 'name': 'Procedure', 'reason': 'the official template'});
    r.server.routes['POST /v1/ai/transcribe'] =
        _json({'text': 'Venting sector 3. Close the gate valve, then open the vent slowly.'});
    r.server.routes['POST /v1/ai/reshape'] = _json({
      'title': 'Venting sector 3',
      'markdown': '> ⚠ DRAFT — NOT usable as an operational instruction until validated.\n\n# Venting sector 3\n\n'
          '## Steps\n1. Close the gate valve.\n2. Open the vent slowly.\n',
      'template': {'ref': 'official:procedure', 'scope': 'official', 'id': 'procedure', 'version': 1,
        'name': 'Procedure', 'reason': 'the official template'},
      'model': 'm', 'extraction': {'fields': {}, 'sections': {}},
      'dates': {'document_date': '2026-10-22', 'document_date_needs_confirmation': true},
      'missing': ['Safety'], 'ambiguities': [], 'issues': [], 'links': [], 'uncited_lines': [],
      'notices': {'operational': '⚠ DRAFT — NOT usable as an operational instruction until validated.', 'reference': null},
    });
    r.server.routes['POST /v1/documents/reshape'] = http.Response(jsonEncode({'document_uid': 'doc-new', 'code': 'PROC-1',
      'revision_uid': 'doc-new-r1', 'revision_number': 1, 'state': 'draft'}), 201, headers: {'content-type': 'application/json'});

    await r.tap('ask-actions');
    await r.tap('ask-action-doc-voice');
    await tester.tap(find.byKey(const Key('reshape-type')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Procedure').last);
    await tester.pumpAndSettle();
    await r.tap('record-stop');                                // the recorder started once the type was known

    expect(r.server.requests.where((q) => q.url.path == '/v1/ai/transcribe'), hasLength(1));
    final asked = r.server.sent('POST', '/v1/ai/reshape').single;
    expect((asked['source'] as Map)['text'], 'Venting sector 3. Close the gate valve, then open the vent slowly.');
    expect((asked['source'] as Map)['kind'], 'intake');
    expect((asked['source'] as Map)['text_is_current'], true, reason: 'spoken now');
    expect(find.byKey(const Key('reshape-notice')), findsOneWidget, reason: 'a procedure is not usable until validated');

    await r.tap('reshape-confirm-date');
    expect(tester.widget<CheckboxListTile>(find.byKey(const Key('reshape-keep-recording'))).value, isFalse,
        reason: 'the audio is kept only if asked');
    if (keep) await r.tap('reshape-keep-recording');
    await r.tap('reshape-save');
    final saved = r.server.sent('POST', '/v1/documents/reshape').single;
    expect(saved['markdown'], contains('## Steps'));
    final uploads = r.server.sent('POST', '/v1/uploads');
    if (!keep) {
      expect(uploads, isEmpty, reason: 'the transcript is the source; the recording stays on the phone');
      return;
    }
    expect(uploads.single['content_type'], 'audio/mp4');
    final attach = r.server.requests.lastWhere((q) => q.url.path.contains('/attach/'));
    expect(attach.url.path, endsWith('/attach/document/doc-new/revision/doc-new-r1'));
  }

  testWidgets("a document is dictated, reworked with the type's template, reviewed and saved — the audio not kept",
      (tester) => dictated(tester, keep: false));
  testWidgets('…and with the recording kept, when asked', (tester) => dictated(tester, keep: true));

  testWidgets('a document is written from a photo of a page, and tidied by the assistant — with an undo',
      (tester) async {
    final r = await _ask(tester);
    r.texts.text = 'BAKE-OUT\nheat to 150 C for 48 h\nvent with dry nitrogen';
    r.server.routes['POST /v1/ai/draft-document'] =
        _json({'body_markdown': '# Bake-out\n\n1. Heat to 150 °C for 48 h.\n2. Vent with dry nitrogen.'});
    await r.tap('ask-actions');
    await r.tap('ask-action-doc-photo');
    expect(r.photos.taken, 1);
    expect(find.textContaining('vent with dry nitrogen'), findsOneWidget);

    await r.tap('doc-write-tidy');
    final asked = r.server.sent('POST', '/v1/ai/draft-document').single;
    expect(asked['notes'], contains('vent with dry nitrogen'));
    expect(find.textContaining('1. Heat to 150 °C'), findsOneWidget);
    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    expect(find.textContaining('heat to 150 C'), findsOneWidget, reason: "the person's own text is back");
  });

  testWidgets('equipment is registered from a photo: the camera opens at once', (tester) async {
    final r = await _ask(tester);
    await r.tap('ask-actions');
    await r.tap('ask-action-register-photo');
    expect(find.text('Register equipment'), findsOneWidget);
    expect(r.photos.taken, 1);
  });
}
