import 'package:argus_api/api.dart' as api;
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;

import '../domain/capture.dart' show PickedPhoto;
import '../domain/census.dart';
import 'api_service.dart';

Map<String, Object?> _map(Object? o) => o is Map ? o.map((k, v) => MapEntry(k.toString(), v)) : const {};
List<Object?> _list(Object? o) => o is List ? o : const [];

/// A rack surveyed from the phone (`/v1/rack-census`, docs/rack-census.md). Every step is kept on the server, so a
/// survey left half-way is resumed later, on this phone or another.
class CensusRepository {
  CensusRepository(this._api);
  final ApiService _api;

  Future<Object?> _call(String path, String method, [Object? body]) =>
      _api.json((c) => c.invokeAPI(path, method, [], body, {}, {}, body == null ? null : 'application/json'));

  Future<Census> start({String? rackUid, String? placeUid}) async =>
      Census.parse(await _call('/v1/rack-census', 'POST', {'rack_uid': rackUid, 'place_uid': placeUid}));

  Future<List<OpenCensus>> open() async => _list(await _call('/v1/rack-census', 'GET')).map(_map).map((m) => OpenCensus(
      uid: m['uid'].toString(), rack: m['rack'] as String?, items: (m['items'] as num?)?.toInt() ?? 0,
      updatedAt: m['updated_at'] is String ? DateTime.tryParse(m['updated_at'] as String) : null)).toList();

  Future<Census> get(String uid) async => Census.parse(await _call('/v1/rack-census/$uid', 'GET'));

  Future<void> abandon(String uid) => _call('/v1/rack-census/$uid', 'DELETE');

  /// A photo, and what was read on it. Returns the survey and, for a unit, which one it went to.
  Future<({Census survey, String? item, String? note})> photo(String uid, String role, PickedPhoto photo,
      {String? item}) async {
    final mp = http.MultipartRequest('POST', Uri.parse('/v1/rack-census/$uid/photos'))
      ..fields['role'] = role
      ..fields['item'] = item ?? ''
      ..files.add(http.MultipartFile.fromBytes('file', photo.bytes, filename: photo.name,
          contentType: MediaType.parse(photo.mimeType)));
    final m = _map(await _api.json((c) => c.invokeAPI('/v1/rack-census/$uid/photos', 'POST', <api.QueryParam>[], mp,
        {}, {}, 'multipart/form-data')));
    return (survey: Census.parse(m['survey']), item: m['item'] as String?, note: _map(m['reading'])['note'] as String?);
  }

  Future<Census> setRack(String uid, {String? existing, Map<String, Object?>? values}) async => Census.parse(
      await _call('/v1/rack-census/$uid/rack', 'PUT', {'existing': ?existing, 'values': ?values}));

  Future<Census> setItem(String uid, String item, {Map<String, Object?>? values, String? decision, String? assetUid,
          bool? duplicateChecked}) async =>
      Census.parse(await _call('/v1/rack-census/$uid/items/$item', 'PUT', {
        'values': ?values, 'decision': ?decision, 'asset_uid': ?assetUid, 'duplicate_checked': ?duplicateChecked}));

  Future<Census> removeItem(String uid, String item) async =>
      Census.parse(await _call('/v1/rack-census/$uid/items/$item', 'DELETE'));

  Future<CensusReview> review(String uid) async => CensusReview.parse(await _call('/v1/rack-census/$uid/review', 'GET'));

  /// Makes it so; the rack's uid and name.
  Future<({String uid, String name, List<String> changes})> apply(String uid) async {
    final m = _map(await _call('/v1/rack-census/$uid/apply', 'POST', <String, Object?>{}));
    final rack = _map(m['rack']);
    return (uid: rack['uid'].toString(), name: (rack['name'] ?? '').toString(),
        changes: _list(m['changes']).map((c) => c.toString()).toList());
  }
}
