//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class SourceIn {
  /// Returns a new [SourceIn] instance.
  SourceIn({
    this.filename,
    this.kind,
    this.originalDate,
    this.sender,
    this.subject,
    required this.text,
    this.textIsCurrent = false,
  });

  String? filename;

  SourceInKindEnum? kind;

  String? originalDate;

  String? sender;

  String? subject;

  String text;

  bool textIsCurrent;

  @override
  bool operator ==(Object other) => identical(this, other) || other is SourceIn &&
    other.filename == filename &&
    other.kind == kind &&
    other.originalDate == originalDate &&
    other.sender == sender &&
    other.subject == subject &&
    other.text == text &&
    other.textIsCurrent == textIsCurrent;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (filename == null ? 0 : filename!.hashCode) +
    (kind == null ? 0 : kind!.hashCode) +
    (originalDate == null ? 0 : originalDate!.hashCode) +
    (sender == null ? 0 : sender!.hashCode) +
    (subject == null ? 0 : subject!.hashCode) +
    (text.hashCode) +
    (textIsCurrent.hashCode);

  @override
  String toString() => 'SourceIn[filename=$filename, kind=$kind, originalDate=$originalDate, sender=$sender, subject=$subject, text=$text, textIsCurrent=$textIsCurrent]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.filename != null) {
      json[r'filename'] = this.filename;
    } else {
      json[r'filename'] = null;
    }
    if (this.kind != null) {
      json[r'kind'] = this.kind;
    } else {
      json[r'kind'] = null;
    }
    if (this.originalDate != null) {
      json[r'original_date'] = this.originalDate;
    } else {
      json[r'original_date'] = null;
    }
    if (this.sender != null) {
      json[r'sender'] = this.sender;
    } else {
      json[r'sender'] = null;
    }
    if (this.subject != null) {
      json[r'subject'] = this.subject;
    } else {
      json[r'subject'] = null;
    }
      json[r'text'] = this.text;
      json[r'text_is_current'] = this.textIsCurrent;
    return json;
  }

  /// Returns a new [SourceIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static SourceIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "SourceIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "SourceIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return SourceIn(
        filename: mapValueOfType<String>(json, r'filename'),
        kind: SourceInKindEnum.fromJson(json[r'kind']),
        originalDate: mapValueOfType<String>(json, r'original_date'),
        sender: mapValueOfType<String>(json, r'sender'),
        subject: mapValueOfType<String>(json, r'subject'),
        text: mapValueOfType<String>(json, r'text')!,
        textIsCurrent: mapValueOfType<bool>(json, r'text_is_current') ?? false,
      );
    }
    return null;
  }

  static List<SourceIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <SourceIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = SourceIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, SourceIn> mapFromJson(dynamic json) {
    final map = <String, SourceIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = SourceIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of SourceIn-objects as value to a dart map
  static Map<String, List<SourceIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<SourceIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = SourceIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'text',
  };
}


class SourceInKindEnum {
  /// Instantiate a new enum with the provided [value].
  const SourceInKindEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const paste = SourceInKindEnum._(r'paste');
  static const email = SourceInKindEnum._(r'email');
  static const intake = SourceInKindEnum._(r'intake');
  static const import_ = SourceInKindEnum._(r'import');

  /// List of all possible values in this [enum][SourceInKindEnum].
  static const values = <SourceInKindEnum>[
    paste,
    email,
    intake,
    import_,
  ];

  static SourceInKindEnum? fromJson(dynamic value) => SourceInKindEnumTypeTransformer().decode(value);

  static List<SourceInKindEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <SourceInKindEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = SourceInKindEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [SourceInKindEnum] to String,
/// and [decode] dynamic data back to [SourceInKindEnum].
class SourceInKindEnumTypeTransformer {
  factory SourceInKindEnumTypeTransformer() => _instance ??= const SourceInKindEnumTypeTransformer._();

  const SourceInKindEnumTypeTransformer._();

  String encode(SourceInKindEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a SourceInKindEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  SourceInKindEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'paste': return SourceInKindEnum.paste;
        case r'email': return SourceInKindEnum.email;
        case r'intake': return SourceInKindEnum.intake;
        case r'import': return SourceInKindEnum.import_;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [SourceInKindEnumTypeTransformer] instance.
  static SourceInKindEnumTypeTransformer? _instance;
}


