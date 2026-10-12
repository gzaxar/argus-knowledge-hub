//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class DecisionIn {
  /// Returns a new [DecisionIn] instance.
  DecisionIn({
    this.note,
  });

  String? note;

  @override
  bool operator ==(Object other) => identical(this, other) || other is DecisionIn &&
    other.note == note;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (note == null ? 0 : note!.hashCode);

  @override
  String toString() => 'DecisionIn[note=$note]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.note != null) {
      json[r'note'] = this.note;
    } else {
      json[r'note'] = null;
    }
    return json;
  }

  /// Returns a new [DecisionIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static DecisionIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "DecisionIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "DecisionIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return DecisionIn(
        note: mapValueOfType<String>(json, r'note'),
      );
    }
    return null;
  }

  static List<DecisionIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <DecisionIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = DecisionIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, DecisionIn> mapFromJson(dynamic json) {
    final map = <String, DecisionIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = DecisionIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of DecisionIn-objects as value to a dart map
  static Map<String, List<DecisionIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<DecisionIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = DecisionIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
  };
}

