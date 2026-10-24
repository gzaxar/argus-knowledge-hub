import 'dart:typed_data';

import 'package:argus_field/app/app.dart';
import 'package:argus_field/app/providers.dart';
import 'package:argus_field/app/router.dart';
import 'package:argus_field/core/config.dart';
import 'package:argus_field/domain/capture.dart';
import 'package:argus_field/features/capture/photo_source.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:argus_field/core/blob_store.dart';
import 'package:argus_field/core/local_store.dart';

import 'package:argus_field/features/capture/media_source.dart';
import 'package:argus_field/features/notifications/phone_notifications.dart';
import 'package:argus_field/features/scan/text_reader.dart';

import 'fake_server.dart';

const testConfig = AppConfig(
  environment: 'development',
  apiBase: 'https://argus.test',
  linkHost: 'argus.test',
  oidcIssuer: '',
  oidcClientId: '',
  oidcRedirect: '',
  appVersion: '0.2.0',
);

const signedIn = {
  'argus.session': '{"accessToken":"tok","authType":"token","workspaceId":"$workspaceId",'
      '"workspaceName":"Slice","deviceId":"dev-1"}',
};

/// A camera that always returns the same small JPEG header, 3000 bytes long.
class FakePhotos implements PhotoSource {
  int taken = 0;
  bool? lastFromGallery;

  @override
  Future<PickedPhoto?> take({bool fromGallery = false}) async {
    taken++;
    lastFromGallery = fromGallery;
    final bytes = Uint8List(3000)..setAll(0, [0xFF, 0xD8, 0xFF, 0xE0]);
    return PickedPhoto(bytes: bytes, name: 'IMG_$taken.jpg', mimeType: 'image/jpeg');
  }
}

class Running {
  Running(this.server, this.photos, this.tester, [FakeTextReader? texts]) : texts = texts ?? FakeTextReader();

  final FakeArgus server;
  final FakePhotos photos;
  final FakeTextReader texts;
  final WidgetTester tester;

  Future<void> go(String path) async {
    ProviderScope.containerOf(tester.element(find.byType(ArgusFieldApp))).read(routerProvider).go(path);
    await tester.pumpAndSettle();
  }

  Future<void> tap(String key) async {
    final f = find.byKey(Key(key));
    await tester.ensureVisible(f);
    await tester.pumpAndSettle();
    await tester.tap(f);
    await tester.pumpAndSettle();
  }

  Future<void> type(String key, String text) async {
    final f = find.byKey(Key(key));
    await tester.ensureVisible(f);
    await tester.enterText(f, text);
    await tester.pump();
  }
}

Future<Running> start(WidgetTester tester,
    {Map<String, String> stored = signedIn,
    List<Override> overrides = const [],
    AppConfig config = testConfig,
    void Function(FakeArgus server)? prepare}) async {
  FlutterSecureStorage.setMockInitialValues(Map.of(stored));
  await tester.binding.setSurfaceSize(const Size(420, 1400));
  final server = FakeArgus();
  prepare?.call(server);
  final photos = FakePhotos();
  final texts = FakeTextReader();
  final media = FakeMedia();
  await tester.pumpWidget(ProviderScope(
    retry: retryPolicy,
    overrides: [
      configProvider.overrideWithValue(config),
      httpClientProvider.overrideWithValue(server.client),
      cacheStoreProvider.overrideWithValue(MemoryLocalStore()),
      blobStoreProvider.overrideWithValue(MemoryBlobStore()),
      photoSourceProvider.overrideWithValue(photos),
      textReaderProvider.overrideWithValue(texts),
      mediaSourceProvider.overrideWithValue(media),
      phoneNotifierProvider.overrideWithValue(FakePhoneNotifier()),
      ...overrides,
    ],
    child: const ArgusFieldApp(),
  ));
  await tester.pumpAndSettle();
  return Running(server, photos, tester, texts);
}



/// What the camera "reads" on a nameplate, in tests.
class FakeTextReader implements TextReader {
  String text = '';

  @override
  bool get available => true;

  @override
  Future<String> read(PickedPhoto photo) async => text;
}


/// Video, recorded notes and places, in tests.
class FakeMedia implements MediaSource {
  @override
  Future<PickedPhoto?> video() async =>
      PickedPhoto(bytes: Uint8List.fromList(List.filled(4000, 7)), name: 'fault.mp4', mimeType: 'video/mp4');

  @override
  Future<PickedPhoto?> place() async => placeFile(41.8219, 12.6826, accuracy: 4);

  @override
  NoteRecorder recorder() => _FakeRecorder();
}

class _FakeRecorder implements NoteRecorder {
  @override
  Future<void> start() async {}

  @override
  Future<PickedPhoto?> stop() async =>
      PickedPhoto(bytes: Uint8List.fromList(List.filled(900, 3)), name: 'note.m4a', mimeType: 'audio/mp4');

  @override
  Future<void> cancel() async {}
}


/// Notifications on the phone, in tests: allowed, and remembered.
class FakePhoneNotifier implements PhoneNotifier {
  bool on = false;

  @override
  bool get supported => true;

  @override
  Future<bool> get enabled async => on;

  @override
  Future<bool> enable(AppConfig config) async => on = true;

  @override
  Future<void> disable() async => on = false;

  int checks = 0;

  @override
  Future<void> checkNow(AppConfig config) async => checks++;

  @override
  Duration? get whileOpenEvery => null;
}
