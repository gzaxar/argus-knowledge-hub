//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;


class SearchApi {
  SearchApi([ApiClient? apiClient]) : apiClient = apiClient ?? defaultApiClient;

  final ApiClient apiClient;

  /// Jql Fields
  ///
  /// For each kind of record, the fields a query can name, what they mean and whether results can be ordered by them. Any other name is one of the record's attributes.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> jqlFieldsWithHttpInfo({ String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/search/jql/fields';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

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

  /// Jql Fields
  ///
  /// For each kind of record, the fields a query can name, what they mean and whether results can be ordered by them. Any other name is one of the record's attributes.
  ///
  /// Parameters:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> jqlFields({ String? authorization, String? xWorkspaceId, }) async {
    final response = await jqlFieldsWithHttpInfo( authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Search Jql
  ///
  /// Tickets, equipment or documents selected by an advanced query. Without `project = …` the query searches the current workspace (and what is shared with every workspace); `project in (a, b)` searches those the person may read. A query that cannot be read answers 422 with where it went wrong.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] entity (required):
  ///
  /// * [String] jql:
  ///   e.g. status = Open AND assignee = currentUser()
  ///
  /// * [int] limit:
  ///
  /// * [int] offset:
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Response> searchJqlWithHttpInfo(String entity, { String? jql, int? limit, int? offset, String? xWorkspaceId, String? authorization, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/search/jql';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

      queryParams.addAll(_queryParams('', 'entity', entity));
    if (jql != null) {
      queryParams.addAll(_queryParams('', 'jql', jql));
    }
    if (limit != null) {
      queryParams.addAll(_queryParams('', 'limit', limit));
    }
    if (offset != null) {
      queryParams.addAll(_queryParams('', 'offset', offset));
    }

    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }
    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
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

  /// Search Jql
  ///
  /// Tickets, equipment or documents selected by an advanced query. Without `project = …` the query searches the current workspace (and what is shared with every workspace); `project in (a, b)` searches those the person may read. A query that cannot be read answers 422 with where it went wrong.
  ///
  /// Parameters:
  ///
  /// * [String] entity (required):
  ///
  /// * [String] jql:
  ///   e.g. status = Open AND assignee = currentUser()
  ///
  /// * [int] limit:
  ///
  /// * [int] offset:
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Object?> searchJql(String entity, { String? jql, int? limit, int? offset, String? xWorkspaceId, String? authorization, }) async {
    final response = await searchJqlWithHttpInfo(entity,  jql: jql, limit: limit, offset: offset, xWorkspaceId: xWorkspaceId, authorization: authorization, );
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
