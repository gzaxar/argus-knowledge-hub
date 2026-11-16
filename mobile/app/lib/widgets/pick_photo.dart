import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app/providers.dart';
import '../domain/capture.dart';

/// Whether a photo input asks where the photo comes from (camera or the photos already on the phone). Tests that
/// are not about the choice turn it off and get the camera.
final askPhotoSourceProvider = Provider<bool>((_) => true);

/// A photo for any photo input: taken with the camera or chosen from the phone's photos, asked first. In the
/// browser there is only a file to choose. Null when the person cancels.
Future<PickedPhoto?> pickPhoto(BuildContext context, WidgetRef ref, {String title = 'Add a photo'}) async {
  final source = ref.read(photoSourceProvider);
  if (kIsWeb) return source.take(fromGallery: true);
  if (!ref.read(askPhotoSourceProvider)) return source.take();
  final fromGallery = await showModalBottomSheet<bool>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(title: Text(title)),
        ListTile(
          key: const Key('photo-camera'),
          leading: const Icon(Icons.photo_camera_outlined),
          title: const Text('Take a photo'),
          onTap: () => Navigator.pop(sheet, false),
        ),
        ListTile(
          key: const Key('photo-gallery'),
          leading: const Icon(Icons.photo_library_outlined),
          title: const Text('Choose from photos'),
          onTap: () => Navigator.pop(sheet, true),
        ),
      ]),
    ),
  );
  if (fromGallery == null) return null;
  return source.take(fromGallery: fromGallery);
}
