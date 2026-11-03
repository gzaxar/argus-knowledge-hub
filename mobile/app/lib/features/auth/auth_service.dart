import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_appauth/flutter_appauth.dart';

import '../../core/config.dart';
import '../../core/problem.dart';
import '../../core/session.dart';

/// Sign-in (flutter-app-design §6.1): OIDC authorization code with PKCE through the system
/// browser, never an embedded web view and never a password typed into the app. A developer
/// token is accepted only in non-production builds, for development and the web build.
abstract class Authenticator {
  bool get supportsOidc;
  /// Sign in with one of the build's providers ([AppConfig.providers]; by default the main one).
  Future<Session> signInWithOidc([String provider = 'main']);
  Future<Session?> refresh(Session s);
  Future<void> endSession(Session s);
}

class AppAuthAuthenticator implements Authenticator {
  AppAuthAuthenticator(this.config, [FlutterAppAuth? appAuth])
    : _appAuth = appAuth ?? const FlutterAppAuth();

  final AppConfig config;
  final FlutterAppAuth _appAuth;

  @override
  bool get supportsOidc => !kIsWeb;

  @override
  Future<Session> signInWithOidc([String provider = 'main']) async {
    final p = config.provider(provider);
    try {
      final google = p.usesGoogle;
      final r = await _appAuth.authorizeAndExchangeCode(
        AuthorizationTokenRequest(
          p.clientId,
          config.oidcRedirect,
          issuer: p.issuer,
          allowInsecureConnections: p.issuer.startsWith('http://'),
          scopes: google
              ? const ['openid', 'profile', 'email']
              : const ['openid', 'profile', 'email', 'offline_access'],
          // Google returns a refresh token only on consent, so ask for it every time. AppAuth
          // refuses `prompt` among the additional parameters: it has its own field.
          promptValues: google ? const ['select_account', 'consent'] : null,
          additionalParameters: google ? const {'access_type': 'offline'} : null,
        ),
      );
      final token = p.sendsIdToken ? r.idToken : r.accessToken;
      if (token == null) {
        throw Problem(ProblemCode.unauthenticated, 'Sign-in did not return a token.');
      }
      return Session(
        accessToken: token,
        authType: 'oidc',
        refreshToken: r.refreshToken,
        expiresAt: r.accessTokenExpirationDateTime,
        provider: p.id,
      );
    } on FlutterAppAuthUserCancelledException {
      throw Problem(ProblemCode.unauthenticated, 'Sign-in was cancelled.');
    } on FlutterAppAuthPlatformException catch (e) {
      throw Problem(
        ProblemCode.unauthenticated,
        'Sign-in failed: ${e.message ?? e.code}',
      );
    }
  }

  @override
  Future<Session?> refresh(Session s) async {
    if (s.authType != 'oidc' || s.refreshToken == null) return null;
    final p = config.provider(s.provider);                // renewed where it was issued
    try {
      final r = await _appAuth.token(
        TokenRequest(
          p.clientId,
          config.oidcRedirect,
          issuer: p.issuer,
          allowInsecureConnections: p.issuer.startsWith('http://'),
          refreshToken: s.refreshToken,
        ),
      );
      final token = p.sendsIdToken ? r.idToken : r.accessToken;
      if (token == null) return null;
      return s.copyWith(
        accessToken: token,
        refreshToken: r.refreshToken,
        expiresAt: r.accessTokenExpirationDateTime,
      );
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> endSession(Session s) async {
    // The identity provider's session ends with the browser's; the tokens here are wiped by the
    // caller. Nothing to do for a developer token.
  }
}
