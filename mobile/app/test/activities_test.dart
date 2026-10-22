import 'dart:convert';

import 'package:argus_field/app/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'harness.dart';

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

final _now = DateTime.now();
String _at(DateTime d) => d.toUtc().toIso8601String();

Map<String, Object?> _item(String id, String title, String status,
        {DateTime? planned, DateTime? end, String? series, bool overdue = false}) =>
    {
      'id': id, 'uid': series == null ? id : null, 'title': title, 'status': status, 'visibility': 'workspace',
      'all_day': false, 'planned_start': planned == null ? null : _at(planned), 'actual_end': end == null ? null : _at(end),
      'actual_start': status == 'in_progress' ? _at(_now.subtract(const Duration(hours: 1))) : null,
      'series_uid': series, 'recurrence': series == null ? null : 'every Monday at 09:00', 'overdue': overdue,
      'may_change': true, 'created_at': _at(_now),
    };

Map<String, Object?> _page(List<Map<String, Object?>> items, [Map<String, int> counts = const {}]) =>
    {'items': items, 'counts': {'planned': 0, 'in_progress': 0, 'completed': 0, 'overdue': 0, 'total': items.length, ...counts},
      'total': items.length, 'next_offset': null};

Future<Running> _open(WidgetTester tester) async {
  final app = await start(tester, overrides: [deviceTimezoneProvider.overrideWith((_) async => 'Europe/Rome')]);
  app.server.routes['GET /v1/activities'] = _json(_page([
    _item('a1', 'Inspection of the linac', 'in_progress'),
    _item('s1@2026-10-26T09:00', 'Check the cooling', 'planned', planned: _now.add(const Duration(hours: 2)), series: 's1'),
  ], {'in_progress': 1, 'planned': 1}));
  await app.go('/activities');
  await tester.pumpAndSettle();
  return app;
}

List<Uri> _listings(Running app) =>
    app.server.requests.where((r) => r.method == 'GET' && r.url.path == '/v1/activities').map((r) => r.url).toList();

void main() {
  testWidgets('today: my activities, and one is done from the list in a tap, sent once', (tester) async {
    final app = await _open(tester);
    expect(_listings(app).first.queryParameters, containsPair('view', 'today'));
    expect(_listings(app).first.queryParameters, containsPair('tz', 'Europe/Rome'));
    expect(find.text('Inspection of the linac'), findsOneWidget);
    expect(find.textContaining('every Monday at 09:00'), findsOneWidget, reason: 'an occurrence says it repeats');
    app.server.routes['POST /v1/activities/a1/complete'] = _json(_item('a1', 'Inspection of the linac', 'completed'));
    await app.tap('activity-complete-a1');
    final sent = app.server.requests.where((r) => r.url.path == '/v1/activities/a1/complete').toList();
    expect(sent, hasLength(1));
    expect(sent.single.headers['Idempotency-Key'], startsWith('activity-action:'));
  });

  testWidgets('the workspace view: a range by planned or done date, counts, filters, calendar or list', (tester) async {
    final app = await _open(tester);
    await app.tap('activities-workspace');
    final ranged = _listings(app).last.queryParameters;
    expect(ranged.containsKey('from') && ranged.containsKey('to'), isTrue);
    expect(ranged['basis'], 'planned');
    expect(find.byKey(const Key('activities-calendar')), findsOneWidget);
    expect(find.text('Under way 1'), findsOneWidget, reason: 'counts beside the filters');

    await tester.tap(find.text('Done on'));
    await tester.pumpAndSettle();
    expect(_listings(app).last.queryParameters['basis'], 'actual');
    await app.tap('activities-filter-recurring');
    expect(_listings(app).last.queryParameters['recurring'], 'true');
    await app.tap('activities-filter-completed');
    expect(_listings(app).last.queryParameters['status'], 'completed');

    await tester.tap(find.text('List'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('activities-workspace-list')), findsOneWidget);
  });

  testWidgets('an occurrence is changed for itself, this and the future ones, or the whole series', (tester) async {
    final app = await _open(tester);
    const id = 's1@2026-10-26T09:00';
    app.server.routes['GET /v1/activities/$id'] =
        _json(_item(id, 'Check the cooling', 'planned', planned: _now.add(const Duration(hours: 2)), series: 's1'));
    app.server.routes['PATCH /v1/activities/$id'] = _json(_item('s2', 'Check the cooling (new pump)', 'planned', series: 's2'));
    app.server.routes['GET /v1/activities/s2'] = _json(_item('s2', 'Check the cooling (new pump)', 'planned', series: 's2'));
    await app.tap('activity-$id');
    await tester.dragUntilVisible(find.byKey(const Key('activity-skip')), find.byKey(const Key('activity-body')),
        const Offset(0, -200));
    expect(find.byKey(const Key('activity-skip')), findsOneWidget, reason: 'one occurrence can be skipped');
    await app.tap('activity-edit');
    await tester.enterText(find.byKey(const Key('activity-edit-title')), 'Check the cooling (new pump)');
    await tester.tap(find.text('This and future'));
    await tester.pumpAndSettle();
    await app.tap('activity-edit-save');
    final patch = app.server.requests.lastWhere((r) => r.method == 'PATCH');
    expect(patch.url.queryParameters['scope'], 'future');
    expect(jsonDecode(patch.body), {'title': 'Check the cooling (new pump)'});
    expect(find.text('Check the cooling (new pump)'), findsOneWidget);
  });

  testWidgets('capture is on the home screen', (tester) async {
    final app = await start(tester, overrides: [deviceTimezoneProvider.overrideWith((_) async => 'Europe/Rome')]);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('home-capture')), findsOneWidget);
    await app.tap('home-capture');
    expect(find.text('Capture by voice'), findsWidgets);
    expect(find.textContaining('only the text is sent to ARGUS'), findsOneWidget);
  });
}
