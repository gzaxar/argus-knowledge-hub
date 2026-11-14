/// A rack surveyed from the phone (docs/rack-census.md): what the screens of the guided survey work with.
library;

Map<String, Object?> _map(Object? o) => o is Map ? o.map((k, v) => MapEntry(k.toString(), v)) : const {};
List<Object?> _list(Object? o) => o is List ? o : const [];

/// One value read on a photo or taken from the catalogue: never used until the person takes it.
class CensusProposal {
  const CensusProposal({required this.field, required this.value, this.label, this.confidence, this.evidence,
      this.grounded = true, this.source = 'photo'});

  final String field;
  final Object? value;
  final String? label;
  final double? confidence;
  final String? evidence;
  final bool grounded;
  final String source; // photo | label | rack photo | catalogue

  String get display => label ?? '$value';
  bool get weak => !grounded || (confidence != null && confidence! < 0.6);

  /// What the server keeps when the person takes it: the value and where it came from.
  Map<String, Object?> taken() => {'value': value, 'source': source, if (confidence != null) 'confidence': confidence};

  static CensusProposal parse(String field, Object? o) {
    final m = _map(o);
    return CensusProposal(field: field, value: m['value'], label: m['label'] as String?,
        confidence: (m['confidence'] as num?)?.toDouble(), evidence: m['evidence'] as String?,
        grounded: m['grounded'] != false, source: (m['source'] ?? 'photo').toString());
  }
}

/// A value the person set: taken from a proposal (its source), or typed.
class CensusValue {
  const CensusValue(this.value, this.source);
  final Object? value;
  final String source;
}

class Duplicate {
  const Duplicate({required this.uid, this.key, required this.name, required this.why, required this.strength, this.mountedIn});
  final String uid;
  final String? key;
  final String name;
  final String why;
  final String strength; // strong | medium | weak
  final String? mountedIn;
}

class CensusPhoto {
  const CensusPhoto(this.uid, this.role);
  final String uid;
  final String role; // rack_front | rack_rear | device | label
}

class CensusItem {
  const CensusItem({required this.id, this.photos = const [], this.proposals = const {}, this.values = const {},
      this.decision, this.assetUid, this.duplicates = const [], this.duplicateChecked = false, this.note});

  final String id;
  final List<CensusPhoto> photos;
  final Map<String, CensusProposal> proposals;
  final Map<String, CensusValue> values;
  final String? decision; // link | create | skip
  final String? assetUid;
  final List<Duplicate> duplicates;
  final bool duplicateChecked;
  final String? note;

  Object? value(String f) => values[f]?.value;
  int? intValue(String f) => switch (value(f)) { final int v => v, final num v => v.toInt(), _ => null };
  String get title => (value('name') ?? proposals['name']?.value ?? 'Unit').toString();
  bool get hasLabel => photos.any((p) => p.role == 'label');

  /// The U it takes, when its lowest unit and height are known.
  ({int from, int to})? get span {
    final s = intValue('start_u'), h = intValue('height_u');
    if (s == null || h == null) return null;
    return (from: s, to: s + (h < 1 ? 1 : h) - 1);
  }

  static CensusItem parse(Object? o) {
    final m = _map(o);
    return CensusItem(
      id: m['id'].toString(),
      photos: _list(m['photos']).map(_map).map((p) => CensusPhoto(p['uid'].toString(), p['role'].toString())).toList(),
      proposals: _map(m['proposals']).map((k, v) => MapEntry(k, CensusProposal.parse(k, v))),
      values: _map(m['values']).map((k, v) {
        final e = _map(v);
        return MapEntry(k, v is Map ? CensusValue(e['value'], (e['source'] ?? 'person').toString()) : CensusValue(v, 'person'));
      }),
      decision: m['decision'] as String?,
      assetUid: m['asset_uid'] as String?,
      duplicates: _list(m['duplicates']).map(_map).map((d) => Duplicate(uid: d['uid'].toString(), key: d['key'] as String?,
          name: (d['name'] ?? '').toString(), why: (d['why'] ?? '').toString(), strength: (d['strength'] ?? 'weak').toString(),
          mountedIn: _map(d['mounted'])['rack'] as String?)).toList(),
      duplicateChecked: m['duplicate_checked'] == true,
      note: m['note'] as String?,
    );
  }
}

class CensusRack {
  const CensusRack({this.recordUid, this.recordName, this.units, this.photos = const [], this.proposals = const {},
      this.values = const {}, this.candidates = const [], this.note});

  final String? recordUid;
  final String? recordName;
  final int? units;
  final List<CensusPhoto> photos;
  final Map<String, CensusProposal> proposals;
  final Map<String, Object?> values;
  final List<({String uid, String? key, String name, String why})> candidates;
  final String? note;

  bool get isNew => recordUid == null;
  String get name => recordName ?? (values['name'] ?? proposals['name']?.value ?? 'New rack').toString();
  int get height => units ?? (values['units'] as num?)?.toInt() ?? 42;

  static CensusRack parse(Object? o) {
    final m = _map(o);
    final rec = _map(m['record']);
    return CensusRack(
      recordUid: rec['uid'] as String?, recordName: rec['name'] as String?, units: (rec['units'] as num?)?.toInt(),
      photos: _list(m['photos']).map(_map).map((p) => CensusPhoto(p['uid'].toString(), p['role'].toString())).toList(),
      proposals: _map(m['proposals']).map((k, v) => MapEntry(k, CensusProposal.parse(k, v))),
      values: _map(m['values']),
      candidates: _list(m['candidates']).map(_map).map((c) => (uid: c['uid'].toString(), key: c['key'] as String?,
          name: (c['name'] ?? '').toString(), why: (c['why'] ?? '').toString())).toList(),
      note: m['note'] as String?,
    );
  }
}

class Census {
  const Census({required this.uid, required this.state, required this.rack, this.items = const []});
  final String uid;
  final String state; // open | applied | abandoned
  final CensusRack rack;
  final List<CensusItem> items;

  CensusItem? item(String id) => items.where((i) => i.id == id).firstOrNull;

  static Census parse(Object? o) {
    final m = _map(o);
    return Census(uid: m['uid'].toString(), state: (m['state'] ?? 'open').toString(), rack: CensusRack.parse(m['rack']),
        items: _list(m['items']).map(CensusItem.parse).toList());
  }
}

class OpenCensus {
  const OpenCensus({required this.uid, this.rack, required this.items, this.updatedAt});
  final String uid;
  final String? rack;
  final int items;
  final DateTime? updatedAt;
}

/// What stands between the survey and the inventory.
class CensusReview {
  const CensusReview({required this.ok, this.missing = const [], this.problems = const [], this.changes = const [],
      this.newRecords = 0});
  final bool ok;
  final List<({String? item, String field, String message})> missing;
  final List<String> problems;
  final List<String> changes;
  final int newRecords;

  static CensusReview parse(Object? o) {
    final m = _map(o);
    return CensusReview(
      ok: m['ok'] == true,
      missing: _list(m['missing']).map(_map).map((x) => (item: x['item'] as String?, field: x['field'].toString(),
          message: x['message'].toString())).toList(),
      problems: _list(m['problems']).map(_map).map((p) => p['message'].toString()).toList(),
      changes: _list(m['changes']).map((c) => c.toString()).toList(),
      newRecords: (m['new_records'] as num?)?.toInt() ?? 0,
    );
  }
}
