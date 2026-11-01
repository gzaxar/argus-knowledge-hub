//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;


class CatalogueApi {
  CatalogueApi([ApiClient? apiClient]) : apiClient = apiClient ?? defaultApiClient;

  final ApiClient apiClient;

  /// Install One Model
  ///
  /// Install one model of the pinned sources (and its vendor, when the catalogue has none) — what a person picks for a unit they are creating. An existing record that looks like it is never overwritten: the answer is 409 with that record, to choose instead. Recorded in the catalogue's history as a partial installation.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [InstallOneIn] installOneIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> installOneModelWithHttpInfo(InstallOneIn installOneIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/catalogue/collections/models/install-one';

    // ignore: prefer_final_locals
    Object? postBody = installOneIn;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
    }
    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }

    const contentTypes = <String>['application/json'];


    return apiClient.invokeAPI(
      path,
      'POST',
      queryParams,
      postBody,
      headerParams,
      formParams,
      contentTypes.isEmpty ? null : contentTypes.first,
    );
  }

  /// Install One Model
  ///
  /// Install one model of the pinned sources (and its vendor, when the catalogue has none) — what a person picks for a unit they are creating. An existing record that looks like it is never overwritten: the answer is 409 with that record, to choose instead. Recorded in the catalogue's history as a partial installation.
  ///
  /// Parameters:
  ///
  /// * [InstallOneIn] installOneIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> installOneModel(InstallOneIn installOneIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await installOneModelWithHttpInfo(installOneIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'Object',) as Object;
    
    }
    return null;
  }

  /// Search Models
  ///
  /// Models for a picker: those installed in the catalogue first, then the pinned sources' not yet installed (the NetBox library among them), best first — the model code exactly, at its start, inside it, then the name. The models of this workspace's domains, unless `every`.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] q:
  ///
  /// * [bool] every:
  ///
  /// * [int] limit:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> searchModelsWithHttpInfo({ String? q, bool? every, int? limit, String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/catalogue/collections/models/search';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (q != null) {
      queryParams.addAll(_queryParams('', 'q', q));
    }
    if (every != null) {
      queryParams.addAll(_queryParams('', 'every', every));
    }
    if (limit != null) {
      queryParams.addAll(_queryParams('', 'limit', limit));
    }

    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
    }
    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }

    const contentTypes = <String>[];


    return apiClient.invokeAPI(
      path,
      'GET',
      queryParams,
      postBody,
      headerParams,
      formParams,
      contentTypes.isEmpty ? null : contentTypes.first,
    );
  }

  /// Search Models
  ///
  /// Models for a picker: those installed in the catalogue first, then the pinned sources' not yet installed (the NetBox library among them), best first — the model code exactly, at its start, inside it, then the name. The models of this workspace's domains, unless `every`.
  ///
  /// Parameters:
  ///
  /// * [String] q:
  ///
  /// * [bool] every:
  ///
  /// * [int] limit:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> searchModels({ String? q, bool? every, int? limit, String? authorization, String? xWorkspaceId, }) async {
    final response = await searchModelsWithHttpInfo( q: q, every: every, limit: limit, authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'Object',) as Object;
    
    }
    return null;
  }
}
