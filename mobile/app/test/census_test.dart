import 'dart:convert';

import 'package:argus_field/domain/census.dart';
import 'package:argus_field/features/census/rack_drawing.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'harness.dart';

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

Map<String, Object?> _survey({List<Map<String, Object?>> items = const [], Map<String, Object?> rack = const {}}) => {
      'uid': 'c1', 'state': 'open',
      'rack': {'photos': [], 'proposals': {}, 'values': {}, 'candidates': [], 'record': null, ...rack},
      'items': items,
    };

Map<String, Object?> _unit({Map<String, Object?> values = const {}, String? decision, String? asset}) => {
      'id': 'u1',
      'photos': [{'uid': 'ph1', 'role': 'device'}],
      'proposals': {
        'serial': {'value': 'SN-77', 'confidence': 0.95, 'evidence': 'S/N SN-77', 'grounded': true, 'source': 'photo'},
        'height_u': {'value': 2, 'confidence': 0.9, 'evidence': 'catalogue: Halberd R7 server is 2 U', 'grounded': true,
                     'source': 'catalogue'},
      },
      'values': values,
      'decision': decision,
      'asset_uid': asset,
      'duplicates': [
        {'uid': 'old-1', 'key': 'NF-HV-09', 'name': 'Hypervisor host 09', 'why': 'the same serial number SN-77',
         'strength': 'strong', 'mounted': null},
      ],
    };

Map<String, Object?> _review({bool ok = false, List<Map<String, Object?>> missing = const [],
        List<Map<String, Object?>> problems = const []}) =>
    {'ok': ok, 'missing': missing, 'problems': problems, 'changes': ok ? ['Hypervisor host 09: U10–U11 front'] : [],
     'new_records': 0};

void main() {
  test('the drawing finds two units in the same unit', () {
    CensusItem at(String id, int start, int height, [String face = 'front']) => CensusItem.parse({
          'id': id, 'decision': 'create',
          'values': {'start_u': start, 'height_u': height, 'face': face}});
    final front = RackDrawing.occupancy([at('a', 10, 2), at('b', 11, 1), at('c', 11, 1, 'rear')], 'front');
    expect(front[10]!.map((i) => i.id), ['a']);
    expect(front[11]!.map((i) => i.id), ['a', 'b']);                 // a clash
    expect(RackDrawing.occupancy([at('c', 11, 1, 'rear')], 'front'), isEmpty);
  });

  testWidgets('a unit photographed: what was read is proposed, nothing invented, a duplicate shown, the U chosen',
      (tester) async {
    final app = await start(tester);
    final s = app.server.routes;
    s['GET /v1/rack-census'] = _json([]);
    s['POST /v1/rack-census'] = _json(_survey(), 201);
    s['GET /v1/rack-census/c1'] = _json(_survey());
    s['GET /v1/rack-census/c1/review'] = _json(_review());
    await app.go('/census');
    expect(find.text('A rack not recorded yet'), findsOneWidget);
    await app.tap('census-new');
    expect(find.text('1 · THE RACK'), findsOneWidget);

    s['POST /v1/rack-census/c1/photos'] = _json({'photo': 'ph1', 'item': 'u1', 'survey': _survey(items: [_unit()])});
    s['GET /v1/rack-census/c1'] = _json(_survey(items: [_unit()]));
    await app.tap('census-unit-photo');
    expect(app.photos.taken, 1);
    // The unit's page: the serial read with its evidence and confidence, the height from the catalogue — proposed only.
    expect(find.text('Serial: SN-77'), findsOneWidget);
    expect(find.textContaining('read on the photo · “S/N SN-77” · 95% sure'), findsOneWidget);
    expect(find.textContaining('from the catalogue'), findsWidgets);
    final startU = find.descendant(of: find.byKey(const Key('census-value-start_u')), matching: find.text('not read — type it'));
    expect(startU, findsOneWidget);

    s['PUT /v1/rack-census/c1/items/u1'] = _json(_survey(items: [_unit(values: {'serial': {'value': 'SN-77', 'source': 'photo'}})]));
    await app.tap('census-use-serial');
    expect(app.server.sent('PUT', '/v1/rack-census/c1/items/u1').last['values'],
        {'serial': {'value': 'SN-77', 'source': 'photo', 'confidence': 0.95}});

    // The same serial is on a record already: shown, and "it is this one" links it.
    await tester.scrollUntilVisible(find.text('May be NF-HV-09'), 300, scrollable: find.byType(Scrollable).first);
    expect(find.text('May be NF-HV-09'), findsOneWidget);
    final thisOne = find.descendant(of: find.byKey(const Key('census-duplicate-old-1')), matching: find.text('It is this one'));
    await tester.ensureVisible(thisOne);
    await tester.pumpAndSettle();
    await tester.tap(thisOne);
    await tester.pumpAndSettle();
    expect(app.server.sent('PUT', '/v1/rack-census/c1/items/u1').last['asset_uid'], 'old-1');

    // Its lowest unit, typed by a tap on the drawing.
    await tester.scrollUntilVisible(find.byKey(const Key('census-u-10')), -300, scrollable: find.byType(Scrollable).first);
    await app.tap('census-u-10');
    expect(app.server.sent('PUT', '/v1/rack-census/c1/items/u1').last['values'], {'start_u': 10});
  });

  testWidgets('the rack is saved only when the review finds nothing; an overlap is said', (tester) async {
    final app = await start(tester);
    final s = app.server.routes;
    final done = _unit(values: {'start_u': 10, 'height_u': 2}, decision: 'link', asset: 'old-1');
    s['GET /v1/rack-census/c1'] = _json(_survey(items: [done], rack: {
      'record': {'uid': 'rk1', 'key': 'NF-RACK-R-A02', 'name': 'Rack R-A02', 'units': 42}}));
    s['GET /v1/rack-census/c1/review'] = _json(_review(problems: [
      {'code': 'overlap', 'message': 'U10 front: Hypervisor host 09 and Hypervisor host 01 both take it'}]));
    await app.go('/census/c1');
    await tester.dragUntilVisible(find.byKey(const Key('census-save')), find.byType(ListView).first, const Offset(0, -300));
    expect(find.textContaining('both take it'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('census-save'))).onPressed, isNull);

    s['GET /v1/rack-census/c1/review'] = _json(_review(ok: true));
    s['POST /v1/rack-census/c1/apply'] = _json({'ok': true, 'rack': {'uid': 'rk1', 'name': 'Rack R-A02'},
                                                'created': [], 'changes': ['Hypervisor host 09: U10–U11 front']});
    s['GET /v1/rack-census'] = _json([]);
    await app.go('/census');
    await app.go('/census/c1');
    await tester.dragUntilVisible(find.byKey(const Key('census-save')), find.byType(ListView).first, const Offset(0, -300));
    expect(find.text('Hypervisor host 09: U10–U11 front'), findsOneWidget);
    await app.tap('census-save');
    expect(app.server.requests.where((r) => r.method == 'POST' && r.url.path == '/v1/rack-census/c1/apply'), hasLength(1));
  });

  testWidgets('a survey left half-way is listed to be resumed', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/rack-census'] = _json([
      {'uid': 'c9', 'rack': 'Rack B07', 'items': 3, 'updated_at': '2026-11-14T10:00:00Z'}]);
    await app.go('/census');
    expect(find.text('Rack B07'), findsOneWidget);
    expect(find.text('3 units so far'), findsOneWidget);
  });
  testWidgets('the units seen on the photo of the whole rack are taken at once, the rack recorded too', (tester) async {
    final app = await start(tester);
    final s = app.server.routes;
    s['GET /v1/rack-census/c1'] = _json(_survey(rack: {
      'proposals': {'name': {'value': 'BPM-R3', 'confidence': 0.8, 'grounded': true, 'source': 'rack photo',
                             'evidence': 'BPM-R3 on the top panel'}},
      'seen': {'photo': 'ph0', 'face': 'front', 'taken': [], 'units': [
        {'kind': 'Server', 'type': 'Server', 'label': 'BPM-1', 'height_u': 1, 'gap_above_u': 0, 'confidence': 0.8},
        {'kind': 'Server', 'type': 'Server', 'label': 'BPM-2', 'height_u': 1, 'gap_above_u': 2, 'confidence': 0.8},
        {'kind': 'Oscilloscope', 'height_u': 4, 'gap_above_u': 1},
      ]}}));
    s['GET /v1/rack-census/c1/review'] = _json(_review());
    s['POST /v1/rack-census/c1/seen'] = _json(_survey());
    await app.go('/census/c1');
    expect(find.text('2. BPM-2'), findsOneWidget);
    expect(find.textContaining('Oscilloscope (not a type here)'), findsOneWidget);
    await app.tap('census-seen-2');                                     // left out
    await app.type('census-seen-top', '40');
    await app.tap('census-seen-take');
    final sent = app.server.requests.where((r) => r.method == 'POST' && r.url.path == '/v1/rack-census/c1/seen');
    expect(sent, hasLength(1));
    expect(jsonDecode(sent.single.body), {'units': [0, 1], 'top_u': 40, 'use': true, 'rack': true});
  });

  testWidgets('a rack survey starts from the Assets menu', (tester) async {
    final app = await start(tester);
    app.server.routes['GET /v1/rack-census'] = _json([]);
    await app.go('/assets');
    await app.tap('assets-menu');
    await app.tap('assets-census');
    expect(find.byKey(const Key('census-new')), findsOneWidget);
  });
}
