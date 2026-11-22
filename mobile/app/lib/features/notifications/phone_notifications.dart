import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:workmanager/workmanager.dart';

import '../../core/config.dart';
import '../../core/problem.dart';
import '../../core/session.dart';
import '../../data/api_service.dart';
import '../../data/capture_repositories.dart';
import '../../domain/capture.dart';
import '../auth/auth_service.dart';

/// News from ARGUS on the phone while the app is closed (no push service yet): every 15 minutes or so —
/// as often as Android allows, and when iOS chooses — the app asks ARGUS for the person's unread news in
/// every workspace and shows what it has not shown before. Tapping one opens what it is about.
///
/// What a person hears about is chosen per workspace (Settings → Notifications); this only carries it.
abstract class PhoneNotifier {
  bool get supported;

  /// Asks the person to allow notifications; true when they did.
  Future<bool> enable(AppConfig config);

  Future<void> disable();

  Future<bool> get enabled;

  /// While the app is open: ask for news now, and show what is new on the phone when the person turned it on.
  Future<void> checkNow(AppConfig config);

  /// How often the open app asks (null: never — tests).
  Duration? get whileOpenEvery;
}

const _task = 'argus-news';
const _lastShown = 'argus.notify.last-shown';
const _on = 'argus.notify.on';
final _plugin = FlutterLocalNotificationsPlugin();

/// Where a tapped notification leads, for the app to open (set by the app once it runs).
void Function(String route)? onNotificationTapped;
String? launchedFromNotification;

Future<void> initPhoneNotifications() async {
  if (kIsWeb) return;
  await _plugin.initialize(
    settings: const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(
          requestAlertPermission: false, requestBadgePermission: false, requestSoundPermission: false),
    ),
    onDidReceiveNotificationResponse: (r) {
      final route = r.payload;
      if (route != null && route.isNotEmpty) onNotificationTapped?.call(route);
    },
  );
  final launch = await _plugin.getNotificationAppLaunchDetails();
  if (launch?.didNotificationLaunchApp == true) launchedFromNotification = launch!.notificationResponse?.payload;
}

class DevicePhoneNotifier implements PhoneNotifier {
  @override
  bool get supported => !kIsWeb;

  @override
  Future<bool> get enabled async => await const FlutterSecureStorage().read(key: _on) == '1';

  @override
  Future<bool> enable(AppConfig config) async {
    final android = _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    final ios = _plugin.resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>();
    final allowed = await android?.requestNotificationsPermission() ??
        await ios?.requestPermissions(alert: true, badge: true, sound: true) ??
        false;
    if (!allowed) return false;
    // From now on: what is already there was seen in the app, not news.
    await checkForNews(config, showing: false);
    await Workmanager().initialize(newsCallback);
    await Workmanager().registerPeriodicTask(_task, _task,
        frequency: const Duration(minutes: 15),
        constraints: Constraints(networkType: NetworkType.connected),
        existingWorkPolicy: ExistingPeriodicWorkPolicy.keep);
    await const FlutterSecureStorage().write(key: _on, value: '1');
    return true;
  }

  @override
  Future<void> disable() async {
    await Workmanager().cancelByUniqueName(_task);
    await const FlutterSecureStorage().delete(key: _on);
  }

  @override
  Future<void> checkNow(AppConfig config) async {
    if (!await enabled) return;
    try {
      await checkForNews(config);
    } catch (_) {
      // offline, or signed out: the next check tries again
    }
  }

  @override
  Duration? get whileOpenEvery => const Duration(minutes: 2);
}

@pragma('vm:entry-point')
void newsCallback() {
  Workmanager().executeTask((task, input) async {
    WidgetsFlutterBinding.ensureInitialized();
    try {
      await initPhoneNotifications();
      await checkForNews(AppConfig.fromEnvironment());
    } catch (_) {
      // a check that fails (no network, signed out) waits for the next one
    }
    return true;
  });
}

/// Asks ARGUS for unread news newer than the last shown, and shows it ([showing]) or only takes note of it.
Future<int> checkForNews(AppConfig config, {bool showing = true}) async {
  const storage = FlutterSecureStorage();
  final store = SessionStore();
  var session = await store.load();
  if (session == null) return 0;
  final auth = AppAuthAuthenticator(config);
  Future<void> fresh() async {
    if (session!.expired && session!.refreshToken != null) {
      Session? renewed;
      try {
        renewed = await auth.refresh(session!);
      } on Problem {
        return;                              // the sign-in service is out of reach: try at the next check
      }
      if (renewed != null) {
        session = renewed;
        await store.save(renewed);
      }
    }
  }

  if (!session!.verified) return 0;           // a sign-in no server has confirmed yet: nothing to ask
  final api = ApiService(config.withApiBase(session!.apiBase ?? config.apiBase), () => session,
      ensureFresh: fresh, httpClient: http.Client());
  final after = int.tryParse(await storage.read(key: _lastShown) ?? '') ?? 0;
  final news = await NotificationRepository(api).everywhere(after: after);
  if (news.isEmpty) return 0;
  if (showing) {
    for (final n in news) {
      await showNews(n);
    }
  }
  await storage.write(key: _lastShown, value: '${news.map((n) => n.id).reduce((a, b) => a > b ? a : b)}');
  return news.length;
}

Future<void> showNews(NotificationItem n) => _plugin.show(
      id: n.id,
      title: n.title,
      body: n.workspaceName,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails('argus-news', 'News from ARGUS',
            channelDescription: 'New tickets, documents and equipment in the workspaces you chose',
            importance: Importance.defaultImportance),
        iOS: DarwinNotificationDetails(),
      ),
      payload: n.route,
    );
