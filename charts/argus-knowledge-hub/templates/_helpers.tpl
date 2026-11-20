{{- define "argus.labels" -}}
app.kubernetes.io/part-of: argus-knowledge-hub
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "argus.secretEnv" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ .secret }}
      key: {{ .key }}
{{- end }}

{{/* The API's environment, shared by the API and the portability jobs. */}}
{{- define "argus.apiEnv" -}}
{{- $kcIssuer := printf "https://%s/realms/%s" .Values.hosts.keycloak .Values.keycloak.realm -}}
{{- $providers := .Values.api.extraProviders -}}
{{ include "argus.secretEnv" (dict "name" "DATABASE_URL" "secret" .Values.existingSecret "key" "database-url") }}
{{ include "argus.secretEnv" (dict "name" "TOKEN_PEPPER" "secret" .Values.existingSecret "key" "token-pepper") }}
{{ include "argus.secretEnv" (dict "name" "IMPORT_SECRETS_KEY" "secret" .Values.existingSecret "key" "import-secrets-key") }}
- {name: ATTACHMENTS_DIR, value: /data/attachments}
- {name: ARGUS_PORTABILITY_ROOT, value: /data/portability}
- {name: ARGUS_PORTABILITY_DECRYPTION_KEYS, value: /etc/argus/portability-decryption}
{{- $oidc := .Values.api.oidc | default dict }}
{{- if and (or $oidc.issuer $oidc.jwksUri $oidc.audience) .Values.keycloak.enabled }}
{{- /* Signing in with an external provider (INFN AAI) while the bundled Keycloak still runs: Keycloak's tokens stay
     trusted beside it — the mobile app and Keycloak's own Google sign-in use them. */}}
{{- $providers = append ($providers | default list) (dict "issuer" $kcIssuer "jwks_uri" (printf "http://argus-keycloak:8080/realms/%s/protocol/openid-connect/certs" .Values.keycloak.realm) "audience" .Values.keycloak.clientId) }}
{{- end }}
{{- if or $oidc.issuer $oidc.jwksUri $oidc.audience }}
- {name: OIDC_ISSUER, value: {{ required "api.oidc.issuer is required" $oidc.issuer | quote }}}
- {name: OIDC_JWKS_URI, value: {{ required "api.oidc.jwksUri is required" $oidc.jwksUri | quote }}}
- {name: OIDC_AUDIENCE, value: {{ required "api.oidc.audience is required" $oidc.audience | quote }}}
{{- with $oidc.emailDomains }}
# The domains it gives out the addresses of: an address there that it signs in counts as verified.
- {name: OIDC_EMAIL_DOMAINS, value: {{ join "," . | quote }}}
{{- end }}
{{- else if .Values.keycloak.enabled }}
# The issuer is the public address the browser signs in at; the keys are fetched inside the cluster.
- {name: OIDC_ISSUER, value: {{ $kcIssuer | quote }}}
- {name: OIDC_JWKS_URI, value: "http://argus-keycloak:8080/realms/{{ .Values.keycloak.realm }}/protocol/openid-connect/certs"}
- {name: OIDC_AUDIENCE, value: {{ .Values.keycloak.clientId | quote }}}
{{- end }}
{{- if $oidc.tokenEndpoint }}
- {name: OIDC_TOKEN_ENDPOINT, value: {{ $oidc.tokenEndpoint | quote }}}
- {name: OIDC_REDIRECT_URIS, value: {{ join "," (required "api.oidc.redirectUris is required for confidential login" $oidc.redirectUris) | quote }}}
{{ include "argus.secretEnv" (dict "name" "OIDC_CLIENT_SECRET" "secret" .Values.existingSecret "key" (required "api.oidc.clientSecretKey is required for confidential login" $oidc.clientSecretKey)) }}
{{- end }}
{{- with $providers }}
- name: OIDC_EXTRA_PROVIDERS
  value: {{ toJson . | quote }}
{{- end }}
{{- $mail := .Values.api.mail | default dict }}
{{- if $mail.url }}
- {name: INFN_MAIL_URL, value: {{ $mail.url | quote }}}
- {name: INFN_MAIL_TOKEN_URL, value: {{ required "api.mail.tokenUrl is required with api.mail.url" $mail.tokenUrl | quote }}}
# Optional: without the key the API starts and sends e-mail through SMTP (email.host), if any.
- name: BACK_END_CLIENT_OAUTH
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.existingSecret }}
      key: {{ required "api.mail.clientOAuthSecretKey is required with api.mail.url" $mail.clientOAuthSecretKey }}
      optional: true
{{- end }}
# Links in e-mails and notifications lead to the web app.
- {name: ARGUS_WEB_URL, value: {{ printf "https://%s" .Values.hosts.web | quote }}}
{{- with .Values.email }}
{{- if .host }}
- {name: SMTP_HOST, value: {{ .host | quote }}}
- {name: SMTP_PORT, value: {{ .port | quote }}}
- {name: SMTP_SECURITY, value: {{ .security | quote }}}
{{- with .from }}
- {name: SMTP_FROM, value: {{ . | quote }}}
{{- end }}
- {name: NOTIFY_DIGEST_HOUR, value: {{ .digestHour | quote }}}
# The account the server relays for, when it asks for one: keys username and password of this Secret.
- name: SMTP_USERNAME
  valueFrom: {secretKeyRef: {name: {{ .secret }}, key: username, optional: true}}
- name: SMTP_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .secret }}, key: password, optional: true}}
{{- end }}
{{- end }}
{{- with .Values.iocEngineer }}
{{- if .catalog }}
- {name: ARGUS_IOC_CATALOG, value: {{ .catalog | quote }}}
{{- end }}
- {name: ARGUS_IOC_PR_REPOS, value: {{ .pullRequests.repositories | quote }}}
- {name: ARGUS_IOC_PR_DRAFT, value: {{ .pullRequests.draft | quote }}}
{{- end }}
# Pull requests (the IOC engineer's, and models proposed to the catalogue) only when this key is in the Secret.
- name: ARGUS_GITHUB_TOKEN
  valueFrom: {secretKeyRef: {name: {{ .Values.existingSecret }}, key: ioc-github-token, optional: true}}
{{- if .Values.security.hardened }}
# Not root: git and the libraries keep their caches here.
- {name: HOME, value: /tmp}
{{- end }}
{{- range $k, $v := .Values.api.env }}
- {name: {{ $k }}, value: {{ $v | quote }}}
{{- end }}
{{- end }}

{{/* Pods that may reach the database (NetworkPolicy argus-postgres-clients): the API and its jobs. */}}
{{- define "argus.dbClient" -}}
argus.infn.it/db-client: "true"
{{- end }}

{{/* Pod-level hardening (security.hardened): no Kubernetes token, a non-root user, the runtime's seccomp profile. */}}
{{- define "argus.podSecurity" -}}
{{- if .root.Values.security.hardened }}
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .user }}
  runAsGroup: {{ .user }}
  fsGroup: {{ .user }}
  fsGroupChangePolicy: OnRootMismatch
  seccompProfile: {type: RuntimeDefault}
{{- end }}
{{- end }}

{{/* Container-level hardening (security.hardened): no privilege escalation, no Linux capabilities. */}}
{{- define "argus.containerSecurity" -}}
{{- if .root.Values.security.hardened }}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: {{ .readOnly | default false }}
  capabilities: {drop: [ALL]}
{{- end }}
{{- end }}

{{/* Mounted Secrets: owner-only as root; group-readable (the pod's fsGroup) when the pod runs as another user. */}}
{{- define "argus.secretMode" -}}
{{- if .Values.security.hardened }}0440{{ else }}0400{{ end }}
{{- end }}
