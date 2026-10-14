//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class MapLayerOut {
  /// Returns a new [MapLayerOut] instance.
  MapLayerOut({
    this.description,
    required this.id,
    required this.name,
  });

  String? description;

  String id;

  String name;

  @override
  bool operator ==(Object other) => identical(this, other) || other is MapLayerOut &&
    other.description == description &&
    other.id == id &&
    other.name == name;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (description == null ? 0 : description!.hashCode) +
    (id.hashCode) +
    (name.hashCode);

  @override
  String toString() => 'MapLayerOut[description=$description, id=$id, name=$name]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.description != null) {
      json[r'description'] = this.description;
    } else {
      json[r'description'] = null;
    }
      json[r'id'] = this.id;
      json[r'name'] = this.name;
    return json;
  }

  /// Returns a new [MapLayerOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static MapLayerOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "MapLayerOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "MapLayerOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return MapLayerOut(
        description: mapValueOfType<String>(json, r'description'),
        id: mapValueOfType<String>(json, r'id')!,
        name: mapValueOfType<String>(json, r'name')!,
      );
    }
    return null;
  }

  static List<MapLayerOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <MapLayerOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = MapLayerOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, MapLayerOut> mapFromJson(dynamic json) {
    final map = <String, MapLayerOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = MapLayerOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of MapLayerOut-objects as value to a dart map
  static Map<String, List<MapLayerOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<MapLayerOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = MapLayerOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'id',
    'name',
  };
}

