//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class ActivityAction {
  /// Returns a new [ActivityAction] instance.
  ActivityAction({
    this.at,
    this.end,
    this.note,
    this.start,
  });

  DateTime? at;

  DateTime? end;

  String? note;

  DateTime? start;

  @override
  bool operator ==(Object other) => identical(this, other) || other is ActivityAction &&
    other.at == at &&
    other.end == end &&
    other.note == note &&
    other.start == start;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (at == null ? 0 : at!.hashCode) +
    (end == null ? 0 : end!.hashCode) +
    (note == null ? 0 : note!.hashCode) +
    (start == null ? 0 : start!.hashCode);

  @override
  String toString() => 'ActivityAction[at=$at, end=$end, note=$note, start=$start]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.at != null) {
      json[r'at'] = this.at!.toUtc().toIso8601String();
    } else {
      json[r'at'] = null;
    }
    if (this.end != null) {
      json[r'end'] = this.end!.toUtc().toIso8601String();
    } else {
      json[r'end'] = null;
    }
    if (this.note != null) {
      json[r'note'] = this.note;
    } else {
      json[r'note'] = null;
    }
    if (this.start != null) {
      json[r'start'] = this.start!.toUtc().toIso8601String();
    } else {
      json[r'start'] = null;
    }
    return json;
  }

  /// Returns a new [ActivityAction] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static ActivityAction? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "ActivityAction[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "ActivityAction[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return ActivityAction(
        at: mapDateTime(json, r'at', r''),
        end: mapDateTime(json, r'end', r''),
        note: mapValueOfType<String>(json, r'note'),
        start: mapDateTime(json, r'start', r''),
      );
    }
    return null;
  }

  static List<ActivityAction> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ActivityAction>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ActivityAction.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, ActivityAction> mapFromJson(dynamic json) {
    final map = <String, ActivityAction>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = ActivityAction.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of ActivityAction-objects as value to a dart map
  static Map<String, List<ActivityAction>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<ActivityAction>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = ActivityAction.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
  };
}

