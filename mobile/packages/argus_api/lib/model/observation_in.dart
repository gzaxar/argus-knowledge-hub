//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class ObservationIn {
  /// Returns a new [ObservationIn] instance.
  ObservationIn({
    this.accuracyM,
    this.crs,
    this.deviceId,
    required this.latitude,
    required this.longitude,
    this.note,
    this.observedAt,
  });

  num? accuracyM;

  String? crs;

  String? deviceId;

  num latitude;

  num longitude;

  String? note;

  String? observedAt;

  @override
  bool operator ==(Object other) => identical(this, other) || other is ObservationIn &&
    other.accuracyM == accuracyM &&
    other.crs == crs &&
    other.deviceId == deviceId &&
    other.latitude == latitude &&
    other.longitude == longitude &&
    other.note == note &&
    other.observedAt == observedAt;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (accuracyM == null ? 0 : accuracyM!.hashCode) +
    (crs == null ? 0 : crs!.hashCode) +
    (deviceId == null ? 0 : deviceId!.hashCode) +
    (latitude.hashCode) +
    (longitude.hashCode) +
    (note == null ? 0 : note!.hashCode) +
    (observedAt == null ? 0 : observedAt!.hashCode);

  @override
  String toString() => 'ObservationIn[accuracyM=$accuracyM, crs=$crs, deviceId=$deviceId, latitude=$latitude, longitude=$longitude, note=$note, observedAt=$observedAt]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.accuracyM != null) {
      json[r'accuracy_m'] = this.accuracyM;
    } else {
      json[r'accuracy_m'] = null;
    }
    if (this.crs != null) {
      json[r'crs'] = this.crs;
    } else {
      json[r'crs'] = null;
    }
    if (this.deviceId != null) {
      json[r'device_id'] = this.deviceId;
    } else {
      json[r'device_id'] = null;
    }
      json[r'latitude'] = this.latitude;
      json[r'longitude'] = this.longitude;
    if (this.note != null) {
      json[r'note'] = this.note;
    } else {
      json[r'note'] = null;
    }
    if (this.observedAt != null) {
      json[r'observed_at'] = this.observedAt;
    } else {
      json[r'observed_at'] = null;
    }
    return json;
  }

  /// Returns a new [ObservationIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static ObservationIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "ObservationIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "ObservationIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return ObservationIn(
        accuracyM: json[r'accuracy_m'] == null
            ? null
            : num.parse('${json[r'accuracy_m']}'),
        crs: mapValueOfType<String>(json, r'crs'),
        deviceId: mapValueOfType<String>(json, r'device_id'),
        latitude: num.parse('${json[r'latitude']}'),
        longitude: num.parse('${json[r'longitude']}'),
        note: mapValueOfType<String>(json, r'note'),
        observedAt: mapValueOfType<String>(json, r'observed_at'),
      );
    }
    return null;
  }

  static List<ObservationIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ObservationIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ObservationIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, ObservationIn> mapFromJson(dynamic json) {
    final map = <String, ObservationIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = ObservationIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of ObservationIn-objects as value to a dart map
  static Map<String, List<ObservationIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<ObservationIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = ObservationIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'latitude',
    'longitude',
  };
}

