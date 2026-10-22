import 'package:argus_api/api.dart' show QueryParam;

import 'api_service.dart';

/// Which template a document type is reworked with, and why (backend services/template_store.py).
class TemplateChoice {
  const TemplateChoice({required this.ref, required this.scope, required this.name, required this.version, required this.reason});

  final String ref; // official:<id> | a variant's uid
  final String scope; // official | workspace | personal
  final String name;
  final int version;
  final String reason;

  /// What saving names: an official template by its id, a variant at the exact version previewed.
  String get savedRef => scope == 'official' ? ref : '$ref@$version';

  factory TemplateChoice.fromJson(Map j) => TemplateChoice(
        ref: '${j['ref']}',
        scope: '${j['scope']}',
        name: '${j['name'] ?? j['id']}',
        version: (j['version'] as num?)?.toInt() ?? 1,
        reason: '${j['reason'] ?? ''}',
      );
}

/// What the raw text is and what is known about it.
class ReshapeSource {
  const ReshapeSource({required this.text, this.kind = 'paste', this.originalDate, this.textIsCurrent = false, this.filename});

  final String text;
  final String kind; // paste | email | intake | import
  final String? originalDate; // YYYY-MM-DD
  final bool textIsCurrent;
  final String? filename;

  Map<String, Object?> toJson() => {
        'text': text,
        'kind': kind,
        'original_date': ?originalDate,
        'text_is_current': textIsCurrent,
        'filename': ?filename,
      };
}

class ReshapeIssue {
  const ReshapeIssue(this.kind, this.message, this.lines);
  final String kind;
  final String message;
  final List<int> lines;

  /// What a person should not miss: a contradictory date, a line written for an assistant.
  bool get serious => kind == 'date_conflict' || kind == 'addressed_to_assistant';
}

class ReshapeLink {
  const ReshapeLink(this.kind, this.uid, this.label);
  final String kind; // asset | document | ticket
  final String uid;
  final String label;
}

/// The preview: the draft and everything to check. Nothing of it is saved.
class ReshapePreview {
  ReshapePreview(this.json)
      : title = '${json['title'] ?? ''}',
        markdown = '${json['markdown'] ?? ''}',
        template = TemplateChoice.fromJson(json['template'] as Map),
        model = json['model']?.toString(),
        missing = [for (final m in (json['missing'] as List? ?? const [])) '$m'],
        issues = [
          for (final i in (json['issues'] as List? ?? const []))
            if (i is Map) ReshapeIssue('${i['kind']}', '${i['message']}', _lines(i['lines'])),
          for (final a in (json['ambiguities'] as List? ?? const []))
            if (a is Map) ReshapeIssue('ambiguity', '${a['text']}', _lines(a['lines'])),
        ],
        links = [
          for (final l in (json['links'] as List? ?? const []))
            if (l is Map) ReshapeLink('${l['kind']}', '${l['uid']}', '${l['label']}'),
        ],
        uncitedLines = _lines(json['uncited_lines']),
        notice = ((json['notices'] as Map?)?['operational'] ?? (json['notices'] as Map?)?['reference'])?.toString(),
        suggestedType = json['suggested_type']?.toString();

  final Map<String, dynamic> json;
  final String title;
  final String markdown;
  final TemplateChoice template;
  final String? model;
  final List<String> missing;
  final List<ReshapeIssue> issues;
  final List<ReshapeLink> links;
  final List<int> uncitedLines;
  final String? notice;
  final String? suggestedType;

  Map get dates => (json['dates'] as Map?) ?? const {};
  String? get documentDate => dates['document_date']?.toString();
  String? get documentDateBasis => dates['document_date_basis']?.toString();
  bool get dateNeedsConfirmation => dates['document_date_needs_confirmation'] == true;

  /// Source lines the draft is built on (the evidence of what was extracted).
  Set<int> get citedLines {
    final out = <int>{};
    void take(Object? e) => out.addAll(_lines(e));
    final ex = json['extraction'] as Map? ?? const {};
    for (final f in ((ex['fields'] as Map?) ?? const {}).values) {
      if (f is Map) take(f['evidence']);
    }
    for (final s in ((ex['sections'] as Map?) ?? const {}).values) {
      for (final i in (s is Map ? (s['items'] as List? ?? const []) : const [])) {
        if (i is Map) take(i['evidence']);
      }
    }
    return out;
  }

  static List<int> _lines(Object? v) => [for (final x in (v as List? ?? const [])) if (x is num) x.toInt()];
}

/// What was saved: the document and its draft revision.
class ReshapeSaved {
  const ReshapeSaved(this.documentUid, this.revisionUid, this.revisionNumber);
  final String documentUid;
  final String revisionUid;
  final int revisionNumber;
}

/// Rework from raw text (the web's Documents → Rework from raw text): notes, a dictation, a photographed page,
/// rewritten as a draft that follows the document type's template.
class ReshapeRepository {
  ReshapeRepository(this._api);

  final ApiService _api;

  Future<TemplateChoice> resolve(String documentType) async {
    final r = await _api.json((c) => c.invokeAPI('/v1/document-templates/resolve', 'GET',
        [QueryParam('document_type', documentType)], null, {}, {}, null));
    return TemplateChoice.fromJson(r as Map);
  }

  Future<ReshapePreview> preview(ReshapeSource source, {required String documentTypeUid, String? documentUid}) async {
    final r = await _api.json((c) => c.invokeAPI('/v1/ai/reshape', 'POST', [], {
          'source': source.toJson(),
          'document_type_uid': documentTypeUid,
          'document_uid': ?documentUid,
        }, {}, {}, 'application/json'));
    return ReshapePreview(Map<String, dynamic>.from(r as Map));
  }

  /// The edited draft saved as a draft: a new document, or [documentUid]'s next revision.
  Future<ReshapeSaved> save(ReshapePreview p, ReshapeSource source,
      {required String documentTypeUid,
      required String title,
      required String markdown,
      String? documentUid,
      bool confirmDate = false,
      List<String> linkAssets = const []}) async {
    final path = documentUid == null ? '/v1/documents/reshape' : '/v1/documents/${Uri.encodeComponent(documentUid)}/reshape';
    final r = await _api.json((c) => c.invokeAPI(path, 'POST', [], {
          'source': source.toJson(),
          'document_type_uid': documentTypeUid,
          'template': p.template.savedRef,
          'title': title,
          'markdown': markdown,
          'dates': p.json['dates'],
          'extraction': p.json['extraction'],
          'issues': p.json['issues'],
          'model': p.model,
          'confirm_document_date': confirmDate,
          'link_assets': linkAssets,
        }, {}, {}, 'application/json'));
    final m = r as Map;
    return ReshapeSaved('${m['document_uid']}', '${m['revision_uid']}', (m['revision_number'] as num?)?.toInt() ?? 1);
  }
}
