import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:uuid/uuid.dart';

/// Who is signed in, where, and on which registered device. Kept only in the platform keystore
/// (Keychain, Android Keystore) and wiped on sign-out or revocation (flutter-app-design §6).
class Session {
  const Session({
    required this.accessToken,
    required this.authType,
    this.refreshToken,
    this.expiresAt,
    this.workspaceId,
    this.workspaceName,
    this.deviceId,
    this.userLabel,
    this.provider,
    this.apiBase,
    this.verified = true,
  });

  final String accessToken;
  final String authType; // oidc | token
  final String? refreshToken;
  final DateTime? expiresAt;
  final String? workspaceId;
  final String? workspaceName;
  final String? deviceId;
  final String? userLabel;
  final String? provider; // the OidcProvider that issued it (main | alt); null: main

  /// The ARGUS server this session works with; null: the build's default (a session saved before servers
  /// could be chosen).
  final String? apiBase;

  /// False for a sign-in no server could confirm yet (every one was out of reach): the app opens on what it has
  /// kept, and confirms it with the server — whoami, device registration — as soon as the server answers.
  final bool verified;

  bool get expired => expiresAt != null && DateTime.now().isAfter(expiresAt!.subtract(const Duration(seconds: 30)));

  Session copyWith({
    String? accessToken,
    String? refreshToken,
    DateTime? expiresAt,
    String? workspaceId,
    String? workspaceName,
    String? deviceId,
    String? userLabel,
    String? apiBase,
    bool? verified,
  }) =>
      Session(
        accessToken: accessToken ?? this.accessToken,
        authType: authType,
        refreshToken: refreshToken ?? this.refreshToken,
        expiresAt: expiresAt ?? this.expiresAt,
        workspaceId: workspaceId ?? this.workspaceId,
        workspaceName: workspaceName ?? this.workspaceName,
        deviceId: deviceId ?? this.deviceId,
        userLabel: userLabel ?? this.userLabel,
        provider: provider,
        apiBase: apiBase ?? this.apiBase,
        verified: verified ?? this.verified,
      );

  Map<String, dynamic> toJson() => {
        'accessToken': accessToken,
        'authType': authType,
        'refreshToken': refreshToken,
        'expiresAt': expiresAt?.toIso8601String(),
        'provider': provider,
        'workspaceId': workspaceId,
        'workspaceName': workspaceName,
        'deviceId': deviceId,
        'userLabel': userLabel,
        'apiBase': apiBase,
        'verified': verified,
      };

  static Session fromJson(Map<String, dynamic> j) => Session(
        accessToken: j['accessToken'] as String,
        authType: j['authType'] as String,
        refreshToken: j['refreshToken'] as String?,
        expiresAt: j['expiresAt'] == null ? null : DateTime.parse(j['expiresAt'] as String),
        workspaceId: j['workspaceId'] as String?,
        workspaceName: j['workspaceName'] as String?,
        deviceId: j['deviceId'] as String?,
        userLabel: j['userLabel'] as String?,
        provider: j['provider'] as String?,
        apiBase: j['apiBase'] as String?,
        verified: j['verified'] as bool? ?? true,
      );
}

/// Secure persistence of the session and the per-installation id.
class SessionStore {
  SessionStore([FlutterSecureStorage? storage]) : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _sessionKey = 'argus.session';
  static const _installationKey = 'argus.installation';

  Future<Session?> load() async {
    final raw = await _storage.read(key: _sessionKey);
    if (raw == null) return null;
    try {
      return Session.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      await _storage.delete(key: _sessionKey);
      return null;
    }
  }

  Future<void> save(Session s) => _storage.write(key: _sessionKey, value: jsonEncode(s.toJson()));

  /// An id for this installation, stable until the app is removed; not tied to the person.
  Future<String> installationId() async {
    final existing = await _storage.read(key: _installationKey);
    if (existing != null) return existing;
    final id = const Uuid().v4();
    await _storage.write(key: _installationKey, value: id);
    return id;
  }

  /// Sign-out, revocation or expiry: everything the app keeps goes, except the installation id and the choice
  /// of server (`argus.backend.*`: addresses, nothing about the person).
  Future<void> wipe() async {
    final kept = {
      for (final e in (await _storage.readAll()).entries)
        if (e.key == _installationKey || e.key.startsWith('argus.backend.')) e.key: e.value,
    };
    await _storage.deleteAll();
    for (final e in kept.entries) {
      await _storage.write(key: e.key, value: e.value);
    }
  }
}
