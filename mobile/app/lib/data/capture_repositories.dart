import 'dart:convert';
import 'dart:typed_data' show Uint8List;

import 'package:argus_api/api.dart' as api;
import 'package:crypto/crypto.dart' show sha256;
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;

import '../core/problem.dart';
import '../domain/capture.dart';
import '../domain/models.dart'
    show AssetLocation, AttributeDef, CockpitItem, IndoorInfo, LinkTarget, LocationObservationItem, MapFeatureItem,
        NearbyHit, PlaceShape, PlacedPoint, PlanInfo, PlanRef,
        QueryHit, QueryResult, RecordKind;
import 'api_service.dart';

Map<String, Object?> _map(Object? o) => o is Map ? o.map((k, v) => MapEntry(k.toString(), v)) : const {};
List<Object?> _list(Object? o) => o is List ? o : const [];
DateTime? _date(Object? o) => o is String ? DateTime.tryParse(o) : null;

List<GuideCheck> parseChecks(Object? guide) => _list(_map(guide)['checks']).map(_map).map((c) => GuideCheck(
      id: (c['id'] ?? '').toString(),
      level: (c['level'] ?? 'info').toString(),
      message: (c['message'] ?? '').toString(),
      field: c['field']?.toString(),
      links: _list(c['links']).map(_map).map((l) => (
            uid: l['uid'].toString(),
            name: (l['name'] ?? l['key'] ?? '').toString(),
            path: (l['path'] ?? '').toString(),
          )).toList(),
    )).toList();

AssistResult parseAssist(Object? body) {
  final r = _map(body);
  return AssistResult(
    runId: r['run_id'].toString(),
    proposals: _map(r['fields']).map((field, v) {
      final f = _map(v);
      return MapEntry(
          field,
          Proposal(
            field: field,
            value: f['value'],
            label: f['label']?.toString(),
            confidence: (f['confidence'] as num?)?.toDouble(),
            evidence: f['evidence']?.toString(),
            grounded: f['grounded'] != false,
            method: (f['method'] ?? 'ai_extracted').toString(),
          ));
    }),
    dropped: _list(r['dropped']).map(_map).map((d) => Dropped(d['field'].toString(), d['reason'].toString())).toList(),
    hypotheses: _list(r['hypotheses']).map((h) => h is Map ? (h['text'] ?? '').toString() : h.toString()).toList(),
    redacted: (r['redacted'] as num?)?.toInt() ?? 0,
    checks: parseChecks(r['guide']),
  );
}

/// The AI Intake and the deterministic guide (revision §23). The server decides; the app shows.
class IntakeRepository {
  IntakeRepository(this._api);
  final ApiService _api;

  Future<AssistResult> assistTicket(String text, Map<String, Object?> draft) async => parseAssist(await _api
      .json((c) => _api.intake(c).assistTicketWithHttpInfo(api.AssistIn(text: text, draft: draft))));

  /// A nameplate photo: the server reads it (§24.6); the device only captured it.
  Future<AssistResult> assistAssetPhoto(PickedPhoto photo, Map<String, Object?> draft) async {
    final file = http.MultipartFile.fromBytes('file', photo.bytes, filename: photo.name,
        contentType: MediaType.parse(photo.mimeType));
    return parseAssist(await _api.json((c) => _api.intake(c).assistFromFileWithHttpInfo('asset', file,
        draft: jsonEncode(draft))));
  }

  Future<List<GuideCheck>> guideTicket(Map<String, Object?> draft) async =>
      parseChecks(await _api.json((c) => _api.intake(c).guideTicketWithHttpInfo(api.GuideIn(draft: draft))));

  Future<List<GuideCheck>> guideAsset(Map<String, Object?> draft) async =>
      parseChecks(await _api.json((c) => _api.intake(c).guideAssetWithHttpInfo(api.GuideIn(draft: draft))));

  /// After the save: which suggestions the person kept (§23.11). Failing to record it loses
  /// nothing the person did, so a failure is swallowed.
  Future<void> recordOutcome(String runId, String recordUid, Map<String, Object?> finalValues) async {
    try {
      await _api.json((c) => _api.intake(c).recordOutcomeWithHttpInfo(
          runId, api.OutcomeIn(recordUid: recordUid, final_: finalValues)));
    } on Problem {
      // the record exists; the outcome is statistics
    }
  }
}

class SchemaRepository {
  SchemaRepository(this._api);
  final ApiService _api;

  Future<List<Map<String, Object?>>> _all() async =>
      _list(await _api.json((c) => _api.schemas(c).listSchemasWithHttpInfo())).map(_map).toList();

  Future<List<TicketKind>> ticketKinds() async => (await _all())
      .where((s) => s['applies_to'] == 'tickets' && s['is_concrete'] != false)
      .map((s) => TicketKind(s['uid'].toString(), s['name'].toString()))
      .toList()
    ..sort((a, b) => a.name.compareTo(b.name));

  Future<List<EquipmentType>> objectTypes() async => (await _all())
      .where((s) => s['applies_to'] == 'objects' && s['is_concrete'] != false)
      .map((s) => EquipmentType(s['uid'].toString(), s['name'].toString()))
      .toList()
    ..sort((a, b) => a.name.compareTo(b.name));

  Future<List<EquipmentType>> documentTypes() async => (await _all())
      .where((s) => s['applies_to'] == 'documents' && s['is_concrete'] != false)
      .map((s) => EquipmentType(s['uid'].toString(), s['name'].toString()))
      .toList()
    ..sort((a, b) => a.name.compareTo(b.name));

  /// The hierarchy of one kind of type: 'objects', 'tickets' or 'documents'.
  Future<TypeTree> tree(String appliesTo) async => TypeTree([
        for (final s in await _all())
          if (s['applies_to'] == appliesTo)
            TypeNode(
              uid: s['uid'].toString(),
              name: (s['name'] ?? '').toString(),
              parentUid: s['parent_schema_uid']?.toString(),
              concrete: s['is_concrete'] != false,
            ),
      ]);

  /// A type's attributes, with its ancestors' folded in (a child's own definition wins on the same
  /// key) — the same rule webapp/src/lib/schemaAttributes.ts effectiveAttributes() applies, so a
  /// record edited here sees the fields the web form would show.
  Future<List<AttributeDef>> effectiveAttributes(String schemaUid) async {
    final all = await _all();
    final byUid = {for (final s in all) s['uid'].toString(): s};
    final chain = <Map<String, Object?>>[];
    final seen = <String>{};
    Map<String, Object?>? current = byUid[schemaUid];
    while (current != null && seen.add(current['uid'].toString())) {
      chain.add(current);
      final parent = current['parent_schema_uid']?.toString();
      current = parent == null ? null : byUid[parent];
    }
    final merged = <String, AttributeDef>{};
    for (final s in chain.reversed) {
      for (final raw in _list(s['attributes']).map(_map)) {
        final def = _attributeDef(raw);
        if (def != null) merged[def.key] = def;
      }
    }
    return merged.values.toList();
  }

  /// [schemaUid] and every type beneath it in the tree — the same set a reference attribute with
  /// includeChildren set accepts (webapp/src/lib/schemaAttributes.ts descendantSchemaUids).
  Future<Set<String>> descendantSchemaUids(String schemaUid) async {
    final all = await _all();
    final children = <String, List<String>>{};
    for (final s in all) {
      final parent = s['parent_schema_uid']?.toString();
      if (parent != null) children.putIfAbsent(parent, () => []).add(s['uid'].toString());
    }
    final out = <String>{};
    final queue = [schemaUid];
    while (queue.isNotEmpty) {
      final uid = queue.removeLast();
      if (out.add(uid)) queue.addAll(children[uid] ?? const []);
    }
    return out;
  }

  AttributeDef? _attributeDef(Map<String, Object?> m) {
    final key = (m['key'] ?? m['name'])?.toString();
    if (key == null || key.isEmpty) return null;
    return AttributeDef(
      key: key,
      name: (m['name'] ?? key).toString(),
      type: (m['type'] ?? 'string').toString(),
      required: m['required'] == true,
      multiValue: m['multiValue'] == true || m['multi_value'] == true,
      minCardinality: (m['minCardinality'] ?? m['min_cardinality']) as int?,
      maxCardinality: (m['maxCardinality'] ?? m['max_cardinality']) as int?,
      options: _list(m['options']).map(_map).map((o) => (id: (o['id'] ?? '').toString(), value: (o['value'] ?? o['id'] ?? '').toString())).toList(),
      regex: m['regex']?.toString(),
      readOnly: m['readOnly'] == true || m['read_only'] == true,
      description: m['description']?.toString(),
      referenceSchemaUid: (m['referenceSchemaUid'] ?? m['reference_schema_uid'])?.toString(),
      includeChildren: m['includeChildren'] == true || m['include_children'] == true,
    );
  }
}

/// Files, sent in pieces with their hash so a weak network can resume (§5.5).
class UploadRepository {
  UploadRepository(this._api, {this.pieceSize = 1024 * 1024});
  final ApiService _api;
  final int pieceSize;

  /// Upload, verify and attach. [key] is the command's own key: each step derives its key from it,
  /// so a retry of the whole command resumes rather than duplicates.
  Future<String> uploadAndAttach(PickedPhoto photo,
      {String? ticketUid, String? assetUid, String? documentUid, String? revisionUid, required String key}) async {
    final digest = sha256.convert(photo.bytes).toString();
    final created = _map(await _api.json(
        (c) => _api.uploads(c).createUploadWithHttpInfo(api.UploadIn(
            filename: photo.name, contentType: photo.mimeType, size: photo.bytes.length, sha256: digest)),
        idempotencyKey: '$key:create'));
    final uid = created['uid'].toString();
    var offset = (created['offset'] as num?)?.toInt() ?? 0;
    while (offset < photo.bytes.length) {
      final end = (offset + pieceSize).clamp(0, photo.bytes.length);
      try {
        final r = _map(await _api.putBytes('/v1/uploads/$uid', {'offset': '$offset'}, photo.bytes.sublist(offset, end)));
        offset = (r['offset'] as num).toInt();
      } on Problem catch (p) {
        // Another attempt got further: resume where the server is.
        final at = p.current?['offset'];
        if (p.code == ProblemCode.conflict && at is num) {
          offset = at.toInt();
        } else {
          rethrow;
        }
      }
    }
    await _api.json((c) => _api.uploads(c).completeUploadWithHttpInfo(uid), idempotencyKey: '$key:complete');
    final attached = _map(await _api.json(
        (c) => ticketUid != null
            ? _api.uploads(c).attachToTicketWithHttpInfo(uid, ticketUid)
            : documentUid != null
                ? _api.uploads(c).attachToDocumentWithHttpInfo(uid, documentUid, revisionUid!)
                : _api.uploads(c).attachToAssetWithHttpInfo(uid, assetUid!),
        idempotencyKey: '$key:attach'));
    return (attached['attachment_uid'] ?? uid).toString();
  }
}

/// Changing tickets: every command carries its own idempotency key, edits carry the version read.
class TicketCommands {
  TicketCommands(this._api);
  final ApiService _api;

  Future<String> create({
    required String uid,
    required String title,
    required String description,
    String? subjectUid,
    String? kindUid,
    Map<String, Object?> attributes = const {},
  }) async {
    final r = _map(await _api.json(
        (c) => _api.issues(c).createIssueWithHttpInfo(api.IssueCreate(
            uid: uid,
            title: title,
            description: description,
            assetUid: subjectUid,
            schemaUid: kindUid,
            attributes: attributes)),
        idempotencyKey: 'ticket:$uid'));
    return r['uid'].toString();
  }

  Future<List<Comment>> comments(String ticketUid) async =>
      _list(await _api.json((c) => _api.issues(c).listIssueCommentsWithHttpInfo(ticketUid)))
          .map(_map)
          .map((m) => Comment(
              uid: m['uid'].toString(),
              author: (m['author'] ?? '').toString(),
              body: (m['body'] ?? '').toString(),
              at: _date(m['created_at'])))
          .toList();

  Future<void> comment(String ticketUid, String commentUid, String body) async {
    await _api.json(
        (c) => _api.issues(c).createIssueCommentWithHttpInfo(
            ticketUid, api.IssueCommentCreate(uid: commentUid, body: body)),
        idempotencyKey: 'comment:$commentUid');
  }

  Future<List<AttachmentInfo>> attachments(String ticketUid) async =>
      _list(await _api.json((c) => _api.issues(c).listIssueAttachmentsWithHttpInfo(ticketUid)))
          .map(_map)
          .map((m) => AttachmentInfo(
              uid: m['uid'].toString(),
              filename: (m['filename'] ?? '').toString(),
              mimeType: m['mime_type']?.toString(),
              size: (m['file_size'] as num?)?.toInt()))
          .toList();

  Future<List<TransitionOption>> transitions(String ticketUid) async =>
      _list(_map(await _api.json((c) => _api.issues(c).listTransitionsWithHttpInfo(ticketUid)))['transitions'])
          .map(_map)
          .map((t) => TransitionOption(
              to: t['to'].toString(),
              name: (t['name'] ?? 'Move').toString(),
              toName: (t['to_name'] ?? t['to']).toString(),
              category: t['category']?.toString(),
              requires: _list(t['requires']).map((e) => e.toString()).toList()))
          .toList();

  Future<TransitionResult> transition(String ticketUid, String to,
      {required int version, required String key, String? comment, String? resolution}) async {
    final r = await _api.raw(
        (c) => _api.issues(c).transitionIssueWithHttpInfo(
            ticketUid, api.TransitionIn(to: to, comment: comment, resolution: resolution)),
        idempotencyKey: key,
        ifMatch: '"$version"');
    return TransitionResult(state: (_map(r.body)['state'] ?? '').toString(), proposed: r.status == 202);
  }
}

/// Registering Equipment the person has in front of them (§24.8: never from a name).
class EquipmentCommands {
  EquipmentCommands(this._api);
  final ApiService _api;

  Future<String> register({
    required String uid,
    required String typeUid,
    required String name,
    String? key,
    required Map<String, Object?> attributes,
  }) async {
    final r = _map(await _api.json(
        (c) => _api.assets(c).createAssetWithHttpInfo(api.AssetCreate(
            uid: uid, schemaUid: typeUid, name: name, key: key, attributes: attributes)),
        idempotencyKey: 'asset:$uid'));
    return r['uid'].toString();
  }
}

class NotificationRepository {
  NotificationRepository(this._api);
  final ApiService _api;

  /// The inbox: the latest hundred, read or not, from every workspace the person can open — a ticket assigned
  /// in another workspace is here whichever workspace the app is in.
  Future<List<NotificationItem>> mine() async =>
      _list(await _api.json((c) => _api.notifications(c).myNotificationsEverywhereWithHttpInfo(includeRead: true)))
          .map(_map)
          .map((n) => NotificationItem(
              id: (n['id'] as num).toInt(),
              title: (n['title'] ?? '').toString(),
              issueUid: n['issue_uid']?.toString(),
              kind: n['kind']?.toString(),
              read: n['read'] == true,
              at: _date(n['created_at']),
              subject: _map(n['detail'])['subject']?.toString(),
              subjectUid: _map(n['detail'])['uid']?.toString(),
              workspaceId: n['workspace_id']?.toString(),
              workspaceName: n['workspace_name']?.toString()))
          .toList();

  /// Unread news in every workspace, newer than [after]: what the background check shows on the phone.
  Future<List<NotificationItem>> everywhere({int after = 0}) async =>
      _list(await _api.json((c) => _api.notifications(c).myNotificationsEverywhereWithHttpInfo(after: after)))
          .map(_map)
          .map((n) => NotificationItem(
              id: (n['id'] as num).toInt(),
              title: (n['title'] ?? '').toString(),
              issueUid: n['issue_uid']?.toString(),
              kind: n['kind']?.toString(),
              at: _date(n['created_at']),
              subject: _map(n['detail'])['subject']?.toString(),
              subjectUid: _map(n['detail'])['uid']?.toString(),
              workspaceId: n['workspace_id']?.toString(),
              workspaceName: n['workspace_name']?.toString()))
          .toList();

  Future<List<WorkspaceSubscription>> subscriptions() async =>
      _list(await _api.json((c) => _api.notifications(c).mySubscriptionsWithHttpInfo()))
          .map(_map)
          .map((m) => WorkspaceSubscription(
              workspaceId: m['workspace_id'].toString(),
              workspaceName: (m['workspace_name'] ?? m['workspace_id']).toString(),
              tickets: m['tickets'] == true,
              documents: m['documents'] == true,
              assets: m['assets'] == true))
          .toList();

  Future<void> subscribe(WorkspaceSubscription s) async {
    await _api.json((c) => _api.notifications(c).setSubscriptionWithHttpInfo(
        s.workspaceId, api.SubscriptionIn(tickets: s.tickets, documents: s.documents, assets: s.assets)));
  }

  Future<void> markRead(int id) async {
    await _api.json((c) => _api.notifications(c).markReadEverywhereWithHttpInfo(id));
  }

  Future<void> markAllRead() async {
    await _api.json((c) => _api.notifications(c).markAllReadEverywhereWithHttpInfo());
  }

  /// Whether the person follows this piece of equipment ('asset') or document ('document').
  Future<bool> following(String subject, String uid) async =>
      _map(await _api.json((c) => _api.notifications(c).followingStateWithHttpInfo(subject, uid)))['following'] ==
      true;

  Future<bool> setFollowing(String subject, String uid, bool follow) async => _map(await _api.json((c) => follow
          ? _api.notifications(c).followRecordWithHttpInfo(subject, uid)
          : _api.notifications(c).unfollowRecordWithHttpInfo(subject, uid)))['following'] ==
      true;

  /// The person's open tickets in every workspace: assigned to them, reported by them, or watched.
  Future<List<CockpitItem>> myWork() async =>
      _list(await _api.json((c) => _api.hub(c).myWorkWithHttpInfo())).map(_map).map((t) => CockpitItem(
            kind: RecordKind.ticket,
            uid: t['uid'].toString(),
            label: (t['title'] ?? t['uid']).toString(),
            sub: [
              switch (t['why']) { 'assigned' => 'assigned to you', 'reported' => 'you reported it', _ => 'watching' },
              t['state'],
              t['workspace_name'],
            ].whereType<Object>().join(' · '),
            at: _date(t['updated_at']),
            workspaceId: t['workspace_id']?.toString(),
          )).toList();
}

/// Advanced query, over tickets, equipment or documents.
class QueryRepository {
  QueryRepository(this._api);
  final ApiService _api;

  Future<QueryResult> run(String entity, String jql, {int limit = 50}) async {
    final r = _map(await _api.json((c) => _api.search(c).searchJqlWithHttpInfo(entity, jql: jql, limit: limit)));
    final kind = switch (entity) { 'tickets' => RecordKind.ticket, 'documents' => RecordKind.document, _ => RecordKind.asset };
    return QueryResult(
      total: (r['total'] as num?)?.toInt() ?? 0,
      capped: r['capped'] == true,
      items: _list(r['items']).map(_map).map((m) => QueryHit(
            kind: kind,
            uid: m['uid'].toString(),
            key: (m['key'] ?? m['code'] ?? m['source_key'])?.toString(),
            title: (m['title'] ?? m['name'] ?? m['uid']).toString(),
            sub: [m['state'] ?? m['type'], m['priority']].whereType<Object>().join(' · '),
            workspaceId: m['workspace_id']?.toString(),
            workspaceName: m['workspace_name']?.toString(),
          )).toList(),
    );
  }
}


/// Places: a record's location, field observations of it and their review, and what is near a point.
class LocationRepository {
  LocationRepository(this._api);
  final ApiService _api;

  static double? _d(Object? v) => (v as num?)?.toDouble();

  static PlacedPoint? _point(Object? raw) {
    final m = raw is Map ? raw.map((k, v) => MapEntry(k.toString(), v)) : null;
    if (m == null) return null;
    return PlacedPoint(
        latitude: _d(m['latitude'])!,
        longitude: _d(m['longitude'])!,
        accuracy: _d(m['accuracy_m']),
        source: m['source']?.toString(),
        at: _date(m['confirmed_at'] ?? m['valid_from']),
        reviewer: m['reviewer']?.toString());
  }

  static LocationObservationItem _observation(Map<String, Object?> m) {
    final record = _map(m['record']);
    return LocationObservationItem(
        id: (m['id'] as num).toInt(),
        status: (m['status'] ?? '').toString(),
        latitude: _d(m['latitude'])!,
        longitude: _d(m['longitude'])!,
        accuracy: _d(m['accuracy_m']),
        distance: _d(m['distance_m']),
        observedBy: m['observed_by']?.toString(),
        at: _date(m['observed_at']),
        record: record.isEmpty
            ? null
            : LinkTarget(kind: RecordKind.asset, uid: record['uid'].toString(), title: record['name']?.toString(),
                key: record['key']?.toString(), subtitle: record['type']?.toString()),
        approved: _point(m['approved']));
  }

  Future<AssetLocation> get(String uid) async {
    final r = _map(await _api.json((c) => _api.locations(c).getLocationWithHttpInfo(uid)));
    return AssetLocation(
        locatable: r['locatable'] == true,
        layer: r['map_layer']?.toString(),
        hidden: r['hidden'] == true,
        current: _point(r['location']),
        observations: _list(r['observations']).map(_map).map(_observation).toList(),
        route: _shape(r['route']),
        outline: _shape(r['outline']));
  }

  static PlaceShape? _shape(Object? raw) {
    final m = raw is Map ? raw.map((k, v) => MapEntry(k.toString(), v)) : null;
    if (m == null) return null;
    return PlaceShape.fromGeoJson((m['role'] ?? 'position').toString(), m['geometry'],
        base: _d(m['base_m']), top: _d(m['top_m']), length: _d(m['length_m']), area: _d(m['area_m2']));
  }

  static PlanRef? _planRef(Object? raw) {
    final m = raw is Map ? raw.map((k, v) => MapEntry(k.toString(), v)) : null;
    if (m == null) return null;
    return PlanRef(uid: '${m['uid']}', name: '${m['name'] ?? ''}', width: _d(m['width_px']) ?? 1, height: _d(m['height_px']) ?? 1);
  }

  /// Where the record is inside: its place, floor and point on a plan, and the places that place is in.
  Future<IndoorInfo> indoors(String uid) async {
    final r = _map(await _api.json((c) => c.invokeAPI('/v1/assets/$uid/indoors', 'GET', [], null, {}, {}, null)));
    final p = _map(r['placement']);
    final place = _map(p['place']);
    return IndoorInfo(
        placeUid: place['uid']?.toString(),
        placeName: place['name']?.toString(),
        levelName: _map(p['level'])['name']?.toString(),
        plan: _planRef(p['plan']),
        x: _d(p['x']),
        y: _d(p['y']),
        chain: [for (final c in _list(r['in']).map(_map)) '${c['name']}'],
        chainUids: [for (final c in _list(r['in']).map(_map)) '${c['uid']}'],
        contents: _list(r['contents']).length);
  }

  /// A floor plan and the records placed on it.
  Future<PlanInfo> plan(String uid) async {
    final m = _map(await _api.json((c) => c.invokeAPI('/v1/plans/$uid', 'GET', [], null, {}, {}, null)));
    return PlanInfo(
        ref: _planRef(m)!,
        mime: '${m['mime_type'] ?? 'image/png'}',
        placeUid: _map(m['place'])['uid']?.toString(),
        placeName: _map(m['place'])['name']?.toString(),
        levelName: _map(m['level'])['name']?.toString(),
        onMap: m['corners'] != null,
        placed: [
          for (final p in _list(m['placed']).map(_map))
            (uid: '${p['uid']}', name: '${p['name'] ?? ''}', x: _d(p['x']) ?? 0, y: _d(p['y']) ?? 0),
        ]);
  }

  /// The floor plans of these places (a room's floor plan is usually its building's), or — for a record with
  /// only a position — those placed on the map around it.
  Future<List<({PlanRef plan, String? level, String? place})>> plansFor(List<String> places,
      {double? lat, double? lon}) async {
    final out = <({PlanRef plan, String? level, String? place})>[];
    void add(Map<String, Object?> m) {
      final ref = _planRef(m);
      if (ref != null && !out.any((p) => p.plan.uid == ref.uid)) {
        out.add((plan: ref, level: _map(m['level'])['name']?.toString(), place: _map(m['place'])['name']?.toString()));
      }
    }
    for (final uid in places) {
      try {
        final r = _map(await _api.json((c) => c.invokeAPI('/v1/assets/$uid/levels', 'GET', [], null, {}, {}, null)));
        _list(r['plans']).map(_map).forEach(add);
      } on Problem {
        // a place this person may not see has no plans for them
      }
    }
    if (places.isEmpty && lat != null && lon != null) {
      const d = 0.002; // about 200 m
      final bbox = [lon - d, lat - d, lon + d, lat + d].map((v) => v.toStringAsFixed(6)).join(',');
      _list(await _api.json((c) => c.invokeAPI('/v1/map/plans', 'GET', [api.QueryParam('bbox', bbox)], null, {}, {}, null)))
          .map(_map)
          .forEach(add);
    }
    return out;
  }

  /// The plan's picture (PNG, JPEG or SVG).
  Future<Uint8List> planImage(String uid) => _api.getBytes('/v1/plans/$uid/image');

  /// Place the record at a point of a plan (in [placeUid], or the place it is in now, or the plan's place). A plan
  /// placed on the map gives it its position too.
  Future<void> placeOnPlan(String uid, {required String planUid, required double x, required double y, String? placeUid}) =>
      _api.json((c) => c.invokeAPI('/v1/assets/$uid/indoors', 'PUT', [],
          {'plan_uid': planUid, 'x': x, 'y': y, 'place_uid': ?placeUid}, {}, {}, 'application/json'));

  /// The records with a location in an area of the map — their positions, routes and outlines — that the person
  /// may see (the same rules as a list).
  Future<List<MapFeatureItem>> features(
      {required double south, required double west, required double north, required double east}) async {
    final bbox = [west, south, east, north].map((v) => v.toStringAsFixed(6)).join(',');
    final r = _map(await _api.json(
        (c) => c.invokeAPI('/v1/map/features', 'GET', [api.QueryParam('bbox', bbox)], null, {}, {}, null)));
    final out = <MapFeatureItem>[];
    for (final f in _list(r['features']).map(_map)) {
      final p = _map(f['properties']);
      final shape = PlaceShape.fromGeoJson((p['role'] ?? 'position').toString(), f['geometry'],
          base: _d(p['base_m']), top: _d(p['top_m']));
      if (shape == null) continue;
      out.add(MapFeatureItem(
          target: LinkTarget(kind: RecordKind.asset, uid: p['uid'].toString(), title: p['name']?.toString(),
              key: p['key']?.toString(), subtitle: p['type']?.toString(), workspaceId: p['workspace_id']?.toString()),
          shape: shape,
          layer: p['map_layer']?.toString(),
          status: p['status']?.toString()));
    }
    return out;
  }

  /// Where the person sees the record now: it never moves it; the answer says whether it agrees with the
  /// approved location or waits for review.
  Future<LocationObservationItem> observe(String uid, double lat, double lon, {double? accuracy}) async =>
      _observation(_map(await _api.json((c) => _api.locations(c).observeWithHttpInfo(
          uid, api.ObservationIn(latitude: lat, longitude: lon, accuracyM: accuracy)))));

  Future<List<NearbyHit>> nearby(double lat, double lon, {double radius = 200}) async {
    final r = _map(await _api.json((c) => _api.locations(c).mapNearbyWithHttpInfo(lat, lon, radiusM: radius)));
    return _list(r['features']).map(_map).map((f) {
      final p = _map(f['properties']);
      return NearbyHit(
          target: LinkTarget(kind: RecordKind.asset, uid: p['uid'].toString(), title: p['name']?.toString(),
              key: p['key']?.toString(), subtitle: p['type']?.toString(), workspaceId: p['workspace_id']?.toString()),
          distance: _d(p['distance_m']) ?? 0,
          layer: p['map_layer']?.toString());
    }).toList();
  }

  Future<List<LocationObservationItem>> reviews() async =>
      _list(await _api.json((c) => _api.locations(c).locationReviewsWithHttpInfo()))
          .map(_map).map(_observation).toList();

  Future<void> decide(int id, {required bool accept}) async {
    await _api.json((c) => accept
        ? _api.locations(c).acceptObservationWithHttpInfo(id, api.DecisionIn())
        : _api.locations(c).rejectObservationWithHttpInfo(id, api.DecisionIn()));
  }
}

/// What the current workspace's packages let it do: a workspace of records only (contracts, technology
/// transfer) has no map, so the app does not offer one.
class CapabilitiesRepository {
  CapabilitiesRepository(this._api);
  final ApiService _api;

  Future<Set<String>> features(String workspaceId) async {
    final r = _map(await _api.json((c) => _api.packages(c).workspaceCapabilitiesWithHttpInfo(workspaceId)));
    final f = _map(r['features']);
    return {for (final e in f.entries) if (e.value == true) e.key};
  }
}
