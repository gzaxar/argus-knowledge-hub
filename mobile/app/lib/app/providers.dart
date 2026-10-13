import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart' show ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../core/blob_store.dart';
import '../core/file_cache_store.dart';
import '../core/local_store.dart';
import '../data/caching_client.dart';

import '../core/config.dart';
import '../core/problem.dart';
import '../core/session.dart';
import '../data/api_service.dart';
import '../data/ask_repository.dart';
import '../data/browse_repository.dart';
import '../data/capture_repositories.dart';
import '../data/graph_repository.dart';
import '../data/replacement_repositories.dart';
import '../data/repositories.dart';
import '../data/update_check.dart';
import '../domain/capture.dart';
import '../domain/models.dart';
import '../features/ask/voice.dart';
import '../features/auth/auth_service.dart';
import '../features/capture/media_source.dart';
import '../features/capture/photo_source.dart';
import '../features/notifications/phone_notifications.dart';
import '../features/scan/text_reader.dart';
import 'queue.dart';

/// Riverpod retries a failed provider by default. A refusal (not found, forbidden, invalid,
/// revoked) will not change by asking again, so only an unreachable server is retried, briefly.
Duration? retryPolicy(int retryCount, Object error) {
  if (error is! Problem || error.code != ProblemCode.offline || retryCount >= 3) return null;
  return Duration(milliseconds: 500 * (1 << retryCount));
}

final configProvider = Provider<AppConfig>((_) => AppConfig.fromEnvironment());
/// The HTTP transport. `null` is the platform default; tests put a fake server here.
final httpClientProvider = Provider<http.Client?>((_) => null);

/// Saved copies, pending commands and their attachments, encrypted on the device.
final localStoreProvider = Provider<LocalStore>((_) => SecureLocalStore());

/// The saved copies of records: encrypted files on a phone (the keystore is for secrets, not hundreds of
/// records — core/file_cache_store.dart), the encrypted local store in a browser.
final cacheStoreProvider =
    Provider<LocalStore>((ref) => kIsWeb ? ref.watch(localStoreProvider) : FileCacheStore());

/// The files pending commands carry (core/blob_store.dart): encrypted files on a phone; in a browser, the
/// local store as before.
final blobStoreProvider = Provider<BlobStore?>((_) => kIsWeb ? null : FileBlobStore());

/// How long a record just read is shown again without asking ARGUS (caching_client.dart).
const freshCopies = Duration(seconds: 45);

/// Light, dark, or as the system says; kept on the device.
class ThemeModeController extends Notifier<ThemeMode> {
  static const _key = 'argus.pref.theme';

  @override
  ThemeMode build() {
    ref.read(localStoreProvider).read(_key).then((v) {
      final m = ThemeMode.values.where((m) => m.name == v).firstOrNull;
      if (m != null && m != state) state = m;
    }).catchError((_) {});
    return ThemeMode.system;
  }

  Future<void> set(ThemeMode m) async {
    state = m;
    await ref.read(localStoreProvider).write(_key, m.name);
  }
}

final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(ThemeModeController.new);

/// Whether records are shown with their key (`SPARC-IP-01 · Ion pump`) or by name or title alone; kept on the
/// device (Settings → Show keys).
class ShowKeysController extends Notifier<bool> {
  static const _key = 'argus.pref.show-keys';

  @override
  bool build() {
    ref.read(localStoreProvider).read(_key).then((v) {
      if (v != null && (v == '1') != state) state = v == '1';
    }).catchError((_) {});
    return true;
  }

  Future<void> set(bool show) async {
    state = show;
    await ref.read(localStoreProvider).write(_key, show ? '1' : '0');
  }
}

final showKeysProvider = NotifierProvider<ShowKeysController, bool>(ShowKeysController.new);

/// Whether ARGUS answered the last request, and the device's offset from the server's clock.
class Reachability {
  const Reachability({this.reachable = true, this.serverOffset = Duration.zero, this.since});

  final bool reachable;
  final Duration serverOffset; // server time minus device time
  final DateTime? since;

  DateTime serverNow() => DateTime.now().add(serverOffset);
}

class ReachabilityController extends Notifier<Reachability> {
  @override
  Reachability build() => const Reachability();

  void reached(bool ok) {
    if (ok != state.reachable) {
      state = Reachability(reachable: ok, serverOffset: state.serverOffset, since: DateTime.now());
    }
  }

  void serverTime(DateTime serverNow) {
    final offset = serverNow.difference(DateTime.now());
    // The Date header has a one-second resolution: only a real change is worth a rebuild.
    if ((offset - state.serverOffset).abs() > const Duration(seconds: 5)) {
      state = Reachability(reachable: state.reachable, serverOffset: offset, since: state.since);
    }
  }
}

final reachabilityProvider = NotifierProvider<ReachabilityController, Reachability>(ReachabilityController.new);

final sessionStoreProvider = Provider<SessionStore>((_) => SessionStore());
final authenticatorProvider = Provider<Authenticator>((ref) => AppAuthAuthenticator(ref.watch(configProvider)));

/// Set when the server says this version is too old (426 `client_too_old`). Nothing else works
/// until the app is updated (revision §24.2, I-MOB-7).
class UpdateRequired extends Notifier<String?> {
  @override
  String? build() => null;
  void require(String minimum) => state = minimum;
}

final updateRequiredProvider = NotifierProvider<UpdateRequired, String?>(UpdateRequired.new);

/// Why the last session ended, shown once on the sign-in screen.
class SignOutReason extends Notifier<String?> {
  @override
  String? build() => null;
  void set(String? reason) => state = reason;
}

final signOutReasonProvider = NotifierProvider<SignOutReason, String?>(SignOutReason.new);

/// The signed-in session. `null` means signed out.
class SessionController extends AsyncNotifier<Session?> {
  SessionStore get _store => ref.read(sessionStoreProvider);
  Future<Session?>? _refreshing;

  @override
  Future<Session?> build() async {
    try {
      return await _store.load();
    } catch (_) {
      return null;
    }
  }

  Session? get current => state.value;

  Future<void> _set(Session? s) async {
    if (s == null) {
      await _store.wipe();
      try {
        await ref.read(cacheStoreProvider).clear(CachingClient.prefix);
        await ref.read(blobStoreProvider)?.clear();
      } catch (_) {}
    } else {
      await _store.save(s);
    }
    state = AsyncData(s);
  }

  /// Sign in with a token (development and web builds only).
  Future<void> signInWithToken(String token) async {
    if (!ref.read(configProvider).allowsDeveloperToken) {
      throw Problem(ProblemCode.forbidden, 'Tokens are not accepted by this build.');
    }
    await _finishSignIn(Session(accessToken: token.trim(), authType: 'token'));
  }

  Future<void> signInWithOidc() async {
    final s = await ref.read(authenticatorProvider).signInWithOidc();
    await _finishSignIn(s);
  }

  /// Check the credentials against ARGUS and register this device before anything is kept.
  Future<void> _finishSignIn(Session candidate) async {
    final config = ref.read(configProvider);
    final service = ApiService(config, () => candidate, httpClient: ref.read(httpClientProvider));
    final label = await WorkspaceRepository(service).whoAmI();
    final installation = await _store.installationId();
    final device = await DeviceRepository(service).register(installation, config.appVersion);
    ref.read(signOutReasonProvider.notifier).set(null);
    await _set(candidate.copyWith(deviceId: device, userLabel: label));
  }

  Future<void> chooseWorkspace(WorkspaceChoice w) async {
    final s = current;
    if (s == null) return;
    await _set(s.copyWith(workspaceId: w.id, workspaceName: w.name));
  }

  Future<void> signOut({String? reason}) async {
    final s = current;
    // Already signed out: a later refusal (several requests in flight) must not replace what the
    // person was told first.
    if (s == null) return;
    await ref.read(authenticatorProvider).endSession(s);
    // Everything the app keeps goes with the session (§5.6, A71). Pending work is not lost silently:
    // the person is told what was not sent.
    final lost = ref.exists(queueProvider) ? ref.read(queueProvider.notifier).unsent : const [];
    final told = lost.isEmpty
        ? reason
        : '${reason ?? 'Signed out.'} ${lost.length} change(s) not yet sent were removed from this device: '
            '${lost.take(5).map((c) => c.label).join('; ')}${lost.length > 5 ? '; …' : ''}.';
    ref.read(signOutReasonProvider.notifier).set(told);
    await _set(null);
    ref.invalidate(queueProvider);
  }

  /// Refresh an OIDC access token shortly before it expires; on failure the person signs in again.
  Future<void> ensureFresh() async {
    final s = current;
    if (s == null || !s.expired || s.authType != 'oidc') return;
    _refreshing ??= ref.read(authenticatorProvider).refresh(s);
    final fresh = await _refreshing;
    _refreshing = null;
    if (fresh == null) {
      await signOut(reason: 'Your session expired. Sign in again.');
    } else {
      await _set(fresh);
    }
  }

  /// Problems that end the session, whatever screen met them.
  void onProblem(Problem p) {
    switch (p.code) {
      case ProblemCode.revoked:
        signOut(reason: 'This device was signed out of ARGUS by an administrator. Its local data was removed.');
      case ProblemCode.unauthenticated:
        signOut(reason: 'Your session is no longer valid. Sign in again.');
      case ProblemCode.clientTooOld:
        ref.read(updateRequiredProvider.notifier).require(p.minimum ?? 'a newer version');
      default:
        break;
    }
  }
}

final sessionProvider = AsyncNotifierProvider<SessionController, Session?>(SessionController.new);

final apiServiceProvider = Provider<ApiService>((ref) {
  final controller = ref.read(sessionProvider.notifier);
  final config = ref.watch(configProvider);
  final reach = ref.read(reachabilityProvider.notifier);
  final caching = CachingClient(
    ref.watch(httpClientProvider) ?? http.Client(),
    ref.watch(cacheStoreProvider),
    retention: config.offlineRetention,
    fresh: freshCopies,
    scope: () {
      final s = ref.read(sessionProvider).value;
      return '${s?.workspaceId}|${s?.userLabel ?? s?.deviceId}';
    },
    onReachable: (ok) => Future.microtask(() => reach.reached(ok)),
    onServerTime: (t) => Future.microtask(() => reach.serverTime(t)),
  );
  return ApiService(
    config,
    () => ref.read(sessionProvider).value,
    onProblem: controller.onProblem,
    ensureFresh: controller.ensureFresh,
    httpClient: caching,
  );
});

final workspaceRepositoryProvider = Provider((ref) => WorkspaceRepository(ref.watch(apiServiceProvider)));
final lookupRepositoryProvider = Provider((ref) => LookupRepository(ref.watch(apiServiceProvider)));
final assetRepositoryProvider = Provider((ref) => AssetRepository(ref.watch(apiServiceProvider)));
final ticketRepositoryProvider = Provider((ref) => TicketRepository(ref.watch(apiServiceProvider)));
final documentRepositoryProvider = Provider((ref) => DocumentRepository(ref.watch(apiServiceProvider)));

/// The workspace in use: every record read below is keyed by it, so switching reloads everything.
final workspaceIdProvider = Provider<String?>((ref) => ref.watch(sessionProvider).value?.workspaceId);

final myWorkspacesProvider = FutureProvider.autoDispose<List<WorkspaceChoice>>(
    (ref) => ref.watch(workspaceRepositoryProvider).mine());

final assetDetailProvider = FutureProvider.autoDispose.family<AssetDetail, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(assetRepositoryProvider).detail(uid);
});

/// A reference attribute's target, named — null if it can no longer be resolved (deleted, or not
/// visible to this viewer), so the caller falls back to showing the bare uid rather than crashing.
final assetBriefProvider = FutureProvider.autoDispose.family<RecordBrief?, String>((ref, uid) async {
  ref.watch(workspaceIdProvider);
  try {
    return await ref.watch(assetRepositoryProvider).brief(uid);
  } on Problem {
    return null;
  }
});

/// The ticket list: every ticket in the workspace, or only the open ones assigned to me (`mine`).
final ticketListProvider = FutureProvider.autoDispose.family<List<TicketListItem>, bool>((ref, mine) {
  ref.watch(workspaceIdProvider);
  return ref.watch(ticketRepositoryProvider).list(mine: mine);
});

final ticketPrioritiesProvider = FutureProvider.autoDispose<List<String>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(ticketRepositoryProvider).priorities();
});

/// A newer release to download, checked once per run (data/update_check.dart).
final updateCheckProvider = FutureProvider<AvailableUpdate?>((ref) {
  final client = ref.watch(httpClientProvider) ?? http.Client();
  return checkForUpdate(ref.watch(configProvider), client);
});

final cockpitRepositoryProvider = Provider((ref) => CockpitRepository(ref.watch(apiServiceProvider)));

final cockpitProvider = FutureProvider.autoDispose<Cockpit>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(cockpitRepositoryProvider).overview();
});

final documentListProvider = FutureProvider.autoDispose<List<DocumentListItem>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(documentRepositoryProvider).list();
});

final revisionAttachmentsProvider =
    FutureProvider.autoDispose.family<List<AttachmentInfo>, (String, String)>((ref, key) {
  ref.watch(workspaceIdProvider);
  return ref.watch(documentRepositoryProvider).revisionAttachments(key.$1, key.$2);
});

final documentRevisionsProvider = FutureProvider.autoDispose.family<List<DocumentRevision>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(documentRepositoryProvider).revisions(uid);
});

final documentTypesProvider = FutureProvider.autoDispose<List<EquipmentType>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(schemaRepositoryProvider).documentTypes();
});

final assetCommentsProvider = FutureProvider.autoDispose.family<List<Comment>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(assetRepositoryProvider).comments(uid);
});

final assetLabelsProvider = FutureProvider.autoDispose.family<List<AssetLabelInfo>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(assetRepositoryProvider).labels(uid);
});

/// After the record changed here: what it shows, its labels and its history are read again.
void refreshAsset(WidgetRef ref, String uid) {
  ref.invalidate(assetDetailProvider(uid));
  ref.invalidate(assetLabelsProvider(uid));
  ref.invalidate(assetHistoryProvider(uid));
}

final assetHistoryProvider = FutureProvider.autoDispose.family<List<HistoryEntry>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(assetRepositoryProvider).history(uid);
});

final assetAttachmentsProvider = FutureProvider.autoDispose.family<List<AttachmentInfo>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(assetRepositoryProvider).attachments(uid);
});

final ticketDetailProvider = FutureProvider.autoDispose.family<TicketDetail, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(ticketRepositoryProvider).detail(uid);
});

final documentDetailProvider = FutureProvider.autoDispose.family<DocumentDetail, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(documentRepositoryProvider).detail(uid);
});

final resolveProvider = FutureProvider.autoDispose.family<LinkTarget, String>((ref, path) {
  ref.watch(workspaceIdProvider);
  return ref.watch(lookupRepositoryProvider).resolveLink(path);
});

final searchProvider = FutureProvider.autoDispose.family<SearchResults, String>((ref, q) {
  ref.watch(workspaceIdProvider);
  if (q.trim().length < 2) return Future.value(const SearchResults());
  return ref.watch(lookupRepositoryProvider).search(q.trim());
});

final serverMetaProvider = FutureProvider.autoDispose<Map<String, Object?>>((ref) async {
  final api = ref.watch(apiServiceProvider);
  final meta = await api.json((c) => api.meta(c).apiMetaWithHttpInfo());
  return meta is Map ? meta.map((k, v) => MapEntry(k.toString(), v)) : {'value': meta};
});

// --------------------------------------------------------------------------- capture and tickets (M2)

final photoSourceProvider = Provider<PhotoSource>((_) => DevicePhotoSource());
final mediaSourceProvider = Provider<MediaSource>((_) => DeviceMediaSource());

/// Reads printed text from a photo, on the device (features/scan/text_reader.dart). Tests replace it.
final textReaderProvider = Provider<TextReader>((_) => DeviceTextReader());
final intakeRepositoryProvider = Provider((ref) => IntakeRepository(ref.watch(apiServiceProvider)));
final schemaRepositoryProvider = Provider((ref) => SchemaRepository(ref.watch(apiServiceProvider)));
final browseRepositoryProvider = Provider((ref) => BrowseRepository(ref.watch(apiServiceProvider)));

/// One kind of type ('objects', 'tickets', 'documents') as its hierarchy, for the lists' type filter and the
/// records' type path. Types change rarely: kept for the session, refreshed with the workspace.
final typeTreeProvider = FutureProvider.family<TypeTree, String>((ref, appliesTo) {
  ref.watch(workspaceIdProvider);
  return ref.watch(schemaRepositoryProvider).tree(appliesTo);
});

final assetTypeCountsProvider = FutureProvider.autoDispose<Map<String, int>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(browseRepositoryProvider).assetTypeCounts();
});
final uploadRepositoryProvider = Provider((ref) => UploadRepository(ref.watch(apiServiceProvider)));
final ticketCommandsProvider = Provider((ref) => TicketCommands(ref.watch(apiServiceProvider)));
final equipmentCommandsProvider = Provider((ref) => EquipmentCommands(ref.watch(apiServiceProvider)));
final notificationRepositoryProvider = Provider((ref) => NotificationRepository(ref.watch(apiServiceProvider)));

final ticketKindsProvider = FutureProvider.autoDispose<List<TicketKind>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(schemaRepositoryProvider).ticketKinds();
});

final objectTypesProvider = FutureProvider.autoDispose<List<EquipmentType>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(schemaRepositoryProvider).objectTypes();
});

final schemaAttributesProvider = FutureProvider.autoDispose.family<List<AttributeDef>, String>((ref, schemaUid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(schemaRepositoryProvider).effectiveAttributes(schemaUid);
});

/// Candidates for a reference attribute's picker: every asset of [schemaUid], plus its descendant
/// types when [includeChildren] — mirrors the web form's ReferenceInput.
final referenceCandidatesProvider =
    FutureProvider.autoDispose.family<List<RecordBrief>, (String schemaUid, bool includeChildren)>((ref, key) async {
  ref.watch(workspaceIdProvider);
  final (schemaUid, includeChildren) = key;
  final assets = ref.watch(assetRepositoryProvider);
  if (!includeChildren) return assets.listByType(schemaUid);
  final allowed = await ref.watch(schemaRepositoryProvider).descendantSchemaUids(schemaUid);
  final all = await assets.listByType(null);
  return all.where((a) => allowed.contains(a.schemaUid)).toList();
});

final commentsProvider = FutureProvider.autoDispose.family<List<Comment>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(ticketCommandsProvider).comments(uid);
});

final attachmentsProvider = FutureProvider.autoDispose.family<List<AttachmentInfo>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(ticketCommandsProvider).attachments(uid);
});

final transitionsProvider = FutureProvider.autoDispose.family<List<TransitionOption>, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(ticketCommandsProvider).transitions(uid);
});

/// The inbox. Push is decision U21; until then the app asks when it opens and when the person looks.
final notificationsProvider = FutureProvider.autoDispose<List<NotificationItem>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(notificationRepositoryProvider).mine();
});

/// The person's open tickets in every workspace (Home, "Your tickets").
final myWorkProvider = FutureProvider.autoDispose<List<CockpitItem>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(notificationRepositoryProvider).myWork();
});

/// Whether the person follows a piece of equipment or a document: (subject, uid).
final followingProvider = FutureProvider.autoDispose.family<bool, (String, String)>(
    (ref, key) => ref.watch(notificationRepositoryProvider).following(key.$1, key.$2));

final queryRepositoryProvider = Provider((ref) => QueryRepository(ref.watch(apiServiceProvider)));

final locationRepositoryProvider = Provider((ref) => LocationRepository(ref.watch(apiServiceProvider)));

/// A record's place on the map (its approved location, and what the field observed).
final assetLocationProvider = FutureProvider.autoDispose.family<AssetLocation, String>((ref, uid) {
  ref.watch(workspaceIdProvider);
  return ref.watch(locationRepositoryProvider).get(uid);
});

/// The features of the current workspace (map, equipment, beam model…); null while unknown — everything is
/// offered then, as before, so an older server or a slow answer hides nothing.
final capabilitiesRepositoryProvider = Provider((ref) => CapabilitiesRepository(ref.watch(apiServiceProvider)));
final workspaceFeaturesProvider = FutureProvider<Set<String>?>((ref) async {
  final ws = ref.watch(workspaceIdProvider);
  if (ws == null) return null;
  try {
    return await ref.watch(capabilitiesRepositoryProvider).features(ws);
  } catch (_) {
    return null;
  }
});

/// Field observations of this workspace's records waiting for a decision.
final locationReviewsProvider = FutureProvider.autoDispose<List<LocationObservationItem>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(locationRepositoryProvider).reviews();
});

// --------------------------------------------------------------------------- replacement and review (M3)

final replacementRepositoryProvider = Provider((ref) => ReplacementRepository(ref.watch(apiServiceProvider)));
final reviewRepositoryProvider = Provider((ref) => ReviewRepository(ref.watch(apiServiceProvider)));

final myReviewItemsProvider = FutureProvider.autoDispose<List<ReviewItem>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(reviewRepositoryProvider).mine();
});

// --------------------------------------------------------------------------- ask

final askRepositoryProvider = Provider((ref) => AskRepository(ref.watch(apiServiceProvider)));

/// The phone's speech recognition and voice. Tests put a fake here.
final voiceProvider = Provider<Voice>((_) => DeviceVoice());

final askAvailabilityProvider = FutureProvider.autoDispose<AskAvailability>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(askRepositoryProvider).availability();
});

final askConversationsProvider = FutureProvider.autoDispose<List<AskConversationSummary>>((ref) {
  ref.watch(workspaceIdProvider);
  return ref.watch(askRepositoryProvider).conversations();
});


/// News on the phone while the app is closed (features/notifications/phone_notifications.dart). Tests replace it.
final phoneNotifierProvider = Provider<PhoneNotifier>((_) => DevicePhoneNotifier());

/// What the person hears about, per workspace.
final subscriptionsProvider = FutureProvider.autoDispose<List<WorkspaceSubscription>>(
    (ref) => ref.watch(notificationRepositoryProvider).subscriptions());

final graphRepositoryProvider = Provider((ref) => GraphRepository(ref.watch(apiServiceProvider)));

final connectedProvider = FutureProvider.autoDispose.family<List<GraphLink>, (RecordKind, String)>((ref, key) {
  ref.watch(workspaceIdProvider);
  return ref.watch(graphRepositoryProvider).connected(key.$1, key.$2);
});

final byMeaningProvider = FutureProvider.autoDispose.family<SemanticNeighbours, (RecordKind, String)>((ref, key) {
  ref.watch(workspaceIdProvider);
  return ref.watch(graphRepositoryProvider).byMeaning(key.$1, key.$2);
});
