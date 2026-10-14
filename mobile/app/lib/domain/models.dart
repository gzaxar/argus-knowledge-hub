/// What the screens work with. Transfer objects (generated from the API contract) and local
/// persistence records are mapped to these at the repository boundary (flutter-app-design §4.1).
library;

class WorkspaceChoice {
  const WorkspaceChoice({required this.id, required this.name, required this.canCreate, required this.canReadTickets});

  final String id;
  final String name;
  final bool canCreate;
  final bool canReadTickets;
}

enum RecordKind { asset, position, installation, document, ticket, review }

/// Where a link, a scanned label or a search hit leads.
class LinkTarget {
  const LinkTarget(
      {required this.kind, required this.uid, this.title, this.subtitle, this.recordUid, this.workspaceId, this.key});

  final RecordKind kind;
  final String uid;
  final String? title;
  final String? subtitle;
  final String? recordUid; // for a review item: the record it is about
  final String? workspaceId; // the workspace it is opened in, when the server said
  final String? key; // its key or code, shown beside the title when keys are shown

  String get route => inWorkspace(switch (kind) {
        RecordKind.asset || RecordKind.position => '/asset/$uid',
        RecordKind.installation => '/asset/${recordUid ?? uid}',
        RecordKind.document => '/document/$uid',
        RecordKind.ticket => '/ticket/$uid',
        RecordKind.review => '/asset/${recordUid ?? uid}',
      }, workspaceId);
}

/// A record's route that opens it in its own workspace (`?ws=`): the app moves there when it is another.
String inWorkspace(String route, String? workspaceId) =>
    workspaceId == null || workspaceId.isEmpty ? route : '$route?ws=${Uri.encodeQueryComponent(workspaceId)}';

class SearchResults {
  const SearchResults({this.assets = const [], this.tickets = const [], this.documents = const []});

  final List<LinkTarget> assets;
  final List<LinkTarget> tickets;
  final List<LinkTarget> documents;

  bool get isEmpty => assets.isEmpty && tickets.isEmpty && documents.isEmpty;
}

/// A temporal value as ARGUS stores it (revision §8.2): a nominal instant and its precision.
class When {
  const When(this.nominal, this.precision);

  final DateTime? nominal;
  final String precision; // instant | day | month | year | open

  static When? fromJson(Object? v) {
    if (v is! Map) return null;
    if (v['kind'] == 'open') return const When(null, 'open');
    final nominal = v['nominal'] is String ? DateTime.tryParse(v['nominal'] as String) : null;
    return When(nominal, (v['precision'] ?? 'instant').toString());
  }
}

/// The other side of an Installation, as briefly as the record screen needs it.
class RecordBrief {
  const RecordBrief({this.uid, this.key, this.name, this.type, this.restricted = false, this.schemaUid});

  final String? uid; // null when restricted
  final String? key;
  final String? name;
  final String? type;
  final bool restricted;
  final String? schemaUid;

  String get label => restricted ? 'Restricted record' : [key, name].whereType<String>().join(' · ');
}

class InstallationInfo {
  const InstallationInfo({
    required this.uid,
    required this.status,
    required this.temporalState,
    this.certainty,
    this.position,
    this.asset,
    this.from,
    this.until,
  });

  final String uid;
  final String status; // Proposed | Confirmed | Rejected
  final String temporalState; // Planned | Current | Future | Ended
  final String? certainty; // definite | possible
  final RecordBrief? position;
  final RecordBrief? asset;
  final When? from;
  final When? until;

  bool get current => temporalState == 'Current';
}

class TicketSummary {
  const TicketSummary({required this.uid, required this.title, required this.state, this.priority, this.open = true});

  final String uid;
  final String title;
  final String state;
  final String? priority;
  final bool open;
}

class DocumentSummary {
  const DocumentSummary({required this.uid, required this.code, required this.title, this.state, this.reviewOverdue = false});

  final String uid;
  final String code;
  final String title;
  final String? state;
  final bool reviewOverdue;
}

/// Everything the record screen shows about Equipment or a Position.
class AssetDetail {
  const AssetDetail({
    required this.uid,
    required this.key,
    required this.name,
    required this.type,
    required this.typePath,
    required this.recordStatus,
    required this.attributes,
    required this.isPosition,
    this.installations = const [],
    this.tickets = const [],
    this.documents = const [],
    this.relations = const [],
    this.processing = false,
    this.restricted,
    this.avatarIconUid,
    this.version,
    required this.schemaUid,
    this.isGlobal = false,
    this.inboundRelationUids = const [],
    this.outboundRelationUids = const [],
  });

  final String uid;
  final String key;
  final String name;
  final String type;
  final List<String> typePath;
  final String recordStatus;
  final Map<String, Object?> attributes;
  final bool isPosition;
  final List<InstallationInfo> installations;
  final List<TicketSummary> tickets;
  final List<DocumentSummary> documents;
  /// What this record points at, and what points at it (flutter-app-design: a smaller twin of the web's
  /// relation graph — one hop, enough to see what is connected and jump to it).
  final List<RelationItem> relations;
  final bool processing;
  final String? restricted;
  final String? avatarIconUid;
  /// The record version, for editing it (If-Match).
  final int? version;
  final String schemaUid;
  final bool isGlobal;
  /// The raw relation-cache uids the record carries (not the enriched [relations] above, which is a
  /// merged view for display): an edit must send these back unchanged, along with [isGlobal] and
  /// [avatarIconUid] — the server treats the whole PUT body as the record's display/caching state, not
  /// a diff of only the fields the client means to change, and a generated client can't omit a field
  /// it didn't set (it serializes null/empty instead), so leaving these out would clear them.
  final List<String> inboundRelationUids;
  final List<String> outboundRelationUids;

  List<InstallationInfo> get current => installations.where((i) => i.current && i.status != 'Rejected').toList();
  List<RelationItem> get outbound => relations.where((r) => r.direction == 'out').toList();
  List<RelationItem> get inbound => relations.where((r) => r.direction == 'in').toList();
}

/// One edge of the relation graph, already resolved to the neighbour's name (hub.neighbours on the server).
class RelationItem {
  const RelationItem({
    required this.uid,
    required this.key,
    required this.name,
    required this.type,
    required this.relation,
    required this.direction, // 'in' | 'out'
  });

  final String uid;
  final String key;
  final String name;
  final String type;
  final String relation;
  final String direction;
}

/// One entry of an object's imported or recorded history (not the live ledger audit — the migrated trail
/// and anything added by hand, the same list the web app shows under "History").
class HistoryEntry {
  const HistoryEntry({required this.uid, required this.type, required this.author, required this.details, this.at});

  final String uid;
  final String type;
  final String author;
  final String details;
  final DateTime? at;
}

class TicketDetail {
  const TicketDetail({
    required this.uid,
    required this.title,
    required this.state,
    this.description,
    this.priority,
    this.assetUid,
    this.occurredFrom,
    this.version = 1,
    this.attributes = const {},
    this.schemaUid,
  });

  final String uid;
  final String title;
  final String state;
  final String? description;
  final String? priority;
  final String? assetUid;
  /// The ticket's type, whose attributes the edit form offers.
  final String? schemaUid;
  final When? occurredFrom;
  final int version; // sent back as If-Match with a change (flutter-app-design §3.3)
  final Map<String, Object?> attributes;

  /// A closure proposed from the field, waiting for a person online (A70).
  Map<String, Object?>? get proposedTransition {
    final p = attributes['argus_proposed_transition'];
    return p is Map ? p.map((k, v) => MapEntry(k.toString(), v)) : null;
  }

  String? get impact => attributes['argus_impact']?.toString();
}

class DocumentDetail {
  const DocumentDetail({
    required this.uid,
    required this.code,
    required this.title,
    required this.authorityLevel,
    this.revisionState,
    this.revisionNumber,
    this.body,
    this.nextReviewDue,
    this.supersededBy,
    this.steps = const [],
    this.documentTypeUid,
  });

  /// The document's type, placed in the hierarchy on screen.
  final String? documentTypeUid;

  final String uid;
  final String code;
  final String title;
  final String authorityLevel;
  final String? revisionState;
  final int? revisionNumber;
  final String? body;
  final DateTime? nextReviewDue;
  final String? supersededBy;
  final List<String> steps;

  bool get approved => revisionState == 'published' || revisionState == 'approved';
  bool get outdated => supersededBy != null || (nextReviewDue != null && nextReviewDue!.isBefore(DateTime.now()));
}

/// One of a type's attributes, as the schema defines it (mirrors webapp/src/api/types.ts
/// SchemaAttribute — the web app's SchemaAttribute and this stay in step by hand, since the field
/// contract does not expose the admin schema-editing shape).
class AttributeDef {
  const AttributeDef({
    required this.key,
    required this.name,
    required this.type,
    this.required = false,
    this.multiValue = false,
    this.minCardinality,
    this.maxCardinality,
    this.options = const [],
    this.regex,
    this.readOnly = false,
    this.description,
    this.referenceSchemaUid,
    this.includeChildren = false,
  });

  final String key;
  final String name;
  final String type; // string | text | integer | float | boolean | date | datetime | enumeration | reference | ...
  final bool required;
  final bool multiValue;
  final int? minCardinality;
  final int? maxCardinality;
  final List<({String id, String value})> options;
  final String? regex;
  final bool readOnly;
  final String? description;
  final String? referenceSchemaUid;
  final bool includeChildren;

  /// Kinds the field client can edit with a plain field. The rest (attachment, user, current_user,
  /// group) need pickers the web app has and the field app does not yet — shown read-only there,
  /// rather than offering a text box that silently cannot hold a valid value.
  static const editableTypes = {
    'string', 'text', 'integer', 'float', 'boolean', 'date', 'datetime', 'enumeration', 'reference',
  };
  bool get editable => !readOnly && editableTypes.contains(type);
}

/// A ticket in a list: enough to choose one to open.
class TicketListItem {
  const TicketListItem({
    required this.uid,
    required this.title,
    required this.state,
    this.priority,
    this.assignee,
    this.assetUid,
    this.updatedAt,
    this.createdAt,
    this.schemaUid,
    this.closed = false,
  });

  final String uid;
  final String title;
  final String state;
  final String? priority;
  final String? assignee;
  final String? assetUid;
  final DateTime? updatedAt;
  final DateTime? createdAt;
  final String? schemaUid;
  final bool closed;
}

/// A document in a list. [published] is whether it has a revision to work from at all.
class DocumentListItem {
  const DocumentListItem({
    required this.uid,
    required this.code,
    required this.title,
    required this.published,
    this.documentTypeUid,
    this.updatedAt,
    this.createdAt,
    this.retired = false,
    this.shared = false,
    this.workspaceId,
  });

  final String uid;
  final String code;
  final String title;
  final bool published;
  /// Readable in every workspace; [workspaceId] is the one it belongs to (and the only one that edits it).
  final bool shared;
  final String? workspaceId;
  final String? documentTypeUid;
  final DateTime? updatedAt;
  final DateTime? createdAt;
  final bool retired;
}

/// One revision of a document: drafted, sent for review, approved, then published (the one to work from).
class DocumentRevision {
  const DocumentRevision({
    required this.uid,
    required this.number,
    required this.state,
    this.body,
    this.authoredBy,
    this.approvedBy,
    this.reviewComment,
    this.updatedAt,
  });

  final String uid;
  final int number;
  final String state; // draft | in_review | approved | published | superseded | retired (a rejection: draft again)
  final String? body;
  final String? authoredBy;
  final String? approvedBy;
  final String? reviewComment;
  final DateTime? updatedAt;

  /// Still being written or decided on, so it is where work on the document continues.
  bool get open => state == 'draft' || state == 'in_review' || state == 'approved';
}

/// One line of the cockpit: a record, ticket or document and where it leads.
class CockpitItem {
  const CockpitItem(
      {required this.kind, required this.uid, required this.label, this.sub, this.at, this.count, this.workspaceId,
      this.key});

  final RecordKind kind;
  final String uid;
  final String label;
  final String? sub;
  final DateTime? at;
  final int? count; // a hotspot's open tickets
  final String? workspaceId; // set when it may be in another workspace than the app's
  final String? key; // its key or code, shown when keys are shown

  String get path => inWorkspace(switch (kind) {
        RecordKind.ticket => '/ticket/$uid',
        RecordKind.document => '/document/$uid',
        _ => '/asset/$uid',
      }, workspaceId);
}

/// A row of an advanced query.
class QueryHit {
  const QueryHit({required this.kind, required this.uid, required this.key, required this.title, this.sub,
      this.workspaceId, this.workspaceName});

  final RecordKind kind;
  final String uid;
  final String? key;
  final String title;
  final String? sub;
  final String? workspaceId;
  final String? workspaceName;

  String get route => LinkTarget(kind: kind, uid: uid, workspaceId: workspaceId).route;
}

class QueryResult {
  const QueryResult({required this.total, required this.items, this.capped = false});

  final int total;
  final List<QueryHit> items;
  final bool capped;
}

/// The operations cockpit (the web's home): what is assigned to me, where tickets pile up, what waits for
/// review, and what changed lately across records, tickets and documents. A section the person may not
/// read is absent, not empty.
class Cockpit {
  const Cockpit({
    this.mine = const [],
    this.openTickets,
    this.byState = const {},
    this.hotspots = const [],
    this.awaitingReview = const [],
    this.reviewOverdue = const [],
    this.recent = const [],
    this.totalTickets,
    this.unassigned,
    this.withoutAsset,
    this.inReview,
    this.notLinked,
    this.assets,
  });

  final List<CockpitItem> mine;
  final int? openTickets; // null: tickets not readable here
  final int? totalTickets;
  final int? unassigned; // open, nobody on it
  final int? withoutAsset; // open, linked to no equipment
  final int? inReview; // revisions waiting for approval; null: documents not readable here
  final int? notLinked; // documents that apply to no equipment or type yet
  final int? assets; // owned by this workspace; null: records not readable here
  final Map<String, int> byState;
  final List<CockpitItem> hotspots;
  final List<CockpitItem> awaitingReview;
  final List<CockpitItem> reviewOverdue;
  final List<CockpitItem> recent;
}


/// A record's place on the map: whether its type may have one, its approved location (with where it came
/// from), and what the field observed (services/spatial on the server).
class AssetLocation {
  const AssetLocation(
      {required this.locatable, this.layer, this.hidden = false, this.current, this.observations = const []});

  final bool locatable;
  final String? layer;
  final bool hidden; // its type restricts the location from this person
  final PlacedPoint? current;
  final List<LocationObservationItem> observations;
}

class PlacedPoint {
  const PlacedPoint(
      {required this.latitude, required this.longitude, this.accuracy, this.source, this.at, this.reviewer});

  final double latitude;
  final double longitude;
  final double? accuracy;
  final String? source;
  final DateTime? at;
  final String? reviewer;
}

class LocationObservationItem {
  const LocationObservationItem(
      {required this.id, required this.status, required this.latitude, required this.longitude, this.accuracy,
      this.distance, this.observedBy, this.at, this.record, this.approved});

  final int id;
  final String status; // consistent | pending | accepted | rejected
  final double latitude;
  final double longitude;
  final double? accuracy;
  final double? distance; // metres from the approved location
  final String? observedBy;
  final DateTime? at;
  final LinkTarget? record; // in the review queue: what it is about
  final PlacedPoint? approved;
}

/// A record near a point, with how far it is.
class NearbyHit {
  const NearbyHit({required this.target, required this.distance, this.layer});

  final LinkTarget target;
  final double distance;
  final String? layer;
}
