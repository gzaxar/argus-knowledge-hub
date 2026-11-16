import 'dart:convert';

import 'package:argus_field/features/capture/media_source.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

/// What was uploaded: its declared type, and where it was attached.
({String type, String attachedTo}) _sent(Running r) {
  final create = r.server.sent('POST', '/v1/uploads').last;
  final attach = r.server.requests.lastWhere((q) => q.url.path.contains('/attach/'));
  return (type: create['content_type'] as String, attachedTo: attach.url.path.split('/attach/').last);
}

void main() {
  testWidgets('a video is attached to a ticket', (tester) async {
    final r = await start(tester);
    await r.go('/ticket/$ticketUid');
    await tester.dragUntilVisible(
        find.byKey(const Key('ticket-add-photo')), find.byType(Scrollable).first, const Offset(0, -300));
    await r.tap('ticket-add-photo');
    await r.tap('attach-video');
    expect(_sent(r), (type: 'video/mp4', attachedTo: 'ticket/$ticketUid'));
    expect(find.text('Video added.'), findsOneWidget);
  });

  testWidgets('a recorded note and where I am are attached to equipment', (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(
        find.byKey(const Key('asset-attach')), find.byKey(const Key('asset-body-list')), const Offset(0, -300));

    await r.tap('asset-attach');
    await r.tap('attach-audio');
    expect(find.textContaining('Recording'), findsOneWidget);
    await r.tap('record-stop');
    expect(_sent(r), (type: 'audio/mp4', attachedTo: 'asset/$ionPumpUid'));

    await r.tap('asset-attach');
    await r.tap('attach-place');
    expect(_sent(r), (type: 'application/geo+json', attachedTo: 'asset/$ionPumpUid'));
    final pieces = r.server.requests.where((q) => q.method == 'PUT' && q.url.path.startsWith('/v1/uploads/')).last;
    final place = readPlace(pieces.bodyBytes)!;
    expect((place.lat, place.lon, place.accuracy), (41.8219, 12.6826, 4.0));
  });

  testWidgets("a photo is added to a document's draft, not to what was approved", (tester) async {
    final r = await start(tester);
    await r.go('/document/$draftUid');
    await tester.dragUntilVisible(
        find.byKey(const Key('doc-attach')), find.byType(Scrollable).first, const Offset(0, -300));
    await r.tap('doc-attach');
    await r.tap('attach-photo');
    expect(_sent(r).attachedTo, 'document/$draftUid/revision/$draftUid-r1');
  });

  testWidgets("a photo already on the phone can be attached too", (tester) async {
    final r = await start(tester);
    await r.go('/document/$draftUid');
    await tester.dragUntilVisible(
        find.byKey(const Key('doc-attach')), find.byType(Scrollable).first, const Offset(0, -300));
    await r.tap('doc-attach');
    await r.tap('attach-gallery');
    expect(r.photos.lastFromGallery, isTrue);
    expect(_sent(r).attachedTo, 'document/$draftUid/revision/$draftUid-r1');
  });

  testWidgets('a published document without a draft offers no attaching', (tester) async {
    final r = await start(tester);
    await r.go('/document/$documentUid');
    expect(find.byKey(const Key('doc-attach')), findsNothing);
  });

  test('a place is kept as a GeoJSON point, longitude first', () {
    final f = placeFile(41.8, 12.6, accuracy: 5);
    final json = jsonDecode(utf8.decode(f.bytes)) as Map;
    expect((json['geometry'] as Map)['coordinates'], [12.6, 41.8]);
    expect(f.mimeType, 'application/geo+json');
  });
}
