import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app/providers.dart';
import '../domain/capture.dart';

/// Text into [controller] from a photo — taken now or chosen among the phone's photos — read on the device
/// (features/scan/text_reader.dart: nothing is sent anywhere to be read). What is read goes where the cursor
/// is, or after what is written; it never replaces what was typed, and stays to be checked and corrected.
class PhotoTextButton extends ConsumerStatefulWidget {
  const PhotoTextButton({super.key, required this.controller, this.onInserted, this.onPhoto, this.label});

  final TextEditingController controller;
  final VoidCallback? onInserted;

  /// The photo the text was read from — for a document, kept with it as its source.
  final void Function(PickedPhoto photo)? onPhoto;

  /// Shown as a labelled action (under a long text) rather than an icon inside the field.
  final String? label;

  @override
  ConsumerState<PhotoTextButton> createState() => _PhotoTextButtonState();
}

class _PhotoTextButtonState extends ConsumerState<PhotoTextButton> {
  bool _reading = false;

  void _say(String text) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _read() async {
    final reader = ref.read(textReaderProvider);
    if (!reader.available) {
      _say('Reading text from a photo needs the app on a phone.');
      return;
    }
    final fromGallery = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const ListTile(title: Text('Text from a photo'), subtitle: Text('Read on this phone; check it afterwards.')),
          ListTile(
            key: const Key('photo-text-camera'),
            leading: const Icon(Icons.photo_camera_outlined),
            title: const Text('Take a photo'),
            onTap: () => Navigator.pop(sheet, false),
          ),
          ListTile(
            key: const Key('photo-text-gallery'),
            leading: const Icon(Icons.photo_library_outlined),
            title: const Text('Choose from photos'),
            onTap: () => Navigator.pop(sheet, true),
          ),
        ]),
      ),
    );
    if (fromGallery == null || !mounted) return;
    final photo = await ref.read(photoSourceProvider).take(fromGallery: fromGallery);
    if (photo == null || !mounted) return;
    setState(() => _reading = true);
    try {
      final text = (await reader.read(photo)).trim();
      if (!mounted) return;
      if (text.isEmpty) {
        _say('No text could be read in the photo.');
        return;
      }
      insertText(widget.controller, text);
      widget.onPhoto?.call(photo);
      widget.onInserted?.call();
    } catch (_) {
      _say('The text could not be read from that photo.');
    } finally {
      if (mounted) setState(() => _reading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final icon = _reading
        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
        : const Icon(Icons.document_scanner_outlined);
    if (widget.label != null) {
      return TextButton.icon(onPressed: _reading ? null : _read, icon: icon, label: Text(widget.label!));
    }
    return IconButton(tooltip: 'Text from a photo', onPressed: _reading ? null : _read, icon: icon);
  }
}

/// [text] put where the cursor is (replacing a selection), or after what is there, on a line of its own.
void insertText(TextEditingController c, String text) {
  final value = c.value;
  final sel = value.selection;
  final at = sel.isValid ? sel.start : value.text.length;
  final end = sel.isValid ? sel.end : value.text.length;
  final before = value.text.substring(0, at);
  final after = value.text.substring(end);
  final lead = before.isEmpty || before.endsWith('\n') ? '' : '\n';
  final trail = after.isEmpty || after.startsWith('\n') ? '' : '\n';
  final inserted = '$lead$text$trail';
  c.value = TextEditingValue(
    text: '$before$inserted$after',
    selection: TextSelection.collapsed(offset: before.length + inserted.length),
  );
}
