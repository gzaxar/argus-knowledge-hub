import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fake_server.dart';
import 'harness.dart';

http.Response _json(Object body) => http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json'});

// A 1×1 white PNG: the plan's picture in a test (its size is the plan's own, 1000 × 500).
final _png = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=');

const _plan = {'uid': 'p1', 'name': 'Ground floor plan', 'width_px': 1000, 'height_px': 500};

Map<String, Object?> _indoors({bool onPlan = true}) => {
      'uid': ionPumpUid,
      'placement': {
        'uid': 'ip1', 'place': {'uid': 'room-12', 'key': 'ROOM-12', 'name': 'Room 12', 'type': 'Area'},
        'level': {'uid': 'l0', 'name': 'Ground floor', 'ordinal': 0},
        'plan': onPlan ? _plan : null, 'x': onPlan ? 250 : null, 'y': onPlan ? 125 : null, 'state': 'confirmed'},
      'in': [
        {'uid': 'room-12', 'key': 'ROOM-12', 'name': 'Room 12', 'type': 'Area'},
        {'uid': 'hall-b1', 'key': 'HALL-B1', 'name': 'Hall B1', 'type': 'Area'},
        {'uid': 'bld-b', 'key': 'BLD-B', 'name': 'Building B', 'type': 'Building'},
      ],
      'contents': [], 'history': [],
    };

void _plans(Running app) {
  app.server.routes['GET /v1/plans/p1'] = _json({..._plan, 'mime_type': 'image/png', 'corners': [[1, 2]],
    'place': {'uid': 'bld-b', 'name': 'Building B'}, 'level': {'uid': 'l0', 'name': 'Ground floor', 'ordinal': 0},
    'placed': [{'uid': ionPumpUid, 'name': 'Ion pump gun area 2', 'x': 250, 'y': 125}]});
  app.server.routes['GET /v1/plans/p1/image'] = http.Response.bytes(_png, 200, headers: {'content-type': 'image/png'});
  app.server.routes['PUT /v1/assets/$ionPumpUid/indoors'] = _json({'uid': 'ip2', 'state': 'confirmed'});
}

void main() {
  testWidgets('an equipment page says which room it is in, shows it on the plan, and a tap moves it there',
      (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/assets/$ionPumpUid/indoors'] = _json(_indoors());
    _plans(app);
    await app.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(find.byKey(const Key('asset-indoors')), find.byType(ListView).first, const Offset(0, -300));
    expect(find.text('In Room 12, Ground floor'), findsOneWidget);
    expect(find.text('which is in Hall B1 → Building B'), findsOneWidget);

    await app.tap('asset-show-plan');
    expect(find.text('Ground floor plan'), findsWidgets);
    expect(find.byKey(Key('plan-pin-$ionPumpUid')), findsOneWidget);
    await tester.tapAt(tester.getCenter(find.byKey(const Key('plan-surface'))));
    await tester.pumpAndSettle();
    expect(find.text('Place it here?'), findsOneWidget);
    await app.tap('plan-place-confirm');
    final put = app.server.sent('PUT', '/v1/assets/$ionPumpUid/indoors').single;
    expect(put['plan_uid'], 'p1');
    expect((put['x'] as num).round(), 500, reason: 'the middle of the plan, in its own pixels');
    expect((put['y'] as num).round(), 250);
    expect(put['place_uid'], 'room-12', reason: 'it stays in its room');
  });

  testWidgets('a unit in a room but not on a plan is offered the plans of its building', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/assets/$ionPumpUid/indoors'] = _json(_indoors(onPlan: false));
    for (final place in ['room-12', 'hall-b1']) {
      app.server.routes['GET /v1/assets/$place/levels'] = _json({'levels': [], 'plans': []});
    }
    app.server.routes['GET /v1/assets/bld-b/levels'] = _json({'levels': [], 'plans': [
      {..._plan, 'place': {'uid': 'bld-b', 'name': 'Building B'}, 'level': {'uid': 'l0', 'name': 'Ground floor'}},
    ]});
    _plans(app);
    await app.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(find.byKey(const Key('asset-pick-plan')), find.byType(ListView).first, const Offset(0, -300));
    await app.tap('asset-pick-plan');
    expect(find.text('Building B · Ground floor'), findsOneWidget);
    await app.tap('plan-choice-p1');
    expect(find.text('Tap where it is to place it there.'), findsOneWidget);
  });
}
