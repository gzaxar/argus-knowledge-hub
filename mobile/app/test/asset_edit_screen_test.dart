import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

void main() {
  testWidgets('editing respects the type: a number field only takes a number, a photo can fill a text field, '
      'and saving sends the version read as If-Match', (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await r.tap('asset-edit'); // a real push, so Save's pop back to the record has somewhere to go

    expect(find.text('Pumping speed (l/s)'), findsOneWidget);
    expect(find.widgetWithText(TextField, '120.5'), findsOneWidget, reason: 'the stored value is shown, pre-filled');

    // An enumeration is stored and matched by its label ("In service"), not its id ("in_service") — the
    // two commonly differ. The dropdown must show the record's actual value without crashing, and change
    // to another option's label when picked.
    expect(find.text('In service'), findsOneWidget);
    await tester.tap(find.byKey(const Key('attr-status')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Planned').last);
    await tester.pumpAndSettle();

    // Typing letters into a number field and trying to save is refused, with a reason — not silently coerced.
    await r.type('attr-pumping_speed-0', 'not a number');
    await r.tap('asset-edit-save');
    expect(find.textContaining('Not a number'), findsOneWidget);
    await r.type('attr-pumping_speed-0', '131.2');

    // A photo of the nameplate proposes a value for one field; nothing is written until it is taken.
    await r.tap('attr-manufacturer-0-scan');
    expect(r.photos.taken, 1);
    expect(find.text('manufacturer: Agilent'), findsOneWidget, reason: 'proposed, not yet written to the field');
    await r.tap('take-attributes.manufacturer');
    expect(find.widgetWithText(TextField, 'Agilent'), findsOneWidget);

    await r.tap('asset-edit-save');

    final put = r.server.requests.lastWhere((q) => q.method == 'PUT' && q.url.path == '/v1/assets/$ionPumpUid');
    expect(put.headers['If-Match'], '"5"', reason: 'the version read with the record, so a stale edit is refused');
    final sent = jsonDecode(put.body)['attributes'] as Map;
    expect(sent['pumping_speed'], 131.2);
    expect(sent['manufacturer'], 'Agilent');
    expect(sent['nominal_voltage'], 24); // untouched fields travel unchanged
    expect(sent['status'], 'Planned', reason: 'the label is sent, matching what the web form writes');
    expect(find.byKey(const Key('asset-edit-save')), findsNothing, reason: 'saving returns to the record, not stays on the form');
  });

  testWidgets('a product model is searched as on its label, the catalogue\'s models first, not a raw uid '
      'text field', (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await r.tap('asset-edit');
    await tester.drag(find.byKey(const Key('asset-edit-list')), const Offset(0, -2000));
    await tester.pumpAndSettle();

    // The record's current model is shown by name, not as a bare uid.
    expect(find.text('PM-ACE2 · Ace 2 a2A1920-51gmBAS'), findsOneWidget);
    expect(r.server.requests.where((q) => q.url.queryParameters['schema_uid']?.endsWith('product-model') ?? false),
        isEmpty, reason: 'the models are searched, not all downloaded to the phone');

    await tester.enterText(find.byKey(const Key('model-search')), 'turbo');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('model-hit-pm-turbo350')));
    await tester.pumpAndSettle();

    await tester.drag(find.byKey(const Key('asset-edit-list')), const Offset(0, -500));
    await tester.pumpAndSettle();
    await r.tap('asset-edit-save');

    final put = r.server.requests.lastWhere((q) => q.method == 'PUT' && q.url.path == '/v1/assets/$ionPumpUid');
    final sent = jsonDecode(put.body)['attributes'] as Map;
    expect(sent['product_model'], 'pm-turbo350');
  });

  testWidgets('a library model (NetBox) is added to the catalogue when it is chosen', (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await r.tap('asset-edit');
    await tester.drag(find.byKey(const Key('asset-edit-list')), const Offset(0, -2000));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('model-search')), 'c9200');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(find.text('NetBox · add'), findsOneWidget);
    await tester.tap(find.byKey(const Key('model-lib-cisco/c9200-24t')));
    await tester.pumpAndSettle();
    final install = r.server.requests.lastWhere((q) => q.url.path == '/v1/catalogue/collections/models/install-one');
    expect(jsonDecode(install.body), {'catalogue_id': 'cisco/c9200-24t'});

    await tester.drag(find.byKey(const Key('asset-edit-list')), const Offset(0, -500));
    await tester.pumpAndSettle();
    await r.tap('asset-edit-save');
    final put = r.server.requests.lastWhere((q) => q.method == 'PUT' && q.url.path == '/v1/assets/$ionPumpUid');
    expect((jsonDecode(put.body)['attributes'] as Map)['product_model'], 'pm-c9200');
  });

  testWidgets('a field kind the field app cannot yet edit (its type needs the web\'s picker) is named, not '
      'offered as a text box that could never hold a valid value', (tester) async {
    final r = await start(tester);
    await r.go('/asset/$ionPumpUid');
    await r.tap('asset-edit');
    await tester.drag(find.byKey(const Key('asset-edit-list')), const Offset(0, -2000));
    await tester.pumpAndSettle();
    expect(find.text('EDITED ON THE WEB'), findsOneWidget);
    expect(find.text('Responsible'), findsOneWidget);
    expect(find.byKey(const Key('attr-responsible-0')), findsNothing);
  });
}
