import 'dart:convert';

import 'package:argus_field/domain/models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'harness.dart';

const _defs = [
  AttributeDef(key: 'vendor', name: 'Vendor', type: 'string'),
  AttributeDef(key: 'vendor_ref', name: 'Supplied by', type: 'reference', referenceType: 'Vendor', referenceSchemaUid: 's'),
  AttributeDef(key: 'model_code', name: 'Model code', type: 'string'),
];

void main() {
  List<String> names(List<AttributeDef> d) => [for (final x in d) '${x.key}:${x.name}'];

  test('a form offers only the reference, called Vendor, and asks an older record for it', () {
    expect(names(oneVendorField(_defs, {'vendor': 'Keysight', 'vendor_ref': 'u'}, form: true)),
        ['vendor_ref:Vendor', 'model_code:Model code']);
    expect(oneVendorField(_defs, {'vendor': 'Keysight'}, form: true).first.description, contains('"Keysight" is not linked'));
  });

  test('a page shows the one value: the reference, or the text not linked yet', () {
    expect(names(oneVendorField(_defs, {'vendor': 'Keysight', 'vendor_ref': 'u'}, form: false)).first, 'vendor_ref:Vendor');
    expect(names(oneVendorField(_defs, {'vendor': 'Keysight'}, form: false)), ['vendor:Vendor', 'model_code:Model code']);
  });

  test('other types are left alone', () {
    final others = [_defs[0], _defs[2]];
    expect(identical(oneVendorField(others, const {}, form: true), others), isTrue);
  });

  testWidgets('a model shows one Vendor, and one not listed is added from the form and saved as the reference', (tester) async {
    final r = await start(tester);
    await r.go('/asset/pm-linked');
    await tester.scrollUntilVisible(find.text('Model code'), 300,
        scrollable: find.descendant(of: find.byKey(const Key('asset-body-list')), matching: find.byType(Scrollable)).first);
    expect(find.text('Supplied by'), findsNothing);
    expect(find.text('Vendor'), findsOneWidget);
    await tester.drag(find.byKey(const Key('asset-body-list')), const Offset(0, 5000));
    await tester.pumpAndSettle();
    await r.tap('asset-edit');
    expect(find.text('Supplied by'), findsNothing);
    expect(find.byKey(const Key('attr-vendor-0')), findsNothing, reason: 'the name is not typed: it follows the record');
    expect(find.byKey(const Key('attr-vendor_ref-0')), findsOneWidget);

    await r.tap('vendor-add');
    await tester.enterText(find.byKey(const Key('vendor-add-name')), 'Acme Instruments');
    await r.tap('vendor-add-confirm');
    await r.tap('asset-edit-save');

    final put = r.server.requests.lastWhere((q) => q.method == 'PUT' && q.url.path == '/v1/assets/pm-linked');
    expect((jsonDecode(put.body)['attributes'] as Map)['vendor_ref'], 'vendor-new');
  });
}
