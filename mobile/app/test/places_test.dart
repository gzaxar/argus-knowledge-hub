import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

void main() {
  testWidgets('an equipment page says where it is, and seeing it elsewhere sends it for review, not moving it',
      (tester) async {
    final app = await start(tester);
    await app.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(find.byKey(const Key('asset-location')), find.byType(ListView).first,
        const Offset(0, -300));
    expect(find.text('41.821700, 12.672600 (±3 m)'), findsOneWidget);
    await tester.dragUntilVisible(find.byKey(const Key('asset-observe-location')), find.byType(ListView).first,
        const Offset(0, -200));
    await app.tap('asset-observe-location');
    expect(app.server.observations.single['latitude'], 41.8219);
    expect(app.server.observations.single['accuracy_m'], 4);
    expect(find.textContaining('Sent for review: 829 m'), findsOneWidget);
    expect(find.textContaining('waiting for review'), findsOneWidget);
  });

  Future<void> toLocation(WidgetTester tester, String key) async {
    await tester.dragUntilVisible(find.byKey(Key(key)), find.byType(ListView).first, const Offset(0, -200));
    await tester.pumpAndSettle();
  }

  testWidgets('without the right to edit, a position cannot be set: only said', (tester) async {
    final app = await start(tester);
    app.server.noLocationFor.add(ionPumpUid);
    await app.go('/asset/$ionPumpUid');
    await toLocation(tester, 'asset-observe-location');
    expect(find.byKey(const Key('asset-set-here')), findsNothing);
    expect(find.byKey(const Key('asset-choose-on-map')), findsNothing);
  });

  testWidgets('who may edit sets the position where the phone is, once confirmed, with its accuracy', (tester) async {
    final app = await start(tester);
    app.server.maySetLocation = true;
    app.server.noLocationFor.add(ionPumpUid);
    await app.go('/asset/$ionPumpUid');
    await toLocation(tester, 'asset-set-here');
    expect(find.byKey(const Key('asset-observe-location')), findsNothing, reason: 'no position yet: nothing to check it against');
    await app.tap('asset-set-here');
    expect(find.textContaining('41.821900, 12.682600 (±4 m)'), findsOneWidget);
    expect(app.server.positionsSet, isEmpty, reason: 'not until confirmed');
    await app.tap('asset-set-here-confirm');
    expect(app.server.positionsSet.single,
        {'latitude': 41.8219, 'longitude': 12.6826, 'accuracy_m': 4, 'source': 'field'});
    expect(app.server.observations, isEmpty, reason: 'set, not sent for review');
    expect(find.text('Position set.'), findsOneWidget);
  });

  testWidgets('cancelling the confirmation sets nothing', (tester) async {
    final app = await start(tester);
    app.server.maySetLocation = true;
    await app.go('/asset/$ionPumpUid');
    await toLocation(tester, 'asset-set-here');
    await app.tap('asset-set-here');
    expect(find.textContaining('stays in its history'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(app.server.positionsSet, isEmpty);
  });

  testWidgets('a point chosen on the map is the crosshair\'s, by hand, with no accuracy claimed', (tester) async {
    final app = await start(tester);
    app.server.maySetLocation = true;
    await app.go('/asset/$ionPumpUid');
    await toLocation(tester, 'asset-choose-on-map');
    await app.tap('asset-choose-on-map');
    expect(find.byKey(const Key('pick-crosshair')), findsOneWidget);
    await app.tap('pick-use');
    final sent = app.server.positionsSet.single;
    expect((sent['latitude'] as num).toDouble(), closeTo(41.8217, 1e-6), reason: 'it opens on where the record is');
    expect((sent['longitude'] as num).toDouble(), closeTo(12.6726, 1e-6));
    expect(sent['source'], 'manual');
    expect(sent.containsKey('accuracy_m'), isFalse);
    expect(find.byKey(const Key('pick-map')), findsNothing, reason: 'back on the record');
  });

  testWidgets('near me lists what has a location around the phone, nearest first', (tester) async {
    final app = await start(tester);
    await app.go('/nearby');
    expect(find.text('Ion pump 7'), findsOneWidget);
    expect(find.text('12 m'), findsOneWidget);
    expect(app.server.requests.any((r) => r.url.path == '/v1/map/nearby' && num.tryParse(r.url.queryParameters['radius_m'] ?? '') == 200),
        isTrue);
  });

  testWidgets('an observation waiting for review can be accepted', (tester) async {
    final app = await start(tester);
    app.server.observations.add({'id': 7, 'latitude': 41.83, 'longitude': 12.68, 'accuracy_m': 6, 'status': 'pending',
      'distance_m': 1100.0});
    await app.go('/location-reviews');
    expect(find.textContaining('1100 m from its approved location'), findsOneWidget);
    await app.tap('location-accept-7');
    expect(app.server.observations.single['status'], 'accepted');
    expect(find.text('Nothing to review.'), findsOneWidget);
  });
}
