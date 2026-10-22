//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class AskMessageOut {
  /// Returns a new [AskMessageOut] instance.
  AskMessageOut({
    this.content = '',
    this.createdAt,
    this.error,
    required this.id,
    this.rating,
    required this.role,
    this.seconds,
    required this.seq,
    this.steps = const [],
    this.stopped,
  });

  String content;

  DateTime? createdAt;

  String? error;

  String id;

  String? rating;

  String role;

  num? seconds;

  int seq;

  List<AskStep>? steps;

  String? stopped;

  @override
  bool operator ==(Object other) => identical(this, other) || other is AskMessageOut &&
    other.content == content &&
    other.createdAt == createdAt &&
    other.error == error &&
    other.id == id &&
    other.rating == rating &&
    other.role == role &&
    other.seconds == seconds &&
    other.seq == seq &&
    _deepEquality.equals(other.steps, steps) &&
    other.stopped == stopped;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (content.hashCode) +
    (createdAt == null ? 0 : createdAt!.hashCode) +
    (error == null ? 0 : error!.hashCode) +
    (id.hashCode) +
    (rating == null ? 0 : rating!.hashCode) +
    (role.hashCode) +
    (seconds == null ? 0 : seconds!.hashCode) +
    (seq.hashCode) +
    (steps == null ? 0 : steps!.hashCode) +
    (stopped == null ? 0 : stopped!.hashCode);

  @override
  String toString() => 'AskMessageOut[content=$content, createdAt=$createdAt, error=$error, id=$id, rating=$rating, role=$role, seconds=$seconds, seq=$seq, steps=$steps, stopped=$stopped]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'content'] = this.content;
    if (this.createdAt != null) {
      json[r'created_at'] = this.createdAt!.toUtc().toIso8601String();
    } else {
      json[r'created_at'] = null;
    }
    if (this.error != null) {
      json[r'error'] = this.error;
    } else {
      json[r'error'] = null;
    }
      json[r'id'] = this.id;
    if (this.rating != null) {
      json[r'rating'] = this.rating;
    } else {
      json[r'rating'] = null;
    }
      json[r'role'] = this.role;
    if (this.seconds != null) {
      json[r'seconds'] = this.seconds;
    } else {
      json[r'seconds'] = null;
    }
      json[r'seq'] = this.seq;
    if (this.steps != null) {
      json[r'steps'] = this.steps;
    } else {
      json[r'steps'] = null;
    }
    if (this.stopped != null) {
      json[r'stopped'] = this.stopped;
    } else {
      json[r'stopped'] = null;
    }
    return json;
  }

  /// Returns a new [AskMessageOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static AskMessageOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "AskMessageOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "AskMessageOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return AskMessageOut(
        content: mapValueOfType<String>(json, r'content') ?? '',
        createdAt: mapDateTime(json, r'created_at', r''),
        error: mapValueOfType<String>(json, r'error'),
        id: mapValueOfType<String>(json, r'id')!,
        rating: mapValueOfType<String>(json, r'rating'),
        role: mapValueOfType<String>(json, r'role')!,
        seconds: json[r'seconds'] == null
            ? null
            : num.parse('${json[r'seconds']}'),
        seq: mapValueOfType<int>(json, r'seq')!,
        steps: AskStep.listFromJson(json[r'steps']),
        stopped: mapValueOfType<String>(json, r'stopped'),
      );
    }
    return null;
  }

  static List<AskMessageOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <AskMessageOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = AskMessageOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, AskMessageOut> mapFromJson(dynamic json) {
    final map = <String, AskMessageOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = AskMessageOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of AskMessageOut-objects as value to a dart map
  static Map<String, List<AskMessageOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<AskMessageOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = AskMessageOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'id',
    'role',
    'seq',
  };
}

