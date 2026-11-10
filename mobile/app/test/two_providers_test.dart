import 'package:argus_field/core/config.dart';
import 'package:argus_field/core/session.dart';
import 'package:argus_field/features/auth/auth_service.dart';
import 'package:flutter_appauth/flutter_appauth.dart';
import 'package:flutter_test/flutter_test.dart';

/// The identity providers, faked: what was asked of them, and tokens that say who issued them.
class _FakeAppAuth extends FlutterAppAuth {
  final asked = <({String issuer, String client})>[];

  @override
  Future<AuthorizationTokenResponse> authorizeAndExchangeCode(AuthorizationTokenRequest request) async {
    asked.add((issuer: request.issuer!, client: request.clientId));
    return AuthorizationTokenResponse('access@${request.issuer}', 'refresh@${request.issuer}',
        DateTime.now().add(const Duration(minutes: 5)), 'id@${request.issuer}', 'Bearer', null, null, null);
  }

  @override
  Future<TokenResponse> token(TokenRequest request) async {
    asked.add((issuer: request.issuer!, client: request.clientId));
    return TokenResponse('access2@${request.issuer}', 'refresh2@${request.issuer}',
        DateTime.now().add(const Duration(minutes: 5)), 'id2@${request.issuer}', 'Bearer', null, null);
  }
}

const aai = 'https://idp-test.app.infn.it/auth/realms/aai';
const keycloak = 'https://keycloak.example/realms/argus';

const config = AppConfig(
  environment: 'production', apiBase: 'https://argus.example', linkHost: 'argus.example',
  oidcIssuer: aai, oidcClientId: 'argus-knowledge-hub', oidcRedirect: 'it.infn.argus.field:/oauthredirect',
  appVersion: '1.0.0', oidcLabel: 'INFN login', oidcIdToken: true,
  altIssuer: keycloak, altClientId: 'argus-mobile', altLabel: 'Google or ARGUS account');

void main() {
  test('INFN login sends its ID token; the second provider its access token; each is renewed where it came from',
      () async {
    final appAuth = _FakeAppAuth();
    final auth = AppAuthAuthenticator(config, appAuth);
    expect(config.providers.map((p) => p.label), ['INFN login', 'Google or ARGUS account']);

    final infn = await auth.signInWithOidc();
    expect(infn.accessToken, 'id@$aai', reason: 'the ID token: addressed to argus-knowledge-hub, the API audience');
    expect(infn.provider, 'main');
    final google = await auth.signInWithOidc('alt');
    expect(google.accessToken, 'access@$keycloak', reason: "Keycloak's access token carries the API audience");
    expect(google.provider, 'alt');

    final renewed = await auth.refresh(Session.fromJson(google.toJson()));        // kept, and read back
    expect(renewed!.accessToken, 'access2@$keycloak');
    expect(appAuth.asked.last, (issuer: keycloak, client: 'argus-mobile'));
    final renewedInfn = await auth.refresh(infn);
    expect(renewedInfn!.accessToken, 'id2@$aai');
    expect(appAuth.asked.last, (issuer: aai, client: 'argus-knowledge-hub'));
  });

  test('a session saved before there were two providers is renewed by the main one', () async {
    final appAuth = _FakeAppAuth();
    final old = Session.fromJson({'accessToken': 'a', 'authType': 'oidc', 'refreshToken': 'r'});
    await AppAuthAuthenticator(config, appAuth).refresh(old);
    expect(appAuth.asked.single.issuer, aai);
    expect(const AppConfig(environment: 'd', apiBase: 'x', linkHost: 'x', oidcIssuer: keycloak, oidcClientId: 'c',
        oidcRedirect: 'r', appVersion: '1').providers.length, 1, reason: 'one provider unless a second is set');
  });
}
