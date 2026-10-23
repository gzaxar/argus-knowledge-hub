import 'package:argus_api/api.dart' show QueryParam;

import 'api_service.dart';

DateTime? _date(Object? v) => v == null ? null : DateTime.tryParse(v.toString())?.toLocal();

/// An activity, or one occurrence of a recurring series (backend models/activity.py): what someone plans, is
/// doing or did. Its [id] is its uid, or `<series uid>@<occurrence key>` for an occurrence not yet touched.
class ActivityItem {
  ActivityItem(this.json)
      : id = '${json['id']}',
        title = '${json['title'] ?? ''}',
        description = json['description']?.toString(),
        status = '${json['status'] ?? 'planned'}',
        visibility = '${json['visibility'] ?? 'workspace'}',
        allDay = json['all_day'] == true,
        plannedStart = _date(json['planned_start']),
        plannedEnd = _date(json['planned_end']),
        dueAt = _date(json['due_at']),
        actualStart = _date(json['actual_start']),
        actualEnd = _date(json['actual_end']),
        createdAt = _date(json['created_at']),
        recurrence = json['recurrence']?.toString(),
        seriesUid = json['series_uid']?.toString(),
        assetUid = json['asset_uid']?.toString(),
        ticketUid = json['ticket_uid']?.toString(),
        ownerUserId = json['owner_user_id']?.toString(),
        assigneeUserId = json['assignee_user_id']?.toString(),
        note = json['note']?.toString(),
        workspaceId = json['workspace_id']?.toString(),
        workspaceIds = [for (final w in (json['workspace_ids'] as List? ?? [json['workspace_id']])) if (w != null) '$w'],
        overdue = json['overdue'] == true,
        mayChange = json['may_change'] != false;

  final Map<String, dynamic> json;
  final String id;
  final String title;
  final String? description;
  final String status; // planned | in_progress | completed | cancelled | skipped
  final String visibility; // workspace | private
  final bool allDay;
  final DateTime? plannedStart, plannedEnd, dueAt, actualStart, actualEnd, createdAt;
  final String? recurrence;
  final String? seriesUid;
  final String? assetUid;
  final String? ticketUid;
  final String? ownerUserId;
  final String? assigneeUserId;
  final String? note;
  /// Its own workspace (where its links are), and every workspace it is in, its own first.
  final String? workspaceId;
  final List<String> workspaceIds;
  final bool overdue;
  final bool mayChange;

  bool get recurring => seriesUid != null;
  bool get open => status == 'planned' || status == 'in_progress';

  /// When it is, for a list: when it was done for done work, else when it is planned.
  DateTime? get when => status == 'completed' ? (actualEnd ?? actualStart) : (plannedStart ?? dueAt ?? actualStart);
}

class ActivityPage {
  ActivityPage(this.items, this.counts, {this.nextOffset, this.total = 0});
  final List<ActivityItem> items;
  final Map<String, int> counts;
  final int? nextOffset;
  final int total;
}

/// What quick capture proposes (backend services/capture.py): nothing is written until the person confirms.
class CaptureProposal {
  CaptureProposal(this.json)
      : kind = '${json['kind'] ?? 'uncertain'}',
        explanation = '${json['explanation'] ?? ''}',
        clarification = json['clarification']?.toString(),
        evidence = [for (final e in (json['evidence'] as List? ?? const [])) '$e'],
        ticket = Map<String, dynamic>.from(json['ticket'] as Map? ?? const {}),
        activity = Map<String, dynamic>.from(json['activity'] as Map? ?? const {}),
        similar = [for (final s in (json['similar_tickets'] as List? ?? const [])) Map<String, dynamic>.from(s as Map)],
        ticketTypes = [for (final t in (json['ticket_types'] as List? ?? const [])) Map<String, dynamic>.from(t as Map)],
        categories = [for (final t in (json['categories'] as List? ?? const [])) Map<String, dynamic>.from(t as Map)],
        impacts = [for (final t in (json['impacts'] as List? ?? const [])) Map<String, dynamic>.from(t as Map)],
        model = json['model']?.toString();

  final Map<String, dynamic> json;
  final String kind; // ticket | activity | uncertain
  final String explanation;
  final String? clarification;
  final List<String> evidence;
  final Map<String, dynamic> ticket;
  final Map<String, dynamic> activity;
  final List<Map<String, dynamic>> similar;
  final List<Map<String, dynamic>> ticketTypes;
  final List<Map<String, dynamic>> categories;
  final List<Map<String, dynamic>> impacts;
  final String? model;

  List<String> get uncertainTicket => [for (final u in (ticket['uncertain'] as List? ?? const [])) '$u'];
  List<String> get uncertainActivity => [for (final u in (activity['uncertain'] as List? ?? const [])) '$u'];
}

/// Activities and quick capture, on the API (backend routers/activities.py).
class ActivityRepository {
  ActivityRepository(this._api);
  final ApiService _api;

  Future<ActivityPage> list({
    String? view,
    DateTime? from,
    DateTime? to,
    String basis = 'planned',
    required String timezone,
    Map<String, String> filters = const {},
    int limit = 200,
    int offset = 0,
  }) async {
    final params = <QueryParam>[
      QueryParam('tz', timezone),
      QueryParam('basis', basis),
      QueryParam('limit', '$limit'),
      QueryParam('offset', '$offset'),
      if (view != null) QueryParam('view', view),
      if (from != null) QueryParam('from', from.toUtc().toIso8601String()),
      if (to != null) QueryParam('to', to.toUtc().toIso8601String()),
      for (final e in filters.entries) QueryParam(e.key, e.value),
    ];
    final r = await _api.json((c) => c.invokeAPI('/v1/activities', 'GET', params, null, {}, {}, null)) as Map;
    return ActivityPage(
      [for (final i in (r['items'] as List? ?? const [])) ActivityItem(Map<String, dynamic>.from(i as Map))],
      {for (final e in ((r['counts'] as Map?) ?? const {}).entries) '${e.key}': (e.value as num).toInt()},
      nextOffset: (r['next_offset'] as num?)?.toInt(),
      total: (r['total'] as num?)?.toInt() ?? 0,
    );
  }

  Future<ActivityItem> get(String id) async => ActivityItem(Map<String, dynamic>.from(await _api.json(
      (c) => c.invokeAPI('/v1/activities/${_seg(id)}', 'GET', [], null, {}, {}, null)) as Map));

  /// One activity or a series; [uid] is chosen here so a retry finds what the first attempt made.
  Future<ActivityItem> create(Map<String, Object?> body, {required String key}) async =>
      ActivityItem(Map<String, dynamic>.from(await _api.json(
          (c) => c.invokeAPI('/v1/activities', 'POST', [], body, {}, {}, 'application/json'),
          idempotencyKey: key) as Map));

  Future<ActivityItem> change(String id, Map<String, Object?> changes, {String scope = 'this'}) async =>
      ActivityItem(Map<String, dynamic>.from(await _api.json((c) => c.invokeAPI(
          '/v1/activities/${_seg(id)}', 'PATCH', [QueryParam('scope', scope)], changes, {}, {},
          'application/json')) as Map));

  Future<ActivityItem> act(String id, String action, {Map<String, Object?> body = const {}, String? key}) async =>
      ActivityItem(Map<String, dynamic>.from(await _api.json(
          (c) => c.invokeAPI('/v1/activities/${_seg(id)}/$action', 'POST', [], body, {}, {},
              'application/json'),
          idempotencyKey: key) as Map));

  Future<CaptureProposal> classify({
    required String transcript,
    required DateTime capturedAt,
    required String timezone,
    String? assetUid,
    Map<String, String>? clarification,
  }) async =>
      CaptureProposal(Map<String, dynamic>.from(await _api.json((c) => c.invokeAPI('/v1/capture/classify', 'POST', [], {
            'transcript': transcript,
            'captured_at': _offset(capturedAt),
            'timezone': timezone,
            'asset_uid': ?assetUid,
            'clarification': ?clarification,
          }, {}, {}, 'application/json')) as Map));
}

/// A local time with its offset, as the server wants it (2026-10-22T16:30:00+02:00).
String _offset(DateTime t) {
  final local = t.toLocal();
  final o = local.timeZoneOffset;
  final sign = o.isNegative ? '-' : '+';
  final h = o.inHours.abs().toString().padLeft(2, '0');
  final m = (o.inMinutes.abs() % 60).toString().padLeft(2, '0');
  final base = local.toIso8601String().split('.').first;
  return '$base$sign$h:$m';
}

String withOffset(DateTime t) => _offset(t);

/// An activity id in a URL path: an occurrence's `@` and `:` are allowed there and kept readable.
String _seg(String id) => Uri.encodeComponent(id).replaceAll('%40', '@').replaceAll('%3A', ':');
