//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class MyWorkspaceOut {
  /// Returns a new [MyWorkspaceOut] instance.
  MyWorkspaceOut({
    required this.canApproveDocuments,
    required this.canCreate,
    required this.canCreateDocuments,
    required this.canCreateTickets,
    required this.canDelete,
    required this.canDeleteDocuments,
    required this.canDeleteTickets,
    required this.canModify,
    required this.canModifyDocuments,
    required this.canModifyTickets,
    required this.canRead,
    required this.canReadDocuments,
    required this.canReadTickets,
    required this.createdAt,
    required this.id,
    required this.isGlobal,
    required this.name,
    this.role,
    this.siteId,
  });

  bool canApproveDocuments;

  bool canCreate;

  bool canCreateDocuments;

  bool canCreateTickets;

  bool canDelete;

  bool canDeleteDocuments;

  bool canDeleteTickets;

  bool canModify;

  bool canModifyDocuments;

  bool canModifyTickets;

  bool canRead;

  bool canReadDocuments;

  bool canReadTickets;

  DateTime createdAt;

  String id;

  bool isGlobal;

  String name;

  String? role;

  String? siteId;

  @override
  bool operator ==(Object other) => identical(this, other) || other is MyWorkspaceOut &&
    other.canApproveDocuments == canApproveDocuments &&
    other.canCreate == canCreate &&
    other.canCreateDocuments == canCreateDocuments &&
    other.canCreateTickets == canCreateTickets &&
    other.canDelete == canDelete &&
    other.canDeleteDocuments == canDeleteDocuments &&
    other.canDeleteTickets == canDeleteTickets &&
    other.canModify == canModify &&
    other.canModifyDocuments == canModifyDocuments &&
    other.canModifyTickets == canModifyTickets &&
    other.canRead == canRead &&
    other.canReadDocuments == canReadDocuments &&
    other.canReadTickets == canReadTickets &&
    other.createdAt == createdAt &&
    other.id == id &&
    other.isGlobal == isGlobal &&
    other.name == name &&
    other.role == role &&
    other.siteId == siteId;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (canApproveDocuments.hashCode) +
    (canCreate.hashCode) +
    (canCreateDocuments.hashCode) +
    (canCreateTickets.hashCode) +
    (canDelete.hashCode) +
    (canDeleteDocuments.hashCode) +
    (canDeleteTickets.hashCode) +
    (canModify.hashCode) +
    (canModifyDocuments.hashCode) +
    (canModifyTickets.hashCode) +
    (canRead.hashCode) +
    (canReadDocuments.hashCode) +
    (canReadTickets.hashCode) +
    (createdAt.hashCode) +
    (id.hashCode) +
    (isGlobal.hashCode) +
    (name.hashCode) +
    (role == null ? 0 : role!.hashCode) +
    (siteId == null ? 0 : siteId!.hashCode);

  @override
  String toString() => 'MyWorkspaceOut[canApproveDocuments=$canApproveDocuments, canCreate=$canCreate, canCreateDocuments=$canCreateDocuments, canCreateTickets=$canCreateTickets, canDelete=$canDelete, canDeleteDocuments=$canDeleteDocuments, canDeleteTickets=$canDeleteTickets, canModify=$canModify, canModifyDocuments=$canModifyDocuments, canModifyTickets=$canModifyTickets, canRead=$canRead, canReadDocuments=$canReadDocuments, canReadTickets=$canReadTickets, createdAt=$createdAt, id=$id, isGlobal=$isGlobal, name=$name, role=$role, siteId=$siteId]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'can_approve_documents'] = this.canApproveDocuments;
      json[r'can_create'] = this.canCreate;
      json[r'can_create_documents'] = this.canCreateDocuments;
      json[r'can_create_tickets'] = this.canCreateTickets;
      json[r'can_delete'] = this.canDelete;
      json[r'can_delete_documents'] = this.canDeleteDocuments;
      json[r'can_delete_tickets'] = this.canDeleteTickets;
      json[r'can_modify'] = this.canModify;
      json[r'can_modify_documents'] = this.canModifyDocuments;
      json[r'can_modify_tickets'] = this.canModifyTickets;
      json[r'can_read'] = this.canRead;
      json[r'can_read_documents'] = this.canReadDocuments;
      json[r'can_read_tickets'] = this.canReadTickets;
      json[r'created_at'] = this.createdAt.toUtc().toIso8601String();
      json[r'id'] = this.id;
      json[r'is_global'] = this.isGlobal;
      json[r'name'] = this.name;
    if (this.role != null) {
      json[r'role'] = this.role;
    } else {
      json[r'role'] = null;
    }
    if (this.siteId != null) {
      json[r'site_id'] = this.siteId;
    } else {
      json[r'site_id'] = null;
    }
    return json;
  }

  /// Returns a new [MyWorkspaceOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static MyWorkspaceOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "MyWorkspaceOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "MyWorkspaceOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return MyWorkspaceOut(
        canApproveDocuments: mapValueOfType<bool>(json, r'can_approve_documents')!,
        canCreate: mapValueOfType<bool>(json, r'can_create')!,
        canCreateDocuments: mapValueOfType<bool>(json, r'can_create_documents')!,
        canCreateTickets: mapValueOfType<bool>(json, r'can_create_tickets')!,
        canDelete: mapValueOfType<bool>(json, r'can_delete')!,
        canDeleteDocuments: mapValueOfType<bool>(json, r'can_delete_documents')!,
        canDeleteTickets: mapValueOfType<bool>(json, r'can_delete_tickets')!,
        canModify: mapValueOfType<bool>(json, r'can_modify')!,
        canModifyDocuments: mapValueOfType<bool>(json, r'can_modify_documents')!,
        canModifyTickets: mapValueOfType<bool>(json, r'can_modify_tickets')!,
        canRead: mapValueOfType<bool>(json, r'can_read')!,
        canReadDocuments: mapValueOfType<bool>(json, r'can_read_documents')!,
        canReadTickets: mapValueOfType<bool>(json, r'can_read_tickets')!,
        createdAt: mapDateTime(json, r'created_at', r'')!,
        id: mapValueOfType<String>(json, r'id')!,
        isGlobal: mapValueOfType<bool>(json, r'is_global')!,
        name: mapValueOfType<String>(json, r'name')!,
        role: mapValueOfType<String>(json, r'role'),
        siteId: mapValueOfType<String>(json, r'site_id'),
      );
    }
    return null;
  }

  static List<MyWorkspaceOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <MyWorkspaceOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = MyWorkspaceOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, MyWorkspaceOut> mapFromJson(dynamic json) {
    final map = <String, MyWorkspaceOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = MyWorkspaceOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of MyWorkspaceOut-objects as value to a dart map
  static Map<String, List<MyWorkspaceOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<MyWorkspaceOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = MyWorkspaceOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'can_approve_documents',
    'can_create',
    'can_create_documents',
    'can_create_tickets',
    'can_delete',
    'can_delete_documents',
    'can_delete_tickets',
    'can_modify',
    'can_modify_documents',
    'can_modify_tickets',
    'can_read',
    'can_read_documents',
    'can_read_tickets',
    'created_at',
    'id',
    'is_global',
    'name',
  };
}

