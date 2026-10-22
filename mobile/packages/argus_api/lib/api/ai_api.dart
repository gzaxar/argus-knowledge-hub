//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;


class AiApi {
  AiApi([ApiClient? apiClient]) : apiClient = apiClient ?? defaultApiClient;

  final ApiClient apiClient;

  /// Chat
  ///
  /// Ask, as a conversation, answered as it is worked out: server-sent events (one JSON object per `data:` line) for what the model is doing, each lookup and its result, and the answer as it is written. The turn is saved in the conversation, which a follow-up continues. Same permission as reading the records by hand: the lookups only retrieve. To somebody who may create or change records it can also propose changes, which wait for them to apply (services/ask_actions.py).
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [ChatIn] chatIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> chatWithHttpInfo(ChatIn chatIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/chat';

    // ignore: prefer_final_locals
    Object? postBody = chatIn;

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

  /// Chat
  ///
  /// Ask, as a conversation, answered as it is worked out: server-sent events (one JSON object per `data:` line) for what the model is doing, each lookup and its result, and the answer as it is written. The turn is saved in the conversation, which a follow-up continues. Same permission as reading the records by hand: the lookups only retrieve. To somebody who may create or change records it can also propose changes, which wait for them to apply (services/ask_actions.py).
  ///
  /// Parameters:
  ///
  /// * [ChatIn] chatIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> chat(ChatIn chatIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await chatWithHttpInfo(chatIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Draft A Document
  ///
  /// A first draft for the editor. Saves nothing.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [DraftDocumentIn] draftDocumentIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> draftADocumentWithHttpInfo(DraftDocumentIn draftDocumentIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/draft-document';

    // ignore: prefer_final_locals
    Object? postBody = draftDocumentIn;

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

  /// Draft A Document
  ///
  /// A first draft for the editor. Saves nothing.
  ///
  /// Parameters:
  ///
  /// * [DraftDocumentIn] draftDocumentIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<DraftDocumentOut?> draftADocument(DraftDocumentIn draftDocumentIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await draftADocumentWithHttpInfo(draftDocumentIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'DraftDocumentOut',) as DraftDocumentOut;
    
    }
    return null;
  }

  /// Get Conversation
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] conversationId (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> getConversationWithHttpInfo(String conversationId, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/conversations/{conversation_id}'
      .replaceAll('{conversation_id}', conversationId);

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

  /// Get Conversation
  ///
  /// Parameters:
  ///
  /// * [String] conversationId (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<AskConversationDetail?> getConversation(String conversationId, { String? authorization, String? xWorkspaceId, }) async {
    final response = await getConversationWithHttpInfo(conversationId,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'AskConversationDetail',) as AskConversationDetail;
    
    }
    return null;
  }

  /// List Conversations
  ///
  /// Your conversations in this workspace, most recent first.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> listConversationsWithHttpInfo({ String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/conversations';

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

  /// List Conversations
  ///
  /// Your conversations in this workspace, most recent first.
  ///
  /// Parameters:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<List<AskConversationOut>?> listConversations({ String? authorization, String? xWorkspaceId, }) async {
    final response = await listConversationsWithHttpInfo( authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      final responseBody = await _decodeBodyBytes(response);
      return (await apiClient.deserializeAsync(responseBody, 'List<AskConversationOut>') as List)
        .cast<AskConversationOut>()
        .toList(growable: false);

    }
    return null;
  }

  /// Rate An Answer
  ///
  /// Rate one of your answers, once: up, or down with an optional word on what was wrong. The rating is kept anonymously (services/ask_feedback.py): the question, the answer and how it was made, not who asked; an answer rated down becomes a ticket for the people who look after Ask ARGUS.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] conversationId (required):
  ///
  /// * [AskFeedbackIn] askFeedbackIn (required):
  ///
  /// * [String] xARGUSClient:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> rateAnAnswerWithHttpInfo(String conversationId, AskFeedbackIn askFeedbackIn, { String? xARGUSClient, String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/conversations/{conversation_id}/feedback'
      .replaceAll('{conversation_id}', conversationId);

    // ignore: prefer_final_locals
    Object? postBody = askFeedbackIn;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (xARGUSClient != null) {
      headerParams[r'X-ARGUS-Client'] = parameterToString(xARGUSClient);
    }
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

  /// Rate An Answer
  ///
  /// Rate one of your answers, once: up, or down with an optional word on what was wrong. The rating is kept anonymously (services/ask_feedback.py): the question, the answer and how it was made, not who asked; an answer rated down becomes a ticket for the people who look after Ask ARGUS.
  ///
  /// Parameters:
  ///
  /// * [String] conversationId (required):
  ///
  /// * [AskFeedbackIn] askFeedbackIn (required):
  ///
  /// * [String] xARGUSClient:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<AskFeedbackOut?> rateAnAnswer(String conversationId, AskFeedbackIn askFeedbackIn, { String? xARGUSClient, String? authorization, String? xWorkspaceId, }) async {
    final response = await rateAnAnswerWithHttpInfo(conversationId, askFeedbackIn,  xARGUSClient: xARGUSClient, authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'AskFeedbackOut',) as AskFeedbackOut;
    
    }
    return null;
  }

  /// Reshape Preview
  ///
  /// The draft a template makes of the raw text, with what is missing or uncertain, the dates and the suggested links. Nothing is saved: no document, no revision, no file.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [ReshapeIn] reshapeIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> reshapePreviewWithHttpInfo(ReshapeIn reshapeIn, { String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/reshape';

    // ignore: prefer_final_locals
    Object? postBody = reshapeIn;

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

  /// Reshape Preview
  ///
  /// The draft a template makes of the raw text, with what is missing or uncertain, the dates and the suggested links. Nothing is saved: no document, no revision, no file.
  ///
  /// Parameters:
  ///
  /// * [ReshapeIn] reshapeIn (required):
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> reshapePreview(ReshapeIn reshapeIn, { String? authorization, String? xWorkspaceId, }) async {
    final response = await reshapePreviewWithHttpInfo(reshapeIn,  authorization: authorization, xWorkspaceId: xWorkspaceId, );
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

  /// Status
  ///
  /// What the application asks before offering an AI action.  A feature that cannot work should not be presented as if it could, and the reason belongs here rather than in a failed request later.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> statusWithHttpInfo({ String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/status';

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

  /// Status
  ///
  /// What the application asks before offering an AI action.  A feature that cannot work should not be presented as if it could, and the reason belongs here rather than in a failed request later.
  ///
  /// Parameters:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<AIStatus?> status({ String? authorization, String? xWorkspaceId, }) async {
    final response = await statusWithHttpInfo( authorization: authorization, xWorkspaceId: xWorkspaceId, );
    if (response.statusCode >= HttpStatus.badRequest) {
      throw ApiException(response.statusCode, await _decodeBodyBytes(response));
    }
    // When a remote server returns no body with a status of 204, we shall not decode it.
    // At the time of writing this, `dart:convert` will throw an "Unexpected end of input"
    // FormatException when trying to decode an empty string.
    if (response.body.isNotEmpty && response.statusCode != HttpStatus.noContent) {
      return await apiClient.deserializeAsync(await _decodeBodyBytes(response), 'AIStatus',) as AIStatus;
    
    }
    return null;
  }

  /// Transcribe Recording
  ///
  /// What was said in a recording, as text, by the workspace's speech-to-text model. Keeps nothing: the person edits the text, and what they save is what is kept.
  ///
  /// Note: This method returns the HTTP [Response].
  ///
  /// Parameters:
  ///
  /// * [MultipartFile] file (required):
  ///   A recording: a dictated note or document
  ///
  /// * [String] language:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Response> transcribeRecordingWithHttpInfo(MultipartFile file, { String? language, String? authorization, String? xWorkspaceId, }) async {
    // ignore: prefer_const_declarations
    final path = r'/v1/ai/transcribe';

    // ignore: prefer_final_locals
    Object? postBody;

    final queryParams = <QueryParam>[];
    final headerParams = <String, String>{};
    final formParams = <String, String>{};

    if (language != null) {
      queryParams.addAll(_queryParams('', 'language', language));
    }

    if (authorization != null) {
      headerParams[r'authorization'] = parameterToString(authorization);
    }
    if (xWorkspaceId != null) {
      headerParams[r'X-Workspace-Id'] = parameterToString(xWorkspaceId);
    }

    const contentTypes = <String>['multipart/form-data'];

    bool hasFields = false;
    final mp = MultipartRequest('POST', Uri.parse(path));
    if (file != null) {
      hasFields = true;
      mp.fields[r'file'] = file.field;
      mp.files.add(file);
    }
    if (hasFields) {
      postBody = mp;
    }

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

  /// Transcribe Recording
  ///
  /// What was said in a recording, as text, by the workspace's speech-to-text model. Keeps nothing: the person edits the text, and what they save is what is kept.
  ///
  /// Parameters:
  ///
  /// * [MultipartFile] file (required):
  ///   A recording: a dictated note or document
  ///
  /// * [String] language:
  ///
  /// * [String] authorization:
  ///
  /// * [String] xWorkspaceId:
  Future<Object?> transcribeRecording(MultipartFile file, { String? language, String? authorization, String? xWorkspaceId, }) async {
    final response = await transcribeRecordingWithHttpInfo(file,  language: language, authorization: authorization, xWorkspaceId: xWorkspaceId, );
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
