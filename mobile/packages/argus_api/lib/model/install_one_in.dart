//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class InstallOneIn {
  /// Returns a new [InstallOneIn] instance.
  InstallOneIn({
    required this.catalogueId,
  });

  String catalogueId;

  @override
  bool operator ==(Object other) => identical(this, other) || other is InstallOneIn &&
    other.catalogueId == catalogueId;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (catalogueId.hashCode);

  @override
  String toString() => 'InstallOneIn[catalogueId=$catalogueId]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'catalogue_id'] = this.catalogueId;
    return json;
  }

  /// Returns a new [InstallOneIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static InstallOneIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "InstallOneIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "InstallOneIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return InstallOneIn(
        catalogueId: mapValueOfType<String>(json, r'catalogue_id')!,
      );
    }
    return null;
  }

  static List<InstallOneIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <InstallOneIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = InstallOneIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, InstallOneIn> mapFromJson(dynamic json) {
    final map = <String, InstallOneIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = InstallOneIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of InstallOneIn-objects as value to a dart map
  static Map<String, List<InstallOneIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<InstallOneIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = InstallOneIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'catalogue_id',
  };
}

