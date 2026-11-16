import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../app/providers.dart';
import '../../core/link_parser.dart';
import '../../core/problem.dart';
import 'text_reader.dart';
import '../../widgets/pick_photo.dart';

/// Scan a label (flutter-app-design §5.2): a QR code, a DataMatrix or a barcode of any kind, or — with
/// "Read text" — what is printed on a nameplate (a serial, an inventory number), read on the device. What
/// was read is parsed before anything happens: only ARGUS links are followed, other links are refused and
/// plain values are looked up among every kind of label, QR codes first. Typing the label is always
/// possible (a damaged label, no camera).
class ScanScreen extends ConsumerStatefulWidget {
  const ScanScreen({super.key, this.pick = false});

  /// Return what was read to the screen that asked, instead of opening it.
  final bool pick;

  @override
  ConsumerState<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends ConsumerState<ScanScreen> {
  final _controller = MobileScannerController(
    // Every format: a serial is often an EAN, ITF or Code 93 barcode, not only a QR code.
    formats: const [BarcodeFormat.all],
  );
  final _typed = TextEditingController();
  bool _handling = false;
  String? _refusal;

  @override
  void dispose() {
    _controller.dispose();
    _typed.dispose();
    super.dispose();
  }

  void _handle(String raw) {
    if (_handling) return;
    final result = parseScan(raw, linkHost: ref.read(configProvider).linkHost);
    switch (result) {
      case ArgusPath(:final path):
        _handling = true;
        widget.pick ? context.pop(path) : context.pushReplacement(path);
      case LabelValue(:final value):
        _handling = true;
        widget.pick ? context.pop('/lookup/${Uri.encodeComponent(value)}')
            : context.pushReplacement('/lookup/${Uri.encodeComponent(value)}');
      case Refused(:final reason):
        setState(() => _refusal = reason);
    }
  }

  bool _reading = false;

  /// A photo of the printed text, read on the device; the values that look like a label are looked up in
  /// turn, and the first that finds a record opens it. None found: the person chooses what to look up.
  Future<void> _readText() async {
    final reader = ref.read(textReaderProvider);
    setState(() {
      _reading = true;
      _refusal = null;
    });
    try {
      try {
        await _controller.stop(); // one camera at a time
      } catch (_) {}
      if (!mounted) return;
      final photo = await pickPhoto(context, ref, title: 'Photo of the label');
      if (photo == null || !mounted) return;
      final candidates = labelCandidates(await reader.read(photo));
      if (!mounted) return;
      if (candidates.isEmpty) {
        setState(() => _refusal = 'No serial, code or number could be read. Try closer, or type it below.');
        return;
      }
      if (widget.pick) {
        final chosen = await _choose(candidates, 'Which is the label?');
        if (chosen != null && mounted) context.pop('/lookup/${Uri.encodeComponent(chosen)}');
        return;
      }
      for (final c in candidates.take(8)) {
        try {
          final target = await ref.read(lookupRepositoryProvider).lookup(c);
          if (!mounted) return;
          _handling = true;
          context.pushReplacement(target.route);
          return;
        } on Problem catch (p) {
          if (p.code == ProblemCode.ambiguous) {
            if (!mounted) return;
            _handling = true;
            context.pushReplacement('/lookup/${Uri.encodeComponent(c)}'); // the person chooses among them
            return;
          }
          if (p.code != ProblemCode.notFound) rethrow;
        }
      }
      final chosen = await _choose(candidates, 'No record carries these. Look one up anyway?');
      if (chosen != null && mounted) {
        _handling = true;
        context.pushReplacement('/lookup/${Uri.encodeComponent(chosen)}');
      }
    } on Problem catch (p) {
      if (mounted) setState(() => _refusal = p.message);
    } finally {
      if (mounted) {
        setState(() => _reading = false);
        if (!_handling) {
          try {
            await _controller.start();
          } catch (_) {}
        }
      }
    }
  }

  Future<String?> _choose(List<String> candidates, String title) {
    setState(() => _reading = false); // read: what is left is the person's choice
    return showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(title, style: Theme.of(sheet).textTheme.titleMedium),
          ),
          for (final c in candidates)
            ListTile(
              key: Key('scan-candidate-$c'),
              leading: const Icon(Icons.label_outline),
              title: Text(c),
              onTap: () => Navigator.pop(sheet, c),
            ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final canRead = ref.watch(textReaderProvider).available;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan label'),
        actions: [
          IconButton(
            tooltip: 'Torch',
            icon: const Icon(Icons.flashlight_on_outlined),
            onPressed: () => _controller.toggleTorch(),
          ),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: Stack(fit: StackFit.expand, children: [
            MobileScanner(
              controller: _controller,
              onDetect: (capture) {
                final value = capture.barcodes.map((b) => b.rawValue).whereType<String>().firstOrNull;
                if (value != null) _handle(value);
              },
              errorBuilder: (context, error) => Container(
                color: Colors.black,
                alignment: Alignment.center,
                padding: const EdgeInsets.all(24),
                child: Text(
                  error.errorCode == MobileScannerErrorCode.permissionDenied
                      ? 'The camera is not allowed. Allow it in the system settings, or type the label below.'
                      : 'The camera is not available here. Type the label below.',
                  style: const TextStyle(color: Colors.white),
                  textAlign: TextAlign.center,
                ),
              ),
            ),
            Center(
              child: Container(
                width: 240,
                height: 240,
                decoration: BoxDecoration(
                  border: Border.all(color: Colors.white70, width: 2),
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
            ),
          ]),
        ),
        if (canRead)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                key: const Key('scan-read-text'),
                onPressed: _reading ? null : _readText,
                icon: _reading
                    ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.document_scanner_outlined),
                label: Text(_reading ? 'Reading…' : 'Read printed text (serial, inventory number)'),
              ),
            ),
          ),
        if (_refusal != null)
          Container(
            key: const Key('scan-refusal'),
            width: double.infinity,
            color: Theme.of(context).colorScheme.errorContainer,
            padding: const EdgeInsets.all(12),
            child: Text(_refusal!, style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer)),
          ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              key: const Key('scan-typed'),
              controller: _typed,
              textInputAction: TextInputAction.go,
              decoration: InputDecoration(
                labelText: 'Or type the label',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(icon: const Icon(Icons.arrow_forward), onPressed: () => _handle(_typed.text)),
              ),
              onSubmitted: _handle,
            ),
          ),
        ),
      ]),
    );
  }
}
