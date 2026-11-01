//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class SchemaOut {
  /// Returns a new [SchemaOut] instance.
  SchemaOut({
    required this.appliesTo,
    required this.attributes,
    required this.createdAt,
    this.description,
    this.iconUid,
    required this.isConcrete,
    required this.isGlobal,
    required this.metadata,
    required this.name,
    this.origin,
    this.parentSchemaUid,
    required this.uid,
    required this.updatedAt,
    required this.version,
    required this.workspaceId,
  });

  String appliesTo;

  Object? attributes;

  DateTime createdAt;

  String? description;

  String? iconUid;

  bool isConcrete;

  bool isGlobal;

  Object metadata;

  String name;

  Object? origin;

  String? parentSchemaUid;

  String uid;

  DateTime updatedAt;

  int version;

  String workspaceId;

  @override
  bool operator ==(Object other) => identical(this, other) || other is SchemaOut &&
    other.appliesTo == appliesTo &&
    other.attributes == attributes &&
    other.createdAt == createdAt &&
    other.description == description &&
    other.iconUid == iconUid &&
    other.isConcrete == isConcrete &&
    other.isGlobal == isGlobal &&
    other.metadata == metadata &&
    other.name == name &&
    other.origin == origin &&
    other.parentSchemaUid == parentSchemaUid &&
    other.uid == uid &&
    other.updatedAt == updatedAt &&
    other.version == version &&
    other.workspaceId == workspaceId;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (appliesTo.hashCode) +
    (attributes == null ? 0 : attributes!.hashCode) +
    (createdAt.hashCode) +
    (description == null ? 0 : description!.hashCode) +
    (iconUid == null ? 0 : iconUid!.hashCode) +
    (isConcrete.hashCode) +
    (isGlobal.hashCode) +
    (metadata.hashCode) +
    (name.hashCode) +
    (origin == null ? 0 : origin!.hashCode) +
    (parentSchemaUid == null ? 0 : parentSchemaUid!.hashCode) +
    (uid.hashCode) +
    (updatedAt.hashCode) +
    (version.hashCode) +
    (workspaceId.hashCode);

  @override
  String toString() => 'SchemaOut[appliesTo=$appliesTo, attributes=$attributes, createdAt=$createdAt, description=$description, iconUid=$iconUid, isConcrete=$isConcrete, isGlobal=$isGlobal, metadata=$metadata, name=$name, origin=$origin, parentSchemaUid=$parentSchemaUid, uid=$uid, updatedAt=$updatedAt, version=$version, workspaceId=$workspaceId]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'applies_to'] = this.appliesTo;
    if (this.attributes != null) {
      json[r'attributes'] = this.attributes;
    } else {
      json[r'attributes'] = null;
    }
      json[r'created_at'] = this.createdAt.toUtc().toIso8601String();
    if (this.description != null) {
      json[r'description'] = this.description;
    } else {
      json[r'description'] = null;
    }
    if (this.iconUid != null) {
      json[r'icon_uid'] = this.iconUid;
    } else {
      json[r'icon_uid'] = null;
    }
      json[r'is_concrete'] = this.isConcrete;
      json[r'is_global'] = this.isGlobal;
      json[r'metadata'] = this.metadata;
      json[r'name'] = this.name;
    if (this.origin != null) {
      json[r'origin'] = this.origin;
    } else {
      json[r'origin'] = null;
    }
    if (this.parentSchemaUid != null) {
      json[r'parent_schema_uid'] = this.parentSchemaUid;
    } else {
      json[r'parent_schema_uid'] = null;
    }
      json[r'uid'] = this.uid;
      json[r'updated_at'] = this.updatedAt.toUtc().toIso8601String();
      json[r'version'] = this.version;
      json[r'workspace_id'] = this.workspaceId;
    return json;
  }

  /// Returns a new [SchemaOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static SchemaOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "SchemaOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "SchemaOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return SchemaOut(
        appliesTo: mapValueOfType<String>(json, r'applies_to')!,
        attributes: mapValueOfType<Object>(json, r'attributes'),
        createdAt: mapDateTime(json, r'created_at', r'')!,
        description: mapValueOfType<String>(json, r'description'),
        iconUid: mapValueOfType<String>(json, r'icon_uid'),
        isConcrete: mapValueOfType<bool>(json, r'is_concrete')!,
        isGlobal: mapValueOfType<bool>(json, r'is_global')!,
        metadata: mapValueOfType<Object>(json, r'metadata')!,
        name: mapValueOfType<String>(json, r'name')!,
        origin: mapValueOfType<Object>(json, r'origin'),
        parentSchemaUid: mapValueOfType<String>(json, r'parent_schema_uid'),
        uid: mapValueOfType<String>(json, r'uid')!,
        updatedAt: mapDateTime(json, r'updated_at', r'')!,
        version: mapValueOfType<int>(json, r'version')!,
        workspaceId: mapValueOfType<String>(json, r'workspace_id')!,
      );
    }
    return null;
  }

  static List<SchemaOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <SchemaOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = SchemaOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, SchemaOut> mapFromJson(dynamic json) {
    final map = <String, SchemaOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = SchemaOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of SchemaOut-objects as value to a dart map
  static Map<String, List<SchemaOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<SchemaOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = SchemaOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'applies_to',
    'attributes',
    'created_at',
    'is_concrete',
    'is_global',
    'metadata',
    'name',
    'uid',
    'updated_at',
    'version',
    'workspace_id',
  };
}

