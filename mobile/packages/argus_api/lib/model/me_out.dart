//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class MeOut {
  /// Returns a new [MeOut] instance.
  MeOut({
    required this.authType,
    this.catalogueMaintainer = false,
    this.email,
    this.isAdmin = false,
    this.name,
    this.userId,
    this.workspaceId,
  });

  MeOutAuthTypeEnum authType;

  bool catalogueMaintainer;

  String? email;

  bool isAdmin;

  String? name;

  String? userId;

  String? workspaceId;

  @override
  bool operator ==(Object other) => identical(this, other) || other is MeOut &&
    other.authType == authType &&
    other.catalogueMaintainer == catalogueMaintainer &&
    other.email == email &&
    other.isAdmin == isAdmin &&
    other.name == name &&
    other.userId == userId &&
    other.workspaceId == workspaceId;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (authType.hashCode) +
    (catalogueMaintainer.hashCode) +
    (email == null ? 0 : email!.hashCode) +
    (isAdmin.hashCode) +
    (name == null ? 0 : name!.hashCode) +
    (userId == null ? 0 : userId!.hashCode) +
    (workspaceId == null ? 0 : workspaceId!.hashCode);

  @override
  String toString() => 'MeOut[authType=$authType, catalogueMaintainer=$catalogueMaintainer, email=$email, isAdmin=$isAdmin, name=$name, userId=$userId, workspaceId=$workspaceId]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'auth_type'] = this.authType;
      json[r'catalogue_maintainer'] = this.catalogueMaintainer;
    if (this.email != null) {
      json[r'email'] = this.email;
    } else {
      json[r'email'] = null;
    }
      json[r'is_admin'] = this.isAdmin;
    if (this.name != null) {
      json[r'name'] = this.name;
    } else {
      json[r'name'] = null;
    }
    if (this.userId != null) {
      json[r'user_id'] = this.userId;
    } else {
      json[r'user_id'] = null;
    }
    if (this.workspaceId != null) {
      json[r'workspace_id'] = this.workspaceId;
    } else {
      json[r'workspace_id'] = null;
    }
    return json;
  }

  /// Returns a new [MeOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static MeOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "MeOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "MeOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return MeOut(
        authType: MeOutAuthTypeEnum.fromJson(json[r'auth_type'])!,
        catalogueMaintainer: mapValueOfType<bool>(json, r'catalogue_maintainer') ?? false,
        email: mapValueOfType<String>(json, r'email'),
        isAdmin: mapValueOfType<bool>(json, r'is_admin') ?? false,
        name: mapValueOfType<String>(json, r'name'),
        userId: mapValueOfType<String>(json, r'user_id'),
        workspaceId: mapValueOfType<String>(json, r'workspace_id'),
      );
    }
    return null;
  }

  static List<MeOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <MeOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = MeOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, MeOut> mapFromJson(dynamic json) {
    final map = <String, MeOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = MeOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of MeOut-objects as value to a dart map
  static Map<String, List<MeOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<MeOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = MeOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'auth_type',
  };
}


class MeOutAuthTypeEnum {
  /// Instantiate a new enum with the provided [value].
  const MeOutAuthTypeEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const pat = MeOutAuthTypeEnum._(r'pat');
  static const oidc = MeOutAuthTypeEnum._(r'oidc');

  /// List of all possible values in this [enum][MeOutAuthTypeEnum].
  static const values = <MeOutAuthTypeEnum>[
    pat,
    oidc,
  ];

  static MeOutAuthTypeEnum? fromJson(dynamic value) => MeOutAuthTypeEnumTypeTransformer().decode(value);

  static List<MeOutAuthTypeEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <MeOutAuthTypeEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = MeOutAuthTypeEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [MeOutAuthTypeEnum] to String,
/// and [decode] dynamic data back to [MeOutAuthTypeEnum].
class MeOutAuthTypeEnumTypeTransformer {
  factory MeOutAuthTypeEnumTypeTransformer() => _instance ??= const MeOutAuthTypeEnumTypeTransformer._();

  const MeOutAuthTypeEnumTypeTransformer._();

  String encode(MeOutAuthTypeEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a MeOutAuthTypeEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  MeOutAuthTypeEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'pat': return MeOutAuthTypeEnum.pat;
        case r'oidc': return MeOutAuthTypeEnum.oidc;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [MeOutAuthTypeEnumTypeTransformer] instance.
  static MeOutAuthTypeEnumTypeTransformer? _instance;
}


