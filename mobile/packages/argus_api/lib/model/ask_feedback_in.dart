//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class AskFeedbackIn {
  /// Returns a new [AskFeedbackIn] instance.
  AskFeedbackIn({
    this.answerIndex,
    this.comment,
    required this.rating,
  });

  /// Minimum value: 0
  int? answerIndex;

  String? comment;

  AskFeedbackInRatingEnum rating;

  @override
  bool operator ==(Object other) => identical(this, other) || other is AskFeedbackIn &&
    other.answerIndex == answerIndex &&
    other.comment == comment &&
    other.rating == rating;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (answerIndex == null ? 0 : answerIndex!.hashCode) +
    (comment == null ? 0 : comment!.hashCode) +
    (rating.hashCode);

  @override
  String toString() => 'AskFeedbackIn[answerIndex=$answerIndex, comment=$comment, rating=$rating]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.answerIndex != null) {
      json[r'answer_index'] = this.answerIndex;
    } else {
      json[r'answer_index'] = null;
    }
    if (this.comment != null) {
      json[r'comment'] = this.comment;
    } else {
      json[r'comment'] = null;
    }
      json[r'rating'] = this.rating;
    return json;
  }

  /// Returns a new [AskFeedbackIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static AskFeedbackIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "AskFeedbackIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "AskFeedbackIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return AskFeedbackIn(
        answerIndex: mapValueOfType<int>(json, r'answer_index'),
        comment: mapValueOfType<String>(json, r'comment'),
        rating: AskFeedbackInRatingEnum.fromJson(json[r'rating'])!,
      );
    }
    return null;
  }

  static List<AskFeedbackIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <AskFeedbackIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = AskFeedbackIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, AskFeedbackIn> mapFromJson(dynamic json) {
    final map = <String, AskFeedbackIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = AskFeedbackIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of AskFeedbackIn-objects as value to a dart map
  static Map<String, List<AskFeedbackIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<AskFeedbackIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = AskFeedbackIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'rating',
  };
}


class AskFeedbackInRatingEnum {
  /// Instantiate a new enum with the provided [value].
  const AskFeedbackInRatingEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const up = AskFeedbackInRatingEnum._(r'up');
  static const down = AskFeedbackInRatingEnum._(r'down');

  /// List of all possible values in this [enum][AskFeedbackInRatingEnum].
  static const values = <AskFeedbackInRatingEnum>[
    up,
    down,
  ];

  static AskFeedbackInRatingEnum? fromJson(dynamic value) => AskFeedbackInRatingEnumTypeTransformer().decode(value);

  static List<AskFeedbackInRatingEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <AskFeedbackInRatingEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = AskFeedbackInRatingEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [AskFeedbackInRatingEnum] to String,
/// and [decode] dynamic data back to [AskFeedbackInRatingEnum].
class AskFeedbackInRatingEnumTypeTransformer {
  factory AskFeedbackInRatingEnumTypeTransformer() => _instance ??= const AskFeedbackInRatingEnumTypeTransformer._();

  const AskFeedbackInRatingEnumTypeTransformer._();

  String encode(AskFeedbackInRatingEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a AskFeedbackInRatingEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  AskFeedbackInRatingEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'up': return AskFeedbackInRatingEnum.up;
        case r'down': return AskFeedbackInRatingEnum.down;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [AskFeedbackInRatingEnumTypeTransformer] instance.
  static AskFeedbackInRatingEnumTypeTransformer? _instance;
}


