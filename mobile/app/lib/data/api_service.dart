import 'dart:convert';
import 'dart:typed_data' show Uint8List;
import 'dart:io' show Platform;

import 'package:argus_api/api.dart' as api;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;

import '../core/config.dart';
import '../core/problem.dart';
import '../core/session.dart';

/// The one door to the ARGUS API: the generated client, with the headers every request
/// carries (authentication, workspace, client version, device) and every failure turned into a
/// [Problem]. Nothing else in the app talks HTTP (flutter-app-design §2.2).
class ApiService {
  ApiService(this.config, this.sessionOf, {this.onProblem, this.ensureFresh, this.httpClient, this.capturedAt});

  /// The same service, stamping every request with when a queued command was captured.
  ApiService capturing(DateTime at) =>
      ApiService(config, sessionOf, onProblem: onProblem, ensureFresh: ensureFresh, httpClient: httpClient, capturedAt: at);

  /// Set on a service made by [capturing].
  final DateTime? capturedAt;

  final AppConfig config;
  final Session? Function() sessionOf;

  /// Told about every problem before it is thrown: revocation, a signed-out session and a client
  /// too old for the server are handled once, for the whole app, by whoever listens.
  final void Function(Problem problem)? onProblem;

  /// Called before each request, to refresh an access token that is about to expire.
  final Future<void> Function()? ensureFresh;

  /// The transport; replaced only in tests.
  final http.Client? httpClient;

  String get platform => kIsWeb ? 'web' : (Platform.isIOS ? 'ios' : Platform.isAndroid ? 'android' : 'other');

  String get base => config.apiBase.replaceAll(RegExp(r'/+$'), '');

  Map<String, String> headers({String? idempotencyKey, String? ifMatch, DateTime? capturedAt}) {
    final s = sessionOf();
    return {
      'X-ARGUS-Client': 'flutter/${config.appVersion}/$platform',
      if (s != null) 'Authorization': 'Bearer ${s.accessToken}',
      if (s?.workspaceId != null) 'X-Workspace-Id': s!.workspaceId!,
      if (s?.deviceId != null) 'X-ARGUS-Device': s!.deviceId!,
      // A command keeps its key for every retry, so a lost answer never writes twice (§3.2).
      'Idempotency-Key': ?idempotencyKey,
      'If-Match': ?ifMatch,
      // When the person captured a queued command, in server time: the server refuses one older than
      // the offline retention (A65).
      if ((capturedAt ?? this.capturedAt) != null)
        'X-ARGUS-Captured-At': (capturedAt ?? this.capturedAt)!.toUtc().toIso8601String(),
    };
  }

  api.ApiClient _client({String? idempotencyKey, String? ifMatch, DateTime? capturedAt}) {
    final c = api.ApiClient(basePath: base);
    if (httpClient != null) c.client = httpClient!;
    headers(idempotencyKey: idempotencyKey, ifMatch: ifMatch, capturedAt: capturedAt).forEach(c.addDefaultHeader);
    return c;
  }

  /// Run a call of the generated client, turning its failures into problems.
  Future<T> call<T>(Future<T?> Function(api.ApiClient c) body, {String? idempotencyKey, String? ifMatch}) async {
    if (ensureFresh != null) await ensureFresh!();
    Problem problem;
    try {
      final result = await body(_client(idempotencyKey: idempotencyKey, ifMatch: ifMatch));
      if (result != null) return result;
      problem = Problem(ProblemCode.notFound, 'Nothing was returned.');
    } on api.ApiException catch (e) {
      problem = _fromException(e);
    }
    onProblem?.call(problem);
    throw problem;
  }

  /// For operations whose response the contract leaves untyped: the generated client builds the
  /// request (path, parameters, headers) and the JSON body is decoded here, since the generated
  /// deserializer has no case for an untyped value.
  Future<Object?> json(Future<http.Response> Function(api.ApiClient c) body,
      {String? idempotencyKey, String? ifMatch, DateTime? capturedAt}) async {
    final r = await raw((c) => body(c), idempotencyKey: idempotencyKey, ifMatch: ifMatch, capturedAt: capturedAt);
    return r.body;
  }

  /// Like [json], with the status and headers (`202` for a proposed transition, the `ETag`).
  Future<({int status, Object? body, Map<String, String> headers})> raw(
      Future<http.Response> Function(api.ApiClient c) body,
      {String? idempotencyKey, String? ifMatch, DateTime? capturedAt}) async {
    if (ensureFresh != null) await ensureFresh!();
    Problem problem;
    try {
      final r = await body(_client(idempotencyKey: idempotencyKey, ifMatch: ifMatch, capturedAt: capturedAt));
      final text = utf8.decode(r.bodyBytes, allowMalformed: true);
      if (r.statusCode < 400) {
        return (status: r.statusCode, body: text.isEmpty ? null : jsonDecode(text), headers: r.headers);
      }
      problem = Problem.fromResponse(r.statusCode, text);
    } on api.ApiException catch (e) {
      problem = _fromException(e);
    } on FormatException {
      problem = Problem(ProblemCode.unknown, 'ARGUS sent a response this version cannot read.');
    }
    onProblem?.call(problem);
    throw problem;
  }

  /// A file's raw bytes (an attachment, an icon): the generated client decodes every body as JSON text,
  /// which would corrupt binary content, so this reads [http.Response.bodyBytes] directly.
  Future<Uint8List> getBytes(String path) async {
    if (ensureFresh != null) await ensureFresh!();
    final client = httpClient ?? http.Client();
    Problem problem;
    try {
      final r = await client.get(Uri.parse('$base$path'), headers: headers());
      if (r.statusCode < 400) return r.bodyBytes;
      problem = Problem.fromResponse(r.statusCode, utf8.decode(r.bodyBytes, allowMalformed: true));
    } on http.ClientException {
      problem = Problem(ProblemCode.offline, 'ARGUS cannot be reached. Check the network and try again.');
    } finally {
      if (httpClient == null) client.close();
    }
    onProblem?.call(problem);
    throw problem;
  }

  /// One piece of a resumable upload, as raw bytes (the generated method cannot send them).
  Future<Object?> putBytes(String path, Map<String, String> query, List<int> bytes, {String? idempotencyKey}) async {
    if (ensureFresh != null) await ensureFresh!();
    final client = httpClient ?? http.Client();
    Problem problem;
    try {
      final r = await client.put(Uri.parse('$base$path').replace(queryParameters: query),
          headers: {...headers(idempotencyKey: idempotencyKey), 'Content-Type': 'application/octet-stream'},
          body: bytes);
      final text = utf8.decode(r.bodyBytes, allowMalformed: true);
      if (r.statusCode < 400) return text.isEmpty ? null : jsonDecode(text);
      problem = Problem.fromResponse(r.statusCode, text);
    } on http.ClientException {
      problem = Problem(ProblemCode.offline, 'ARGUS cannot be reached. Check the network and try again.');
    } finally {
      if (httpClient == null) client.close();
    }
    onProblem?.call(problem);
    throw problem;
  }

  /// A POST answered with server-sent events (the assistant's chat): each `data:` line's JSON
  /// object as it arrives. The generated client would wait for the whole answer.
  Stream<Map<String, Object?>> events(String path, Object body) async* {
    if (ensureFresh != null) await ensureFresh!();
    final client = httpClient ?? http.Client();
    Problem? problem;
    try {
      final request = http.Request('POST', Uri.parse('$base$path'))
        ..headers.addAll({...headers(), 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
        ..body = jsonEncode(body);
      final r = await client.send(request);
      if (r.statusCode >= 400) {
        problem = Problem.fromResponse(r.statusCode, await r.stream.bytesToString());
      } else {
        await for (final line in r.stream.transform(utf8.decoder).transform(const LineSplitter())) {
          if (!line.startsWith('data:')) continue;
          final event = jsonDecode(line.substring(5).trim());
          if (event is Map) yield event.map((k, v) => MapEntry(k.toString(), v));
        }
      }
    } on http.ClientException {
      problem = Problem(ProblemCode.offline, 'ARGUS cannot be reached. Check the network and try again.');
    } finally {
      if (httpClient == null) client.close();
    }
    if (problem != null) {
      onProblem?.call(problem);
      throw problem;
    }
  }

  Problem _fromException(api.ApiException e) => (e.code == 400 && e.innerException != null)
      ? Problem(ProblemCode.offline, 'ARGUS cannot be reached. Check the network and try again.')
      : Problem.fromResponse(e.code, e.message);

  api.WorkspacesApi workspaces(api.ApiClient c) => api.WorkspacesApi(c);
  api.FieldClientApi field(api.ApiClient c) => api.FieldClientApi(c);
  api.HubApi hub(api.ApiClient c) => api.HubApi(c);
  api.AssetsApi assets(api.ApiClient c) => api.AssetsApi(c);
  api.InstallationsApi installations(api.ApiClient c) => api.InstallationsApi(c);
  api.IssuesApi issues(api.ApiClient c) => api.IssuesApi(c);
  api.DocumentsApi documents(api.ApiClient c) => api.DocumentsApi(c);
  api.LookupApi lookup(api.ApiClient c) => api.LookupApi(c);
  api.MetaApi meta(api.ApiClient c) => api.MetaApi(c);
  api.IntakeApi intake(api.ApiClient c) => api.IntakeApi(c);
  api.UploadsApi uploads(api.ApiClient c) => api.UploadsApi(c);
  api.NotificationsApi notifications(api.ApiClient c) => api.NotificationsApi(c);
  api.SearchApi search(api.ApiClient c) => api.SearchApi(c);
  api.LocationsApi locations(api.ApiClient c) => api.LocationsApi(c);
  api.PackagesApi packages(api.ApiClient c) => api.PackagesApi(c);
  api.GlobalValuesApi globalValues(api.ApiClient c) => api.GlobalValuesApi(c);
  api.SchemasApi schemas(api.ApiClient c) => api.SchemasApi(c);
  api.AiApi ai(api.ApiClient c) => api.AiApi(c);
  api.AssetSubresourcesApi assetSubresources(api.ApiClient c) => api.AssetSubresourcesApi(c);
  api.LabelsApi labels(api.ApiClient c) => api.LabelsApi(c);
  api.GraphApi graph(api.ApiClient c) => api.GraphApi(c);
  api.AttachmentsApi attachments(api.ApiClient c) => api.AttachmentsApi(c);
}
