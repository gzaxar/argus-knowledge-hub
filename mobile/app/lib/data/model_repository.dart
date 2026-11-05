import 'package:argus_api/api.dart' as api;

import 'api_service.dart';

Map<String, Object?> _map(Object? o) => o is Map ? o.map((k, v) => MapEntry(k.toString(), v)) : const {};
List<Object?> _list(Object? o) => o is List ? o : const [];

/// A model a picker offers: one in the catalogue (`uid`), or one of its sources' library, to install (`catalogueId`).
class ModelHit {
  const ModelHit({this.uid, this.catalogueId, required this.name, this.code, this.vendor, this.source});

  final String? uid;
  final String? catalogueId;
  final String name;
  final String? code;
  final String? vendor;
  final String? source; // netbox | argus, for a library model

  bool get installed => uid != null;
}

class ModelSearchResult {
  const ModelSearchResult({this.installed = const [], this.library = const [], this.more = false});

  final List<ModelHit> installed;
  final List<ModelHit> library;
  final bool more;
}

/// The product model picker's server side (GET …/models/search, POST …/models/install-one).
class ModelRepository {
  ModelRepository(this._api);

  final ApiService _api;

  Future<ModelSearchResult> search(String q, {bool every = false}) async {
    final r = _map(await _api.json((c) => _api.catalogue(c).searchModelsWithHttpInfo(q: q, every: every)));
    return ModelSearchResult(
      installed: [
        for (final m in _list(r['installed']).map(_map))
          ModelHit(uid: m['uid']?.toString(), name: (m['name'] ?? '').toString(), code: m['model_code']?.toString(),
                   vendor: m['vendor']?.toString()),
      ],
      library: [
        for (final m in _list(r['library']).map(_map))
          ModelHit(catalogueId: m['catalogue_id']?.toString(), name: (m['name'] ?? '').toString(),
                   code: (m['part_number'] ?? m['model_code'])?.toString(), vendor: m['vendor']?.toString(),
                   source: m['source']?.toString()),
      ],
      more: r['more'] == true,
    );
  }

  /// The catalogue's Vendor of this name or alias, or a new one (the catalogue's maintainers); its record's uid.
  Future<String> addVendor(String name) async {
    final r = _map(await _api.json((c) => c.invokeAPI(
        '/v1/catalogue/collections/vendors', 'POST', [], {'name': name}, {}, {}, 'application/json')));
    return r['uid'].toString();
  }

  /// Installs a library model in the catalogue (with its vendor) and returns its record's uid. A record already
  /// here that looks like it comes back as a `Problem` whose `candidates` name it.
  Future<String> installOne(String catalogueId) async {
    final r = _map(await _api.json(
        (c) => _api.catalogue(c).installOneModelWithHttpInfo(api.InstallOneIn(catalogueId: catalogueId))));
    return r['uid'].toString();
  }
}
