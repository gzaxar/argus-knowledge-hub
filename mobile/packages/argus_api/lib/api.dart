//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

library openapi.api;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:collection/collection.dart';
import 'package:http/http.dart';
import 'package:intl/intl.dart';
import 'package:meta/meta.dart';

part 'api_client.dart';
part 'api_helper.dart';
part 'api_exception.dart';
part 'auth/authentication.dart';
part 'auth/api_key_auth.dart';
part 'auth/oauth.dart';
part 'auth/http_basic_auth.dart';
part 'auth/http_bearer_auth.dart';

part 'api/ai_api.dart';
part 'api/asset_subresources_api.dart';
part 'api/assets_api.dart';
part 'api/attachments_api.dart';
part 'api/documents_api.dart';
part 'api/field_client_api.dart';
part 'api/global_values_api.dart';
part 'api/graph_api.dart';
part 'api/hub_api.dart';
part 'api/installations_api.dart';
part 'api/intake_api.dart';
part 'api/issues_api.dart';
part 'api/labels_api.dart';
part 'api/ledger_api.dart';
part 'api/locations_api.dart';
part 'api/lookup_api.dart';
part 'api/meta_api.dart';
part 'api/notifications_api.dart';
part 'api/schemas_api.dart';
part 'api/search_api.dart';
part 'api/uploads_api.dart';
part 'api/workspaces_api.dart';

part 'model/ai_status.dart';
part 'model/approve_action.dart';
part 'model/ask_conversation_detail.dart';
part 'model/ask_conversation_out.dart';
part 'model/ask_message_out.dart';
part 'model/ask_step.dart';
part 'model/asset_comment_create.dart';
part 'model/asset_comment_out.dart';
part 'model/asset_create.dart';
part 'model/asset_history_out.dart';
part 'model/asset_label_create.dart';
part 'model/asset_label_out.dart';
part 'model/asset_out.dart';
part 'model/asset_update.dart';
part 'model/assist_in.dart';
part 'model/attachment_out.dart';
part 'model/chat_in.dart';
part 'model/close_review_in.dart';
part 'model/decide_in.dart';
part 'model/decide_replacement_in.dart';
part 'model/decision_in.dart';
part 'model/device_in.dart';
part 'model/document_create.dart';
part 'model/document_out.dart';
part 'model/document_relation_create.dart';
part 'model/document_relation_out.dart';
part 'model/document_revision_create.dart';
part 'model/document_revision_out.dart';
part 'model/document_revision_update.dart';
part 'model/document_update.dart';
part 'model/draft_document_in.dart';
part 'model/draft_document_out.dart';
part 'model/global_value_out.dart';
part 'model/graph_edge_out.dart';
part 'model/graph_node_out.dart';
part 'model/graph_out.dart';
part 'model/guide_in.dart';
part 'model/http_validation_error.dart';
part 'model/issue_comment_create.dart';
part 'model/issue_comment_out.dart';
part 'model/issue_create.dart';
part 'model/issue_out.dart';
part 'model/issue_update.dart';
part 'model/me_out.dart';
part 'model/mentioned_object.dart';
part 'model/my_workspace_out.dart';
part 'model/observation_in.dart';
part 'model/outcome_in.dart';
part 'model/replace_in.dart';
part 'model/revoke_in.dart';
part 'model/schema_out.dart';
part 'model/semantic_edge_out.dart';
part 'model/semantic_graph_out.dart';
part 'model/subscription_in.dart';
part 'model/swap_in.dart';
part 'model/transition_in.dart';
part 'model/upload_in.dart';
part 'model/validation_error.dart';


/// An [ApiClient] instance that uses the default values obtained from
/// the OpenAPI specification file.
var defaultApiClient = ApiClient();

const _delimiters = {'csv': ',', 'ssv': ' ', 'tsv': '\t', 'pipes': '|'};
const _dateEpochMarker = 'epoch';
const _deepEquality = DeepCollectionEquality();
final _dateFormatter = DateFormat('yyyy-MM-dd');
final _regList = RegExp(r'^List<(.*)>$');
final _regSet = RegExp(r'^Set<(.*)>$');
final _regMap = RegExp(r'^Map<String,(.*)>$');

bool _isEpochMarker(String? pattern) => pattern == _dateEpochMarker || pattern == '/$_dateEpochMarker/';
