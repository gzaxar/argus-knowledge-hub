//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class AssetUpdate {
  /// Returns a new [AssetUpdate] instance.
  AssetUpdate({
    this.attributes,
    this.avatarIconUid,
    this.deletedAt,
    this.inboundRelations = const [],
    this.isGlobal,
    this.name,
    this.outboundRelations = const [],
    this.schemaUid,
    this.type,
  });

  Object? attributes;

  String? avatarIconUid;

  DateTime? deletedAt;

  List<String>? inboundRelations;

  bool? isGlobal;

  String? name;

  List<String>? outboundRelations;

  String? schemaUid;

  String? type;

  @override
  bool operator ==(Object other) => identical(this, other) || other is AssetUpdate &&
    other.attributes == attributes &&
    other.avatarIconUid == avatarIconUid &&
    other.deletedAt == deletedAt &&
    _deepEquality.equals(other.inboundRelations, inboundRelations) &&
    other.isGlobal == isGlobal &&
    other.name == name &&
    _deepEquality.equals(other.outboundRelations, outboundRelations) &&
    other.schemaUid == schemaUid &&
    other.type == type;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (attributes == null ? 0 : attributes!.hashCode) +
    (avatarIconUid == null ? 0 : avatarIconUid!.hashCode) +
    (deletedAt == null ? 0 : deletedAt!.hashCode) +
    (inboundRelations == null ? 0 : inboundRelations!.hashCode) +
    (isGlobal == null ? 0 : isGlobal!.hashCode) +
    (name == null ? 0 : name!.hashCode) +
    (outboundRelations == null ? 0 : outboundRelations!.hashCode) +
    (schemaUid == null ? 0 : schemaUid!.hashCode) +
    (type == null ? 0 : type!.hashCode);

  @override
  String toString() => 'AssetUpdate[attributes=$attributes, avatarIconUid=$avatarIconUid, deletedAt=$deletedAt, inboundRelations=$inboundRelations, isGlobal=$isGlobal, name=$name, outboundRelations=$outboundRelations, schemaUid=$schemaUid, type=$type]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.attributes != null) {
      json[r'attributes'] = this.attributes;
    } else {
      json[r'attributes'] = null;
    }
    if (this.avatarIconUid != null) {
      json[r'avatar_icon_uid'] = this.avatarIconUid;
    } else {
      json[r'avatar_icon_uid'] = null;
    }
    if (this.deletedAt != null) {
      json[r'deleted_at'] = this.deletedAt!.toUtc().toIso8601String();
    } else {
      json[r'deleted_at'] = null;
    }
    if (this.inboundRelations != null) {
      json[r'inbound_relations'] = this.inboundRelations;
    } else {
      json[r'inbound_relations'] = null;
    }
    if (this.isGlobal != null) {
      json[r'is_global'] = this.isGlobal;
    } else {
      json[r'is_global'] = null;
    }
    if (this.name != null) {
      json[r'name'] = this.name;
    } else {
      json[r'name'] = null;
    }
    if (this.outboundRelations != null) {
      json[r'outbound_relations'] = this.outboundRelations;
    } else {
      json[r'outbound_relations'] = null;
    }
    if (this.schemaUid != null) {
      json[r'schema_uid'] = this.schemaUid;
    } else {
      json[r'schema_uid'] = null;
    }
    if (this.type != null) {
      json[r'type'] = this.type;
    } else {
      json[r'type'] = null;
    }
    return json;
  }

  /// Returns a new [AssetUpdate] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static AssetUpdate? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "AssetUpdate[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "AssetUpdate[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return AssetUpdate(
        attributes: mapValueOfType<Object>(json, r'attributes'),
        avatarIconUid: mapValueOfType<String>(json, r'avatar_icon_uid'),
        deletedAt: mapDateTime(json, r'deleted_at', r''),
        inboundRelations: json[r'inbound_relations'] is Iterable
            ? (json[r'inbound_relations'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        isGlobal: mapValueOfType<bool>(json, r'is_global'),
        name: mapValueOfType<String>(json, r'name'),
        outboundRelations: json[r'outbound_relations'] is Iterable
            ? (json[r'outbound_relations'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        schemaUid: mapValueOfType<String>(json, r'schema_uid'),
        type: mapValueOfType<String>(json, r'type'),
      );
    }
    return null;
  }

  static List<AssetUpdate> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <AssetUpdate>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = AssetUpdate.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, AssetUpdate> mapFromJson(dynamic json) {
    final map = <String, AssetUpdate>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = AssetUpdate.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of AssetUpdate-objects as value to a dart map
  static Map<String, List<AssetUpdate>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<AssetUpdate>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = AssetUpdate.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
  };
}

