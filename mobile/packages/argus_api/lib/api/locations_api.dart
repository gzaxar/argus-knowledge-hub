//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;


class LocationsApi {
  LocationsApi([ApiClient? apiClient]) : apiClient = apiClient ?? defaultApiClient;

  final ApiClient apiClient;

  /// Accept Observation
  ///
  /// Accept an observation: it becomes the record's approved location (the previous one kept in history).
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [int] obsId (required):
  ///
  /// * [DecisionIn] decisionIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> acceptObservationWithHttpInfo(int obsId, DecisionIn decisionIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/location-reviews/{obs_id}/accept'
      .replaceAll('{obs_id}', obsId.toString());

    // ignore: prefer_final_locals
    Object? postBody = decisionIn;

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

  /// Accept Observation
  ///
  /// Accept an observation: it becomes the record's approved location (the previous one kept in history).
  ///
  /// Parameters:
  ///
  /// * [int] obsId (required):
  ///
  /// * [DecisionIn] decisionIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> acceptObservation(int obsId, DecisionIn decisionIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await acceptObservationWithHttpInfo(obsId, decisionIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Get Location
  ///
  /// The record's approved location (or none), whether its type may have one and on which map layer, the history of its approved locations, and the field observations of it.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] uid (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> getLocationWithHttpInfo(String uid, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/assets/{uid}/location'
      .replaceAll('{uid}', uid);

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

  /// Get Location
  ///
  /// The record's approved location (or none), whether its type may have one and on which map layer, the history of its approved locations, and the field observations of it.
  ///
  /// Parameters:
  ///
  /// * [String] uid (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> getLocation(String uid, { String? authorization, String? xWorkspaceId, }) async {
    final response = await getLocationWithHttpInfo(uid,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Location Reviews
  ///
  /// Field observations of this workspace's records waiting for a decision (or decided: status=…).
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] status:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> locationReviewsWithHttpInfo({ String? status, String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/location-reviews';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (status != null) {
      queryParams.addAll(_queryParams('', 'status', status));
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

  /// Location Reviews
  ///
  /// Field observations of this workspace's records waiting for a decision (or decided: status=…).
  ///
  /// Parameters:
  ///
  /// * [String] status:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> locationReviews({ String? status, String? authorization, String? xWorkspaceId, }) async {
    final response = await locationReviewsWithHttpInfo( status: status, authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Map Nearby
  ///
  /// The records within a distance of a point, nearest first, as GeoJSON with each one's distance.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [num] latitude (required):
  ///
  /// * [num] longitude (required):
  ///
  /// * [num] radiusM:
  ///
  /// * [String] workspaces:
  ///
  /// * [String] types:
  ///
  /// * [String] status:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> mapNearbyWithHttpInfo(num latitude, num longitude, { num? radiusM, String? workspaces, String? types, String? status, String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/map/nearby';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

      queryParams.addAll(_queryParams('', 'latitude', latitude));
      queryParams.addAll(_queryParams('', 'longitude', longitude));
    if (radiusM != null) {
      queryParams.addAll(_queryParams('', 'radius_m', radiusM));
    }
    if (workspaces != null) {
      queryParams.addAll(_queryParams('', 'workspaces', workspaces));
    }
    if (types != null) {
      queryParams.addAll(_queryParams('', 'types', types));
    }
    if (status != null) {
      queryParams.addAll(_queryParams('', 'status', status));
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

  /// Map Nearby
  ///
  /// The records within a distance of a point, nearest first, as GeoJSON with each one's distance.
  ///
  /// Parameters:
  ///
  /// * [num] latitude (required):
  ///
  /// * [num] longitude (required):
  ///
  /// * [num] radiusM:
  ///
  /// * [String] workspaces:
  ///
  /// * [String] types:
  ///
  /// * [String] status:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> mapNearby(num latitude, num longitude, { num? radiusM, String? workspaces, String? types, String? status, String? authorization, String? xWorkspaceId, }) async {
    final response = await mapNearbyWithHttpInfo(latitude, longitude,  radiusM: radiusM, workspaces: workspaces, types: types, status: status, authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Observe
  ///
  /// Where someone saw the record (a phone's GPS fix and its accuracy). It never moves the record: it agrees with the approved location, or it waits for a person to review it.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] uid (required):
  ///
  /// * [ObservationIn] observationIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> observeWithHttpInfo(String uid, ObservationIn observationIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/assets/{uid}/location/observations'
      .replaceAll('{uid}', uid);

    // ignore: prefer_final_locals
    Object? postBody = observationIn;

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

  /// Observe
  ///
  /// Where someone saw the record (a phone's GPS fix and its accuracy). It never moves the record: it agrees with the approved location, or it waits for a person to review it.
  ///
  /// Parameters:
  ///
  /// * [String] uid (required):
  ///
  /// * [ObservationIn] observationIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> observe(String uid, ObservationIn observationIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await observeWithHttpInfo(uid, observationIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Reject Observation
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [int] obsId (required):
  ///
  /// * [DecisionIn] decisionIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> rejectObservationWithHttpInfo(int obsId, DecisionIn decisionIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/location-reviews/{obs_id}/reject'
      .replaceAll('{obs_id}', obsId.toString());

    // ignore: prefer_final_locals
    Object? postBody = decisionIn;

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

  /// Reject Observation
  ///
  /// Parameters:
  ///
  /// * [int] obsId (required):
  ///
  /// * [DecisionIn] decisionIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> rejectObservation(int obsId, DecisionIn decisionIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await rejectObservationWithHttpInfo(obsId, decisionIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
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
