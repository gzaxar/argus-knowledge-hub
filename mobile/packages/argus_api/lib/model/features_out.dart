//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class FeaturesOut {
  /// Returns a new [FeaturesOut] instance.
  FeaturesOut({
    required this.beamModel,
    required this.controlSystem,
    required this.documents,
    required this.equipment,
    required this.map,
    required this.records,
    required this.tickets,
    required this.typeCatalogue,
  });

  bool beamModel;

  bool controlSystem;

  bool documents;

  bool equipment;

  bool map;

  bool records;

  bool tickets;

  bool typeCatalogue;

  @override
  bool operator ==(Object other) => identical(this, other) || other is FeaturesOut &&
    other.beamModel == beamModel &&
    other.controlSystem == controlSystem &&
    other.documents == documents &&
    other.equipment == equipment &&
    other.map == map &&
    other.records == records &&
    other.tickets == tickets &&
    other.typeCatalogue == typeCatalogue;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (beamModel.hashCode) +
    (controlSystem.hashCode) +
    (documents.hashCode) +
    (equipment.hashCode) +
    (map.hashCode) +
    (records.hashCode) +
    (tickets.hashCode) +
    (typeCatalogue.hashCode);

  @override
  String toString() => 'FeaturesOut[beamModel=$beamModel, controlSystem=$controlSystem, documents=$documents, equipment=$equipment, map=$map, records=$records, tickets=$tickets, typeCatalogue=$typeCatalogue]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'beam_model'] = this.beamModel;
      json[r'control_system'] = this.controlSystem;
      json[r'documents'] = this.documents;
      json[r'equipment'] = this.equipment;
      json[r'map'] = this.map;
      json[r'records'] = this.records;
      json[r'tickets'] = this.tickets;
      json[r'type_catalogue'] = this.typeCatalogue;
    return json;
  }

  /// Returns a new [FeaturesOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static FeaturesOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "FeaturesOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "FeaturesOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return FeaturesOut(
        beamModel: mapValueOfType<bool>(json, r'beam_model')!,
        controlSystem: mapValueOfType<bool>(json, r'control_system')!,
        documents: mapValueOfType<bool>(json, r'documents')!,
        equipment: mapValueOfType<bool>(json, r'equipment')!,
        map: mapValueOfType<bool>(json, r'map')!,
        records: mapValueOfType<bool>(json, r'records')!,
        tickets: mapValueOfType<bool>(json, r'tickets')!,
        typeCatalogue: mapValueOfType<bool>(json, r'type_catalogue')!,
      );
    }
    return null;
  }

  static List<FeaturesOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <FeaturesOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = FeaturesOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, FeaturesOut> mapFromJson(dynamic json) {
    final map = <String, FeaturesOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = FeaturesOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of FeaturesOut-objects as value to a dart map
  static Map<String, List<FeaturesOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<FeaturesOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = FeaturesOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'beam_model',
    'control_system',
    'documents',
    'equipment',
    'map',
    'records',
    'tickets',
    'type_catalogue',
  };
}

