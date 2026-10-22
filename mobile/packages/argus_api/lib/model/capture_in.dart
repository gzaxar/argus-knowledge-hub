//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class CaptureIn {
  /// Returns a new [CaptureIn] instance.
  CaptureIn({
    this.assetUid,
    required this.capturedAt,
    this.clarification,
    this.timezone = 'UTC',
    required this.transcript,
  });

  String? assetUid;

  DateTime capturedAt;

  Object? clarification;

  String timezone;

  String transcript;

  @override
  bool operator ==(Object other) => identical(this, other) || other is CaptureIn &&
    other.assetUid == assetUid &&
    other.capturedAt == capturedAt &&
    other.clarification == clarification &&
    other.timezone == timezone &&
    other.transcript == transcript;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (assetUid == null ? 0 : assetUid!.hashCode) +
    (capturedAt.hashCode) +
    (clarification == null ? 0 : clarification!.hashCode) +
    (timezone.hashCode) +
    (transcript.hashCode);

  @override
  String toString() => 'CaptureIn[assetUid=$assetUid, capturedAt=$capturedAt, clarification=$clarification, timezone=$timezone, transcript=$transcript]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.assetUid != null) {
      json[r'asset_uid'] = this.assetUid;
    } else {
      json[r'asset_uid'] = null;
    }
      json[r'captured_at'] = this.capturedAt.toUtc().toIso8601String();
    if (this.clarification != null) {
      json[r'clarification'] = this.clarification;
    } else {
      json[r'clarification'] = null;
    }
      json[r'timezone'] = this.timezone;
      json[r'transcript'] = this.transcript;
    return json;
  }

  /// Returns a new [CaptureIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static CaptureIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "CaptureIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "CaptureIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return CaptureIn(
        assetUid: mapValueOfType<String>(json, r'asset_uid'),
        capturedAt: mapDateTime(json, r'captured_at', r'')!,
        clarification: mapValueOfType<Object>(json, r'clarification'),
        timezone: mapValueOfType<String>(json, r'timezone') ?? 'UTC',
        transcript: mapValueOfType<String>(json, r'transcript')!,
      );
    }
    return null;
  }

  static List<CaptureIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <CaptureIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = CaptureIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, CaptureIn> mapFromJson(dynamic json) {
    final map = <String, CaptureIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = CaptureIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of CaptureIn-objects as value to a dart map
  static Map<String, List<CaptureIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<CaptureIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = CaptureIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'captured_at',
    'transcript',
  };
}

