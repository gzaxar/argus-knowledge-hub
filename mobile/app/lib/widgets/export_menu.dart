import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:printing/printing.dart';
import 'package:share_plus/share_plus.dart';

import '../app/providers.dart';
import '../core/problem.dart';

/// What can be exported, and the API path it is exported from.
enum ExportKind {
  document('documents'),
  asset('assets'),
  ticket('issues');

  const ExportKind(this.path);
  final String path;
}

enum _Action { open, print, sharePdf, shareMarkdown }

/// Export in a record's app bar: the record as a PDF (open it, print it, send it on) or as a Markdown file.
///
/// The same files as Export on the web: the PDF is laid out by ARGUS on A4 with the record's pictures, the
/// Markdown is the text it is made from. [name] names the files (a document's code, an asset's key).
class ExportMenu extends ConsumerWidget {
  const ExportMenu({
    super.key,
    required this.kind,
    required this.uid,
    required this.name,
  });

  final ExportKind kind;
  final String uid;
  final String name;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (kIsWeb) return const SizedBox.shrink();
    return PopupMenuButton<_Action>(
      key: const Key('export-menu'),
      tooltip: 'Export',
      icon: const Icon(Icons.ios_share),
      onSelected: (a) => _run(context, ref, a),
      itemBuilder: (_) => const [
        PopupMenuItem(
          value: _Action.open,
          child: ListTile(
            leading: Icon(Icons.picture_as_pdf_outlined),
            title: Text('Open as PDF'),
          ),
        ),
        PopupMenuItem(
          value: _Action.print,
          child: ListTile(
            leading: Icon(Icons.print_outlined),
            title: Text('Print'),
          ),
        ),
        PopupMenuItem(
          value: _Action.sharePdf,
          child: ListTile(
            leading: Icon(Icons.share_outlined),
            title: Text('Send PDF'),
          ),
        ),
        PopupMenuItem(
          value: _Action.shareMarkdown,
          child: ListTile(
            leading: Icon(Icons.description_outlined),
            title: Text('Send Markdown'),
          ),
        ),
      ],
    );
  }

  String get _stem {
    final s = name
        .replaceAll(RegExp(r'[^A-Za-z0-9._-]+'), '_')
        .replaceAll(RegExp(r'^_+|_+$'), '');
    return s.isEmpty ? 'export' : (s.length > 120 ? s.substring(0, 120) : s);
  }

  Future<void> _run(BuildContext context, WidgetRef ref, _Action action) async {
    final messenger = ScaffoldMessenger.of(context);
    final api = ref.read(apiServiceProvider);
    messenger.showSnackBar(
      const SnackBar(
        content: Text('Preparing…'),
        duration: Duration(seconds: 20),
      ),
    );
    try {
      if (action == _Action.shareMarkdown) {
        final bytes = await api.getBytes(
          '/v1/${kind.path}/${Uri.encodeComponent(uid)}/markdown',
        );
        // Links to files are API paths; made absolute, they still say where each file is outside the app.
        final text = utf8
            .decode(bytes)
            .replaceAll('](/v1/attachments/', '](${api.base}/v1/attachments/');
        final file = await _save(
          '$_stem.md',
          Uint8List.fromList(utf8.encode(text)),
        );
        messenger.hideCurrentSnackBar();
        await SharePlus.instance.share(
          ShareParams(
            files: [XFile(file.path, mimeType: 'text/markdown')],
            title: name,
          ),
        );
        return;
      }
      final pdf = await api.getBytes(
        '/v1/${kind.path}/${Uri.encodeComponent(uid)}/pdf',
      );
      messenger.hideCurrentSnackBar();
      switch (action) {
        case _Action.print:
          await Printing.layoutPdf(onLayout: (_) async => pdf, name: _stem);
        case _Action.sharePdf:
          final file = await _save('$_stem.pdf', pdf);
          await SharePlus.instance.share(
            ShareParams(
              files: [XFile(file.path, mimeType: 'application/pdf')],
              title: name,
            ),
          );
        case _Action.open:
          final file = await _save('$_stem.pdf', pdf);
          final r = await OpenFilex.open(file.path, type: 'application/pdf');
          if (r.type != ResultType.done) {
            messenger.showSnackBar(
              const SnackBar(
                content: Text('No app on this phone opens PDFs: use Send PDF.'),
              ),
            );
          }
        case _Action.shareMarkdown:
          break;
      }
    } on Problem catch (p) {
      messenger.hideCurrentSnackBar();
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
    } catch (_) {
      messenger.hideCurrentSnackBar();
      messenger.showSnackBar(
        const SnackBar(content: Text('Could not export.')),
      );
    }
  }

  /// In a folder of its own under the app's temporary files, so the file keeps its readable name.
  Future<File> _save(String filename, Uint8List bytes) async {
    final dir = Directory(
      '${(await getTemporaryDirectory()).path}/export-${DateTime.now().millisecondsSinceEpoch}',
    );
    await dir.create(recursive: true);
    final file = File('${dir.path}/$filename');
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }
}
