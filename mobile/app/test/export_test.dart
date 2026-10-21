import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

void main() {
  for (final (route, path) in [
    ('/asset/$ionPumpUid', '/v1/assets/$ionPumpUid'),
    ('/document/$documentUid', '/v1/documents/$documentUid'),
    ('/ticket/$ticketUid', '/v1/issues/$ticketUid'),
  ]) {
    testWidgets('$route is exported as a PDF or as Markdown from its page', (tester) async {
      final app = await start(tester);
      await app.go(route);
      await app.tap('export-menu');
      for (final label in ['Open as PDF', 'Print', 'Send PDF', 'Send Markdown']) {
        expect(find.text(label), findsOneWidget);
      }
      await tester.tap(find.text('Send Markdown'));
      await tester.pumpAndSettle();
      expect(app.server.requests.any((r) => r.url.path == '$path/markdown'), isTrue);

      await app.tap('export-menu');
      await tester.tap(find.text('Open as PDF'));
      await tester.pumpAndSettle();
      expect(app.server.requests.any((r) => r.url.path == '$path/pdf'), isTrue);
    });
  }
}
