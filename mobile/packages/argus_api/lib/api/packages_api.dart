//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;


class PackagesApi {
  PackagesApi([ApiClient? apiClient]) : apiClient = apiClient ?? defaultApiClient;

  final ApiClient apiClient;

  /// Workspace Capabilities
  ///
  /// What this workspace's packages let it do: which pages to show (equipment, map, beam model, records), its map layers, ticket and document kinds, and the importers its packages support.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] workspaceId (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> workspaceCapabilitiesWithHttpInfo(String workspaceId, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/workspaces/{workspace_id}/capabilities'
      .replaceAll('{workspace_id}', workspaceId);

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

  /// Workspace Capabilities
  ///
  /// What this workspace's packages let it do: which pages to show (equipment, map, beam model, records), its map layers, ticket and document kinds, and the importers its packages support.
  ///
  /// Parameters:
  ///
  /// * [String] workspaceId (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<CapabilitiesOut?> workspaceCapabilities(String workspaceId, { String? authorization, String? xWorkspaceId, }) async {
    final response = await workspaceCapabilitiesWithHttpInfo(workspaceId,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'CapabilitiesOut',) as CapabilitiesOut;
    
    }
    return null;
  }
}
