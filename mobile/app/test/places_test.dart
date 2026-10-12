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
