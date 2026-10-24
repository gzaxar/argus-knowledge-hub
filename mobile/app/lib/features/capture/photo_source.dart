import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:image_picker/image_picker.dart';

import '../../domain/capture.dart';

/// Where photos come from: the camera on a phone (or, [fromGallery], the photos already on it), a file chooser
/// in the browser. Tests replace it.
abstract class PhotoSource {
  Future<PickedPhoto?> take({bool fromGallery = false});
}

class DevicePhotoSource implements PhotoSource {
  final _picker = ImagePicker();

  @override
  Future<PickedPhoto?> take({bool fromGallery = false}) async {
    // Resized on the device: a nameplate or a fault needs detail, not 50 megapixels (§5.5).
    final file = await _picker.pickImage(
      source: kIsWeb || fromGallery ? ImageSource.gallery : ImageSource.camera,
      maxWidth: 2400,
      maxHeight: 2400,
      imageQuality: 85,
    );
    if (file == null) return null;
    final bytes = await file.readAsBytes();
    final mime = file.mimeType ?? (file.name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg');
    return PickedPhoto(bytes: bytes, name: file.name, mimeType: mime);
  }
}
