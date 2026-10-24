import 'package:argus_field/widgets/photo_text.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

String _text(WidgetTester tester, String key) => tester.widget<TextField>(find.byKey(Key(key))).controller!.text;

void main() {
  testWidgets('a document body takes the text of a chosen photo, read on the phone, after what was written',
      (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(find.byKey(const Key('asset-write-document')),
        find.byKey(const Key('asset-body-list')), const Offset(0, -300));
    await r.tap('asset-write-document');
    await r.type('doc-write-body', '# Bake-out');
    r.texts.text = 'Heat to 150 C for 48 h\nVent with dry nitrogen';

    await r.tap('photo-text-document');
    await r.tap('photo-text-gallery');
    expect(r.photos.lastFromGallery, isTrue);
    expect(_text(tester, 'doc-write-body'), '# Bake-out\nHeat to 150 C for 48 h\nVent with dry nitrogen');

    // The photo is the source: attached to the draft by default, so the original is not lost.
    expect(tester.widget<CheckboxListTile>(find.byKey(const Key('doc-write-keep-photos'))).value, isTrue);
    await r.type('doc-write-title', 'Bake-out');
    await r.tap('doc-write-save');
    final created = r.server.sent('POST', '/v1/documents').single;
    expect(created['body_markdown'], contains('Vent with dry nitrogen'));
    expect(r.server.sent('POST', '/v1/uploads').single['content_type'], 'image/jpeg');
  });

  testWidgets('the photo is not attached when the person says not to', (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(find.byKey(const Key('asset-write-document')),
        find.byKey(const Key('asset-body-list')), const Offset(0, -300));
    await r.tap('asset-write-document');
    r.texts.text = 'Heat to 150 C';
    await r.tap('photo-text-document');
    await r.tap('photo-text-camera');
    await r.tap('doc-write-keep-photos');
    await r.type('doc-write-title', 'Bake-out');
    await r.tap('doc-write-save');
    expect(r.server.sent('POST', '/v1/documents'), hasLength(1));
    expect(r.server.sent('POST', '/v1/uploads'), isEmpty);
  });

  testWidgets('a comment takes the text of a photo taken now', (tester) async {
    final r = await start(tester);
    await r.go('/ticket/$ticketUid');
    r.texts.text = 'E-42 vacuum interlock';
    await r.tap('photo-text-comment');
    await r.tap('photo-text-camera');
    expect(r.photos.lastFromGallery, isFalse);
    expect(_text(tester, 'ticket-comment'), 'E-42 vacuum interlock');
  });

  testWidgets('nothing read leaves the text as it was, and says so', (tester) async {
    final r = await start(tester);
    await r.go('/ticket/$ticketUid');
    await r.type('ticket-comment', 'Seen at 10:00');
    r.texts.text = '   ';
    await r.tap('photo-text-comment');
    await r.tap('photo-text-camera');
    expect(_text(tester, 'ticket-comment'), 'Seen at 10:00');
    expect(find.text('No text could be read in the photo.'), findsOneWidget);
  });

  test('read text goes where the cursor is, on a line of its own', () {
    final c = TextEditingController(text: 'first\nlast')
      ..selection = const TextSelection.collapsed(offset: 5);
    insertText(c, 'READ');
    expect(c.text, 'first\nREAD\nlast');
    final empty = TextEditingController();
    insertText(empty, 'READ');
    expect(empty.text, 'READ');
  });
}
