//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class ReshapeIn {
  /// Returns a new [ReshapeIn] instance.
  ReshapeIn({
    this.confidentiality,
    required this.documentTypeUid,
    this.documentUid,
    required this.source_,
    this.template,
    this.templateSource,
    this.title,
  });

  ReshapeInConfidentialityEnum? confidentiality;

  String documentTypeUid;

  String? documentUid;

  SourceIn source_;

  String? template;

  String? templateSource;

  String? title;

  @override
  bool operator ==(Object other) => identical(this, other) || other is ReshapeIn &&
    other.confidentiality == confidentiality &&
    other.documentTypeUid == documentTypeUid &&
    other.documentUid == documentUid &&
    other.source_ == source_ &&
    other.template == template &&
    other.templateSource == templateSource &&
    other.title == title;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (confidentiality == null ? 0 : confidentiality!.hashCode) +
    (documentTypeUid.hashCode) +
    (documentUid == null ? 0 : documentUid!.hashCode) +
    (source_.hashCode) +
    (template == null ? 0 : template!.hashCode) +
    (templateSource == null ? 0 : templateSource!.hashCode) +
    (title == null ? 0 : title!.hashCode);

  @override
  String toString() => 'ReshapeIn[confidentiality=$confidentiality, documentTypeUid=$documentTypeUid, documentUid=$documentUid, source_=$source_, template=$template, templateSource=$templateSource, title=$title]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.confidentiality != null) {
      json[r'confidentiality'] = this.confidentiality;
    } else {
      json[r'confidentiality'] = null;
    }
      json[r'document_type_uid'] = this.documentTypeUid;
    if (this.documentUid != null) {
      json[r'document_uid'] = this.documentUid;
    } else {
      json[r'document_uid'] = null;
    }
      json[r'source'] = this.source_;
    if (this.template != null) {
      json[r'template'] = this.template;
    } else {
      json[r'template'] = null;
    }
    if (this.templateSource != null) {
      json[r'template_source'] = this.templateSource;
    } else {
      json[r'template_source'] = null;
    }
    if (this.title != null) {
      json[r'title'] = this.title;
    } else {
      json[r'title'] = null;
    }
    return json;
  }

  /// Returns a new [ReshapeIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static ReshapeIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "ReshapeIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "ReshapeIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return ReshapeIn(
        confidentiality: ReshapeInConfidentialityEnum.fromJson(json[r'confidentiality']),
        documentTypeUid: mapValueOfType<String>(json, r'document_type_uid')!,
        documentUid: mapValueOfType<String>(json, r'document_uid'),
        source_: SourceIn.fromJson(json[r'source'])!,
        template: mapValueOfType<String>(json, r'template'),
        templateSource: mapValueOfType<String>(json, r'template_source'),
        title: mapValueOfType<String>(json, r'title'),
      );
    }
    return null;
  }

  static List<ReshapeIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ReshapeIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ReshapeIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, ReshapeIn> mapFromJson(dynamic json) {
    final map = <String, ReshapeIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = ReshapeIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of ReshapeIn-objects as value to a dart map
  static Map<String, List<ReshapeIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<ReshapeIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = ReshapeIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'document_type_uid',
    'source',
  };
}


class ReshapeInConfidentialityEnum {
  /// Instantiate a new enum with the provided [value].
  const ReshapeInConfidentialityEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const pubblico = ReshapeInConfidentialityEnum._(r'pubblico');
  static const interno = ReshapeInConfidentialityEnum._(r'interno');
  static const riservato = ReshapeInConfidentialityEnum._(r'riservato');

  /// List of all possible values in this [enum][ReshapeInConfidentialityEnum].
  static const values = <ReshapeInConfidentialityEnum>[
    pubblico,
    interno,
    riservato,
  ];

  static ReshapeInConfidentialityEnum? fromJson(dynamic value) => ReshapeInConfidentialityEnumTypeTransformer().decode(value);

  static List<ReshapeInConfidentialityEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ReshapeInConfidentialityEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ReshapeInConfidentialityEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [ReshapeInConfidentialityEnum] to String,
/// and [decode] dynamic data back to [ReshapeInConfidentialityEnum].
class ReshapeInConfidentialityEnumTypeTransformer {
  factory ReshapeInConfidentialityEnumTypeTransformer() => _instance ??= const ReshapeInConfidentialityEnumTypeTransformer._();

  const ReshapeInConfidentialityEnumTypeTransformer._();

  String encode(ReshapeInConfidentialityEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a ReshapeInConfidentialityEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  ReshapeInConfidentialityEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'pubblico': return ReshapeInConfidentialityEnum.pubblico;
        case r'interno': return ReshapeInConfidentialityEnum.interno;
        case r'riservato': return ReshapeInConfidentialityEnum.riservato;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [ReshapeInConfidentialityEnumTypeTransformer] instance.
  static ReshapeInConfidentialityEnumTypeTransformer? _instance;
}


