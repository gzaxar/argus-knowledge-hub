//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;


class ActivitiesApi {
  ActivitiesApi([ApiClient? apiClient]) : apiClient = apiClient ?? defaultApiClient;

  final ApiClient apiClient;

  /// Act On Activity
  ///
  /// Start, complete, skip, cancel or reopen it (one occurrence of a series, on its own).
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] activityId (required):
  ///
  /// * [String] action (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  ///
  /// * [ActivityAction] activityAction:
  Future<Response> actOnActivityWithHttpInfo(String activityId, String action, { String? xWorkspaceId, String? authorization, ActivityAction? activityAction, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/activities/{activity_id}/{action}'
      .replaceAll('{activity_id}', activityId)
      .replaceAll('{action}', action);

    // ignore: prefer_final_locals
    Object? postBody = activityAction;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }
    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
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

  /// Act On Activity
  ///
  /// Start, complete, skip, cancel or reopen it (one occurrence of a series, on its own).
  ///
  /// Parameters:
  ///
  /// * [String] activityId (required):
  ///
  /// * [String] action (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  ///
  /// * [ActivityAction] activityAction:
  Future<Object?> actOnActivity(String activityId, String action, { String? xWorkspaceId, String? authorization, ActivityAction? activityAction, }) async {
    final response = await actOnActivityWithHttpInfo(activityId, action,  xWorkspaceId: xWorkspaceId, authorization: authorization, activityAction: activityAction, );
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

  /// Change Activity
  ///
  /// Change it; for an occurrence, `this` one, this and the `future` ones (the series is split), or the whole `series`.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] activityId (required):
  ///
  /// * [ActivityChange] activityChange (required):
  ///
  /// * [String] scope:
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Response> changeActivityWithHttpInfo(String activityId, ActivityChange activityChange, { String? scope, String? xWorkspaceId, String? authorization, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/activities/{activity_id}'
      .replaceAll('{activity_id}', activityId);

    // ignore: prefer_final_locals
    Object? postBody = activityChange;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (scope != null) {
      queryParams.addAll(_queryParams('', 'scope', scope));
    }

    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }
    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
    }

    const contentTypes = <String>['application/json'];


    return apiClient.invokeAPI(
      path,
      'PATCH',
      queryParams,
      postBody,
      headerParams,
      formParams,
      contentTypes.isEmpty ? null : contentTypes.first,
    );
  }

  /// Change Activity
  ///
  /// Change it; for an occurrence, `this` one, this and the `future` ones (the series is split), or the whole `series`.
  ///
  /// Parameters:
  ///
  /// * [String] activityId (required):
  ///
  /// * [ActivityChange] activityChange (required):
  ///
  /// * [String] scope:
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Object?> changeActivity(String activityId, ActivityChange activityChange, { String? scope, String? xWorkspaceId, String? authorization, }) async {
    final response = await changeActivityWithHttpInfo(activityId, activityChange,  scope: scope, xWorkspaceId: xWorkspaceId, authorization: authorization, );
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

  /// Classify Capture
  ///
  /// What was said, proposed as a ticket or an activity (or uncertain), with what it rests on, what is unsure, one clarifying question when needed and open tickets that look the same. Nothing is written.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [CaptureIn] captureIn (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Response> classifyCaptureWithHttpInfo(CaptureIn captureIn, { String? xWorkspaceId, String? authorization, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/capture/classify';

    // ignore: prefer_final_locals
    Object? postBody = captureIn;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }
    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
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

  /// Classify Capture
  ///
  /// What was said, proposed as a ticket or an activity (or uncertain), with what it rests on, what is unsure, one clarifying question when needed and open tickets that look the same. Nothing is written.
  ///
  /// Parameters:
  ///
  /// * [CaptureIn] captureIn (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Object?> classifyCapture(CaptureIn captureIn, { String? xWorkspaceId, String? authorization, }) async {
    final response = await classifyCaptureWithHttpInfo(captureIn,  xWorkspaceId: xWorkspaceId, authorization: authorization, );
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

  /// Create Activity
  ///
  /// One activity, or a recurring series (`rrule`, from `planned_start` read in `timezone`).
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [ActivityIn] activityIn (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Response> createActivityWithHttpInfo(ActivityIn activityIn, { String? xWorkspaceId, String? authorization, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/activities';

    // ignore: prefer_final_locals
    Object? postBody = activityIn;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }
    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
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

  /// Create Activity
  ///
  /// One activity, or a recurring series (`rrule`, from `planned_start` read in `timezone`).
  ///
  /// Parameters:
  ///
  /// * [ActivityIn] activityIn (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Object?> createActivity(ActivityIn activityIn, { String? xWorkspaceId, String? authorization, }) async {
    final response = await createActivityWithHttpInfo(activityIn,  xWorkspaceId: xWorkspaceId, authorization: authorization, );
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

  /// Get Activity
  ///
  /// One activity or occurrence, with where it came from (an AI proposal's transcript, if it did).
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] activityId (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Response> getActivityWithHttpInfo(String activityId, { String? xWorkspaceId, String? authorization, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/activities/{activity_id}'
      .replaceAll('{activity_id}', activityId);

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

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

  /// Get Activity
  ///
  /// One activity or occurrence, with where it came from (an AI proposal's transcript, if it did).
  ///
  /// Parameters:
  ///
  /// * [String] activityId (required):
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Object?> getActivity(String activityId, { String? xWorkspaceId, String? authorization, }) async {
    final response = await getActivityWithHttpInfo(activityId,  xWorkspaceId: xWorkspaceId, authorization: authorization, );
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

  /// List Activities
  ///
  /// The activities of a range the person may see, by planned or actual time, filtered, with counts. A `view` sets the range: `today` (planned today, under way, or done today), `upcoming` (the next 30 days) or `completed` (done in the last 30 days), in the time zone `tz`. Counts are of the whole range under the same filters except status, and never include what the person may not see.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [DateTime] from:
  ///
  /// * [DateTime] to:
  ///
  /// * [String] basis:
  ///
  /// * [String] view:
  ///
  /// * [String] tz:
  ///
  /// * [String] status:
  ///   comma-separated statuses
  ///
  /// * [String] owner:
  ///
  /// * [String] assignee:
  ///
  /// * [String] assetUid:
  ///
  /// * [String] ticketUid:
  ///
  /// * [bool] recurring:
  ///
  /// * [String] visibility:
  ///
  /// * [bool] mine:
  ///
  /// * [String] q:
  ///
  /// * [int] limit:
  ///
  /// * [int] offset:
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Response> listActivitiesWithHttpInfo({ DateTime? from, DateTime? to, String? basis, String? view, String? tz, String? status, String? owner, String? assignee, String? assetUid, String? ticketUid, bool? recurring, String? visibility, bool? mine, String? q, int? limit, int? offset, String? xWorkspaceId, String? authorization, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/activities';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (from != null) {
      queryParams.addAll(_queryParams('', 'from', from));
    }
    if (to != null) {
      queryParams.addAll(_queryParams('', 'to', to));
    }
    if (basis != null) {
      queryParams.addAll(_queryParams('', 'basis', basis));
    }
    if (view != null) {
      queryParams.addAll(_queryParams('', 'view', view));
    }
    if (tz != null) {
      queryParams.addAll(_queryParams('', 'tz', tz));
    }
    if (status != null) {
      queryParams.addAll(_queryParams('', 'status', status));
    }
    if (owner != null) {
      queryParams.addAll(_queryParams('', 'owner', owner));
    }
    if (assignee != null) {
      queryParams.addAll(_queryParams('', 'assignee', assignee));
    }
    if (assetUid != null) {
      queryParams.addAll(_queryParams('', 'asset_uid', assetUid));
    }
    if (ticketUid != null) {
      queryParams.addAll(_queryParams('', 'ticket_uid', ticketUid));
    }
    if (recurring != null) {
      queryParams.addAll(_queryParams('', 'recurring', recurring));
    }
    if (visibility != null) {
      queryParams.addAll(_queryParams('', 'visibility', visibility));
    }
    if (mine != null) {
      queryParams.addAll(_queryParams('', 'mine', mine));
    }
    if (q != null) {
      queryParams.addAll(_queryParams('', 'q', q));
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

  /// List Activities
  ///
  /// The activities of a range the person may see, by planned or actual time, filtered, with counts. A `view` sets the range: `today` (planned today, under way, or done today), `upcoming` (the next 30 days) or `completed` (done in the last 30 days), in the time zone `tz`. Counts are of the whole range under the same filters except status, and never include what the person may not see.
  ///
  /// Parameters:
  ///
  /// * [DateTime] from:
  ///
  /// * [DateTime] to:
  ///
  /// * [String] basis:
  ///
  /// * [String] view:
  ///
  /// * [String] tz:
  ///
  /// * [String] status:
  ///   comma-separated statuses
  ///
  /// * [String] owner:
  ///
  /// * [String] assignee:
  ///
  /// * [String] assetUid:
  ///
  /// * [String] ticketUid:
  ///
  /// * [bool] recurring:
  ///
  /// * [String] visibility:
  ///
  /// * [bool] mine:
  ///
  /// * [String] q:
  ///
  /// * [int] limit:
  ///
  /// * [int] offset:
  ///
  /// * [String] xWorkspaceId:
  ///
  /// * [String] authorization:
  Future<Object?> listActivities({ DateTime? from, DateTime? to, String? basis, String? view, String? tz, String? status, String? owner, String? assignee, String? assetUid, String? ticketUid, bool? recurring, String? visibility, bool? mine, String? q, int? limit, int? offset, String? xWorkspaceId, String? authorization, }) async {
    final response = await listActivitiesWithHttpInfo( from: from, to: to, basis: basis, view: view, tz: tz, status: status, owner: owner, assignee: assignee, assetUid: assetUid, ticketUid: ticketUid, recurring: recurring, visibility: visibility, mine: mine, q: q, limit: limit, offset: offset, xWorkspaceId: xWorkspaceId, authorization: authorization, );
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
