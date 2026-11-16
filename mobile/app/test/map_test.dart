import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fake_server.dart';
import 'harness.dart';
import 'package:argus_field/domain/models.dart';
import 'package:argus_field/features/places/map_screen.dart';

http.Response _json(Object body) => http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json'});

Map<String, Object?> _feature(String uid, String name, String role, Map<String, Object?> geometry, {String layer = 'places'}) =>
    {
      'type': 'Feature', 'id': role == 'position' ? uid : '$uid:$role', 'geometry': geometry,
      'properties': {'uid': uid, 'key': uid.toUpperCase(), 'name': name, 'type': 'Area', 'workspace_id': workspaceId,
        'status': 'Active', 'map_layer': layer, 'role': role, 'base_m': role == 'outline' ? 0 : null,
        'top_m': role == 'outline' ? 6 : null},
    };

const _hall = {'type': 'Polygon', 'coordinates': [[[12.6720, 41.8212], [12.6730, 41.8212], [12.6730, 41.8222],
  [12.6720, 41.8222], [12.6720, 41.8212]]]};
const _cable = {'type': 'LineString', 'coordinates': [[12.6715, 41.8217], [12.6735, 41.8217]]};

void main() {
  testWidgets('the map draws positions, routes and outlines in view, and a dot opens its record', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/map/features'] = _json({'type': 'FeatureCollection', 'features': [
      _feature('hall-1', 'Hall BTF', 'outline', _hall),
      _feature('cable-1', 'Power cable 3', 'route', _cable, layer: 'equipment'),
      _feature(ionPumpUid, 'Ion pump 7', 'position', {'type': 'Point', 'coordinates': [12.6726, 41.8217]},
          layer: 'equipment'),
    ]});
    await app.go('/map');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    final asked = app.server.requests.lastWhere((r) => r.url.path == '/v1/map/features');
    expect(asked.url.queryParameters['bbox']!.split(','), hasLength(4));
    expect(find.text('3 in view'), findsOneWidget);
    final polygons = tester.widget<PolygonLayer>(find.byWidgetPredicate((w) => w is PolygonLayer).first).polygons;
    expect(polygons.single.points, hasLength(5), reason: 'the hall, as an area');
    final lines = tester.widget<PolylineLayer>(find.byWidgetPredicate((w) => w is PolylineLayer).first).polylines;
    expect(lines.single.points.first.longitude, 12.6715, reason: 'the cable, as a line');
    final dots = tester.widget<MarkerLayer>(find.byType(MarkerLayer).first).markers;
    expect(dots.single.point.latitude, 41.8217);

    await tester.tap(find.descendant(of: find.byType(MarkerLayer).first, matching: find.byType(GestureDetector)).first);
    await tester.pumpAndSettle();
    expect(find.byKey(Key('map-feature-$ionPumpUid')), findsOneWidget);
    await app.tap('map-feature-$ionPumpUid');
    expect(find.text('Ion pump gun area 2'), findsWidgets, reason: 'its record opened');
  });

  testWidgets("an equipment page shows its route and outline on a small map, with their measures", (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/assets/$ionPumpUid/location'] = _json({
      'uid': ionPumpUid, 'locatable': true, 'map_layer': 'places', 'hidden': false, 'location': null,
      'route': {'uid': 'r1', 'role': 'route', 'geometry': _cable, 'length_m': 166.1, 'source': 'manual',
        'state': 'confirmed'},
      'outline': {'uid': 'o1', 'role': 'outline', 'geometry': _hall, 'area_m2': 9264.4, 'base_m': 0, 'top_m': 6.5,
        'source': 'manual', 'state': 'confirmed'},
      'history': [], 'observations': []});
    await app.go('/asset/$ionPumpUid');
    await tester.dragUntilVisible(find.byKey(const Key('asset-outline')), find.byType(ListView).first,
        const Offset(0, -300));
    expect(find.byKey(const Key('asset-location-map')), findsOneWidget);
    expect(find.text('Route, 166.1 m long'), findsOneWidget);
    expect(find.text('Outline, 9264 m², from 0.0 m to 6.5 m'), findsOneWidget);
    await tester.dragUntilVisible(find.byKey(const Key('asset-open-map')), find.byType(ListView).first,
        const Offset(0, -200));
    app.server.routes['GET /v1/map/features'] = _json({'type': 'FeatureCollection', 'features': []});
    await app.tap('asset-open-map');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('map')), findsOneWidget);
    expect(find.text('0 in view'), findsOneWidget);
  });

  testWidgets('a tapped building lists its floor plans, and one opens', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/map/features'] = _json({'type': 'FeatureCollection', 'features': [
      _feature('bld-b', 'Building B', 'position', {'type': 'Point', 'coordinates': [12.6726, 41.8217]}),
    ]});
    app.server.routes['GET /v1/assets/bld-b/levels'] = _json({'levels': [], 'plans': [
      {'uid': 'p0', 'name': 'B ground floor', 'width_px': 100, 'height_px': 50, 'place': {'uid': 'bld-b', 'name': 'Building B'},
        'level': {'uid': 'l0', 'name': 'Ground floor', 'ordinal': 0}},
      {'uid': 'p1', 'name': 'B first floor', 'width_px': 100, 'height_px': 50, 'place': {'uid': 'bld-b', 'name': 'Building B'},
        'level': {'uid': 'l1', 'name': 'First floor', 'ordinal': 1}},
    ]});
    await app.go('/map');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byType(MarkerLayer).first, matching: find.byType(GestureDetector)).first);
    await tester.pumpAndSettle();
    expect(find.text('Inside: 2 floor plans'), findsOneWidget);
    expect(find.byKey(const Key('map-inside-p0')), findsOneWidget);
    expect(find.text('First floor'), findsOneWidget);
  });

  testWidgets('search finds a located record and goes to it; a layer turned off is not drawn', (tester) async {
    final app = await start(tester);
    final all = {'type': 'FeatureCollection', 'features': [
      _feature('hall-1', 'Hall BTF', 'outline', _hall),
      _feature(ionPumpUid, 'Ion pump 7', 'position', {'type': 'Point', 'coordinates': [12.6726, 41.8217]},
          layer: 'equipment'),
    ]};
    app.server.routes['GET /v1/map/features'] = _json(all);
    app.server.routes['GET /v1/map/extent'] = _json({'bbox': [12.672, 41.8212, 12.673, 41.8222]});
    app.server.routes['GET /v1/map/layers'] = _json([
      {'id': 'equipment', 'name': 'Equipment', 'package': 'core', 'count': 1},
      {'id': 'places', 'name': 'Places', 'package': 'core', 'count': 1},
      {'id': 'cryogenics', 'name': 'Cryogenics', 'package': 'vacuum-cryo', 'count': 0}]);
    await app.go('/map');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.text('2 in view'), findsOneWidget);

    await app.tap('map-find');
    await tester.enterText(find.byKey(const Key('map-find-text')), 'pump');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('map-found-hall-1')), findsNothing);
    await app.tap('map-found-$ionPumpUid');
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.radio_button_unchecked), findsOneWidget, reason: 'the pump, outlined in orange');

    await app.tap('map-layers');
    expect(find.byKey(const Key('map-layer-cryogenics')), findsNothing, reason: 'nothing on it here');
    await app.tap('map-layer-equipment');
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.byKey(const Key('map-layer-equipment')))).pop();
    await tester.pumpAndSettle();
    expect(find.text('1 in view'), findsOneWidget, reason: 'the equipment layer is off');
  });

  test('a search matches every word typed, once a record, names that start with it first', () {
    MapFeatureItem item(String uid, String name, String key, String type) => MapFeatureItem(
        target: LinkTarget(kind: RecordKind.asset, uid: uid, title: name, key: key, subtitle: type),
        shape: const PlaceShape(role: 'position'));
    final all = [item('s', 'Shielded accelerator hall', 'VL-HALL', 'Building'),
                 item('b', 'Accelerator Building', 'VL-BLD-ACC', 'Building'),
                 item('b', 'Accelerator Building', 'VL-BLD-ACC', 'Building'), item('r', 'Rack A12-1', 'VL-RK-A12-1', 'Rack')];
    expect(findOnMap(all, 'accel').map((f) => f.target.uid), ['b', 's']);
    expect(findOnMap(all, 'vl-rk').map((f) => f.target.uid), ['r']);
    expect(findOnMap(all, ' '), isEmpty);
  });
}
