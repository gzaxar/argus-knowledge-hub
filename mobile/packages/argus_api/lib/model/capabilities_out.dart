//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class CapabilitiesOut {
  /// Returns a new [CapabilitiesOut] instance.
  CapabilitiesOut({
    this.documentKinds = const [],
    required this.features,
    this.importers = const [],
    this.mapLayers = const [],
    this.packages = const [],
    this.provides = const [],
    this.ticketKinds = const [],
    required this.workspaceId,
  });

  List<String> documentKinds;

  FeaturesOut features;

  List<String> importers;

  List<MapLayerOut> mapLayers;

  List<String> packages;

  List<String> provides;

  List<String> ticketKinds;

  String workspaceId;

  @override
  bool operator ==(Object other) => identical(this, other) || other is CapabilitiesOut &&
    _deepEquality.equals(other.documentKinds, documentKinds) &&
    other.features == features &&
    _deepEquality.equals(other.importers, importers) &&
    _deepEquality.equals(other.mapLayers, mapLayers) &&
    _deepEquality.equals(other.packages, packages) &&
    _deepEquality.equals(other.provides, provides) &&
    _deepEquality.equals(other.ticketKinds, ticketKinds) &&
    other.workspaceId == workspaceId;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (documentKinds.hashCode) +
    (features.hashCode) +
    (importers.hashCode) +
    (mapLayers.hashCode) +
    (packages.hashCode) +
    (provides.hashCode) +
    (ticketKinds.hashCode) +
    (workspaceId.hashCode);

  @override
  String toString() => 'CapabilitiesOut[documentKinds=$documentKinds, features=$features, importers=$importers, mapLayers=$mapLayers, packages=$packages, provides=$provides, ticketKinds=$ticketKinds, workspaceId=$workspaceId]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
      json[r'document_kinds'] = this.documentKinds;
      json[r'features'] = this.features;
      json[r'importers'] = this.importers;
      json[r'map_layers'] = this.mapLayers;
      json[r'packages'] = this.packages;
      json[r'provides'] = this.provides;
      json[r'ticket_kinds'] = this.ticketKinds;
      json[r'workspace_id'] = this.workspaceId;
    return json;
  }

  /// Returns a new [CapabilitiesOut] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static CapabilitiesOut? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "CapabilitiesOut[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "CapabilitiesOut[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return CapabilitiesOut(
        documentKinds: json[r'document_kinds'] is Iterable
            ? (json[r'document_kinds'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        features: FeaturesOut.fromJson(json[r'features'])!,
        importers: json[r'importers'] is Iterable
            ? (json[r'importers'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        mapLayers: MapLayerOut.listFromJson(json[r'map_layers']),
        packages: json[r'packages'] is Iterable
            ? (json[r'packages'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        provides: json[r'provides'] is Iterable
            ? (json[r'provides'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        ticketKinds: json[r'ticket_kinds'] is Iterable
            ? (json[r'ticket_kinds'] as Iterable).cast<String>().toList(growable: false)
            : const [],
        workspaceId: mapValueOfType<String>(json, r'workspace_id')!,
      );
    }
    return null;
  }

  static List<CapabilitiesOut> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <CapabilitiesOut>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = CapabilitiesOut.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, CapabilitiesOut> mapFromJson(dynamic json) {
    final map = <String, CapabilitiesOut>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = CapabilitiesOut.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of CapabilitiesOut-objects as value to a dart map
  static Map<String, List<CapabilitiesOut>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<CapabilitiesOut>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = CapabilitiesOut.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'document_kinds',
    'features',
    'importers',
    'map_layers',
    'packages',
    'provides',
    'ticket_kinds',
    'workspace_id',
  };
}

