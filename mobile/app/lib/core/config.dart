/// Where this build talks to, set at build time (flutter-app-design §6):
/// `--dart-define=ARGUS_ENV=staging --dart-define=ARGUS_API_BASE=https://…` and so on,
/// or by the MDM's managed configuration in a later phase. Never typed by the user.
/// One way to sign in: an OpenID Connect provider and this app's client there. [id] is kept with the session, so
/// it is renewed by the provider that issued it.
class OidcProvider {
  const OidcProvider({required this.id, required this.issuer, required this.clientId, required this.label,
      this.idToken = false});

  final String id; // main | alt
  final String issuer;
  final String clientId;
  final String label;

  /// Send the ID token rather than the access token: an ID token is always addressed to this client (the API's
  /// audience), where a provider's access token may not be — INFN AAI's, without an audience mapper; Google's is
  /// opaque.
  final bool idToken;

  /// Google itself (OIDC_ISSUER=https://accounts.google.com): a refresh token only on `access_type=offline`.
  bool get usesGoogle => Uri.tryParse(issuer)?.host == 'accounts.google.com';
  bool get sendsIdToken => idToken || usesGoogle;
}

class AppConfig {
  const AppConfig({
    required this.environment,
    required this.apiBase,
    required this.linkHost,
    required this.oidcIssuer,
    required this.oidcClientId,
    required this.oidcRedirect,
    required this.appVersion,
    this.offlineRetentionDays = 7,
    this.distribution = 'local',
    this.oidcLabel = 'Sign in with your organization account',
    this.oidcIdToken = false,
    this.altIssuer = '',
    this.altClientId = 'argus-mobile',
    this.altLabel = 'Google or ARGUS account',
  });

  /// The main sign-in's button, and whether it sends its ID token (OIDC_LABEL, OIDC_TOKEN=id).
  final String oidcLabel;
  final bool oidcIdToken;

  /// A second way to sign in, beside the main one (OIDC_ALT_ISSUER, OIDC_ALT_CLIENT_ID, OIDC_ALT_LABEL): with
  /// INFN AAI as the main one, ARGUS's Keycloak — Google, and ARGUS's own accounts. Empty: none.
  final String altIssuer;
  final String altClientId;
  final String altLabel;

  /// The ways to sign in, the main one first.
  List<OidcProvider> get providers => [
        OidcProvider(id: 'main', issuer: oidcIssuer, clientId: oidcClientId, label: oidcLabel, idToken: oidcIdToken),
        if (altIssuer.isNotEmpty)
          OidcProvider(id: 'alt', issuer: altIssuer, clientId: altClientId, label: altLabel),
      ];

  /// The provider a session came from (an older session, saved before there were two: the main one).
  OidcProvider provider(String? id) => providers.firstWhere((p) => p.id == id, orElse: () => providers.first);

  final String environment; // development | staging | production
  final String apiBase; // e.g. https://argus.example/ (no trailing /v1)
  final String linkHost; // the host of universal links and new QR labels
  final String oidcIssuer;
  final String oidcClientId;
  final String oidcRedirect;
  final String appVersion;

  /// Where this build was published: `github` (an APK on a GitHub release — the app looks for newer ones
  /// there), `play` (the store updates it), or `local` (a developer's build: no update check).
  final String distribution;

  /// The repository whose releases carry the APK, for the update check of a `github` build.
  static const releasesRepo = 'infn-argus/argus-knowledge-hub';

  /// How long saved copies and pending commands may live on the device (U22, proposed 7 days).
  final int offlineRetentionDays;

  Duration get offlineRetention => Duration(days: offlineRetentionDays);

  /// The privacy policy: a public page on the web app's host (webapp/public/privacy.html), as the stores require.
  Uri get privacyPolicy => Uri.https(linkHost.isNotEmpty ? linkHost : Uri.parse(apiBase).host, '/privacy.html');

  bool get allowsDeveloperToken => environment != 'production';

  /// Google as the identity provider (OIDC_ISSUER=https://accounts.google.com) rather than
  /// Keycloak: its access tokens are opaque, so the app sends the ID token instead, and it
  /// grants a refresh token on `access_type=offline` rather than the `offline_access` scope.
  bool get usesGoogle => providers.first.usesGoogle;

  static AppConfig fromEnvironment() => const AppConfig(
        environment: String.fromEnvironment('ARGUS_ENV', defaultValue: 'development'),
        apiBase: String.fromEnvironment('ARGUS_API_BASE', defaultValue: 'http://localhost:8000'),
        linkHost: String.fromEnvironment('ARGUS_LINK_HOST', defaultValue: 'localhost'),
        oidcIssuer: String.fromEnvironment('OIDC_ISSUER', defaultValue: 'http://localhost:8081/realms/argus-dev'),
        oidcClientId: String.fromEnvironment('OIDC_CLIENT_ID', defaultValue: 'argus-mobile'),
        oidcRedirect: String.fromEnvironment('OIDC_REDIRECT', defaultValue: 'it.infn.argus.field:/oauthredirect'),
        appVersion: String.fromEnvironment('ARGUS_APP_VERSION', defaultValue: '0.1.0'),
        offlineRetentionDays: int.fromEnvironment('ARGUS_OFFLINE_RETENTION_DAYS', defaultValue: 7),
        distribution: String.fromEnvironment('ARGUS_DISTRIBUTION', defaultValue: 'local'),
        oidcLabel: String.fromEnvironment('OIDC_LABEL', defaultValue: 'Sign in with your organization account'),
        oidcIdToken: String.fromEnvironment('OIDC_TOKEN') == 'id',
        altIssuer: String.fromEnvironment('OIDC_ALT_ISSUER'),
        altClientId: String.fromEnvironment('OIDC_ALT_CLIENT_ID', defaultValue: 'argus-mobile'),
        altLabel: String.fromEnvironment('OIDC_ALT_LABEL', defaultValue: 'Google or ARGUS account'),
      );
}
