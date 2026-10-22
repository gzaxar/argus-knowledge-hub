//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class ReshapeSave {
  /// Returns a new [ReshapeSave] instance.
  ReshapeSave({
    this.authorityLevel,
    this.code,
    this.confidentiality,
    this.confirmDocumentDate = false,
    this.dates,
    required this.documentTypeUid,
    this.extraction,
    this.issues,
    this.linkAssets = const [],
    required this.markdown,
    this.model,
    required this.source_,
    required this.template,
    required this.title,
  });

  ReshapeSaveAuthorityLevelEnum? authorityLevel;

  String? code;

  ReshapeSaveConfidentialityEnum? confidentiality;

  bool confirmDocumentDate;

  ///
  /// Please note: This property should have been non-nullable! Since the specification file
  /// does not include a default value (using the "default:" property), however, the generated
  /// source code must fall back to having a nullable type.
  /// Consider adding a "default:" property in the specification file to hide this note.
  ///
  Object? dates;

  String documentTypeUid;

  ///
  /// Please note: This property should have been non-nullable! Since the specification file
  /// does not include a default value (using the "default:" property), however, the generated
  /// source code must fall back to having a nullable type.
  /// Consider adding a "default:" property in the specification file to hide this note.
  ///
  Object? extraction;

  Object? issues;

  List<String> linkAssets;

  String markdown;

  String? model;

  SourceIn source_;

  /// the template the preview used: official:<id>, uid or uid@version
  String template;

  String title;

  @override
  bool operator ==(Object other) => identical(this, other) || other is ReshapeSave &&
    other.authorityLevel == authorityLevel &&
    other.code == code &&
    other.confidentiality == confidentiality &&
    other.confirmDocumentDate == confirmDocumentDate &&
    other.dates == dates &&
    other.documentTypeUid == documentTypeUid &&
    other.extraction == extraction &&
    other.issues == issues &&
    _deepEquality.equals(other.linkAssets, linkAssets) &&
    other.markdown == markdown &&
    other.model == model &&
    other.source_ == source_ &&
    other.template == template &&
    other.title == title;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (authorityLevel == null ? 0 : authorityLevel!.hashCode) +
    (code == null ? 0 : code!.hashCode) +
    (confidentiality == null ? 0 : confidentiality!.hashCode) +
    (confirmDocumentDate.hashCode) +
    (dates == null ? 0 : dates!.hashCode) +
    (documentTypeUid.hashCode) +
    (extraction == null ? 0 : extraction!.hashCode) +
    (issues == null ? 0 : issues!.hashCode) +
    (linkAssets.hashCode) +
    (markdown.hashCode) +
    (model == null ? 0 : model!.hashCode) +
    (source_.hashCode) +
    (template.hashCode) +
    (title.hashCode);

  @override
  String toString() => 'ReshapeSave[authorityLevel=$authorityLevel, code=$code, confidentiality=$confidentiality, confirmDocumentDate=$confirmDocumentDate, dates=$dates, documentTypeUid=$documentTypeUid, extraction=$extraction, issues=$issues, linkAssets=$linkAssets, markdown=$markdown, model=$model, source_=$source_, template=$template, title=$title]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.authorityLevel != null) {
      json[r'authority_level'] = this.authorityLevel;
    } else {
      json[r'authority_level'] = null;
    }
    if (this.code != null) {
      json[r'code'] = this.code;
    } else {
      json[r'code'] = null;
    }
    if (this.confidentiality != null) {
      json[r'confidentiality'] = this.confidentiality;
    } else {
      json[r'confidentiality'] = null;
    }
      json[r'confirm_document_date'] = this.confirmDocumentDate;
    if (this.dates != null) {
      json[r'dates'] = this.dates;
    } else {
      json[r'dates'] = null;
    }
      json[r'document_type_uid'] = this.documentTypeUid;
    if (this.extraction != null) {
      json[r'extraction'] = this.extraction;
    } else {
      json[r'extraction'] = null;
    }
    if (this.issues != null) {
      json[r'issues'] = this.issues;
    } else {
      json[r'issues'] = null;
    }
      json[r'link_assets'] = this.linkAssets;
      json[r'markdown'] = this.markdown;
    if (this.model != null) {
      json[r'model'] = this.model;
    } else {
      json[r'model'] = null;
    }
      json[r'source'] = this.source_;
      json[r'template'] = this.template;
      json[r'title'] = this.title;
    return json;
  }

  /// Returns a new [ReshapeSave] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static ReshapeSave? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "ReshapeSave[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "ReshapeSave[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return ReshapeSave(
        authorityLevel: ReshapeSaveAuthorityLevelEnum.fromJson(json[r'authority_level']),
        code: mapValueOfType<String>(json, r'code'),
        confidentiality: ReshapeSaveConfidentialityEnum.fromJson(json[r'confidentiality']),
        confirmDocumentDate: mapValueOfType<bool>(json, r'confirm_document_date') ?? false,
        dates: mapValueOfType<Object>(json, r'dates'),
        documentTypeUid: mapValueOfType<String>(json, r'document_type_uid')!,
        extraction: mapValueOfType<Object>(json, r'extraction'),
        issues: mapValueOfType<Object>(json, r'issues'),
        linkAssets: json[r'link_assets'] is Iterable
            ? (json[r'link_assets'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        markdown: mapValueOfType<String>(json, r'markdown')!,
        model: mapValueOfType<String>(json, r'model'),
        source_: SourceIn.fromJson(json[r'source'])!,
        template: mapValueOfType<String>(json, r'template')!,
        title: mapValueOfType<String>(json, r'title')!,
      );
    }
    return null;
  }

  static List<ReshapeSave> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ReshapeSave>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ReshapeSave.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, ReshapeSave> mapFromJson(dynamic json) {
    final map = <String, ReshapeSave>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = ReshapeSave.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of ReshapeSave-objects as value to a dart map
  static Map<String, List<ReshapeSave>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<ReshapeSave>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = ReshapeSave.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'document_type_uid',
    'markdown',
    'source',
    'template',
    'title',
  };
}


class ReshapeSaveAuthorityLevelEnum {
  /// Instantiate a new enum with the provided [value].
  const ReshapeSaveAuthorityLevelEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const ufficiale = ReshapeSaveAuthorityLevelEnum._(r'ufficiale');
  static const informativo = ReshapeSaveAuthorityLevelEnum._(r'informativo');
  static const bozzaInterna = ReshapeSaveAuthorityLevelEnum._(r'bozza_interna');

  /// List of all possible values in this [enum][ReshapeSaveAuthorityLevelEnum].
  static const values = <ReshapeSaveAuthorityLevelEnum>[
    ufficiale,
    informativo,
    bozzaInterna,
  ];

  static ReshapeSaveAuthorityLevelEnum? fromJson(dynamic value) => ReshapeSaveAuthorityLevelEnumTypeTransformer().decode(value);

  static List<ReshapeSaveAuthorityLevelEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ReshapeSaveAuthorityLevelEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ReshapeSaveAuthorityLevelEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [ReshapeSaveAuthorityLevelEnum] to String,
/// and [decode] dynamic data back to [ReshapeSaveAuthorityLevelEnum].
class ReshapeSaveAuthorityLevelEnumTypeTransformer {
  factory ReshapeSaveAuthorityLevelEnumTypeTransformer() => _instance ??= const ReshapeSaveAuthorityLevelEnumTypeTransformer._();

  const ReshapeSaveAuthorityLevelEnumTypeTransformer._();

  String encode(ReshapeSaveAuthorityLevelEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a ReshapeSaveAuthorityLevelEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  ReshapeSaveAuthorityLevelEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'ufficiale': return ReshapeSaveAuthorityLevelEnum.ufficiale;
        case r'informativo': return ReshapeSaveAuthorityLevelEnum.informativo;
        case r'bozza_interna': return ReshapeSaveAuthorityLevelEnum.bozzaInterna;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [ReshapeSaveAuthorityLevelEnumTypeTransformer] instance.
  static ReshapeSaveAuthorityLevelEnumTypeTransformer? _instance;
}



class ReshapeSaveConfidentialityEnum {
  /// Instantiate a new enum with the provided [value].
  const ReshapeSaveConfidentialityEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const pubblico = ReshapeSaveConfidentialityEnum._(r'pubblico');
  static const interno = ReshapeSaveConfidentialityEnum._(r'interno');
  static const riservato = ReshapeSaveConfidentialityEnum._(r'riservato');

  /// List of all possible values in this [enum][ReshapeSaveConfidentialityEnum].
  static const values = <ReshapeSaveConfidentialityEnum>[
    pubblico,
    interno,
    riservato,
  ];

  static ReshapeSaveConfidentialityEnum? fromJson(dynamic value) => ReshapeSaveConfidentialityEnumTypeTransformer().decode(value);

  static List<ReshapeSaveConfidentialityEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ReshapeSaveConfidentialityEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ReshapeSaveConfidentialityEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [ReshapeSaveConfidentialityEnum] to String,
/// and [decode] dynamic data back to [ReshapeSaveConfidentialityEnum].
class ReshapeSaveConfidentialityEnumTypeTransformer {
  factory ReshapeSaveConfidentialityEnumTypeTransformer() => _instance ??= const ReshapeSaveConfidentialityEnumTypeTransformer._();

  const ReshapeSaveConfidentialityEnumTypeTransformer._();

  String encode(ReshapeSaveConfidentialityEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a ReshapeSaveConfidentialityEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  ReshapeSaveConfidentialityEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'pubblico': return ReshapeSaveConfidentialityEnum.pubblico;
        case r'interno': return ReshapeSaveConfidentialityEnum.interno;
        case r'riservato': return ReshapeSaveConfidentialityEnum.riservato;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [ReshapeSaveConfidentialityEnumTypeTransformer] instance.
  static ReshapeSaveConfidentialityEnumTypeTransformer? _instance;
}


