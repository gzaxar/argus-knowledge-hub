//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class ActivityChange {
  /// Returns a new [ActivityChange] instance.
  ActivityChange({
    this.actualEnd,
    this.actualStart,
    this.allDay,
    this.assetUid,
    this.assigneeUserId,
    this.description,
    this.documentUid,
    this.dueAt,
    this.note,
    this.plannedEnd,
    this.plannedStart,
    this.rrule,
    this.ticketUid,
    this.title,
    this.visibility,
    this.workspaceIds = const [],
  });

  DateTime? actualEnd;

  DateTime? actualStart;

  bool? allDay;

  String? assetUid;

  String? assigneeUserId;

  String? description;

  String? documentUid;

  DateTime? dueAt;

  String? note;

  DateTime? plannedEnd;

  DateTime? plannedStart;

  String? rrule;

  String? ticketUid;

  String? title;

  ActivityChangeVisibilityEnum? visibility;

  List<String>? workspaceIds;

  @override
  bool operator ==(Object other) => identical(this, other) || other is ActivityChange &&
    other.actualEnd == actualEnd &&
    other.actualStart == actualStart &&
    other.allDay == allDay &&
    other.assetUid == assetUid &&
    other.assigneeUserId == assigneeUserId &&
    other.description == description &&
    other.documentUid == documentUid &&
    other.dueAt == dueAt &&
    other.note == note &&
    other.plannedEnd == plannedEnd &&
    other.plannedStart == plannedStart &&
    other.rrule == rrule &&
    other.ticketUid == ticketUid &&
    other.title == title &&
    other.visibility == visibility &&
    _deepEquality.equals(other.workspaceIds, workspaceIds);

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (actualEnd == null ? 0 : actualEnd!.hashCode) +
    (actualStart == null ? 0 : actualStart!.hashCode) +
    (allDay == null ? 0 : allDay!.hashCode) +
    (assetUid == null ? 0 : assetUid!.hashCode) +
    (assigneeUserId == null ? 0 : assigneeUserId!.hashCode) +
    (description == null ? 0 : description!.hashCode) +
    (documentUid == null ? 0 : documentUid!.hashCode) +
    (dueAt == null ? 0 : dueAt!.hashCode) +
    (note == null ? 0 : note!.hashCode) +
    (plannedEnd == null ? 0 : plannedEnd!.hashCode) +
    (plannedStart == null ? 0 : plannedStart!.hashCode) +
    (rrule == null ? 0 : rrule!.hashCode) +
    (ticketUid == null ? 0 : ticketUid!.hashCode) +
    (title == null ? 0 : title!.hashCode) +
    (visibility == null ? 0 : visibility!.hashCode) +
    (workspaceIds == null ? 0 : workspaceIds!.hashCode);

  @override
  String toString() => 'ActivityChange[actualEnd=$actualEnd, actualStart=$actualStart, allDay=$allDay, assetUid=$assetUid, assigneeUserId=$assigneeUserId, description=$description, documentUid=$documentUid, dueAt=$dueAt, note=$note, plannedEnd=$plannedEnd, plannedStart=$plannedStart, rrule=$rrule, ticketUid=$ticketUid, title=$title, visibility=$visibility, workspaceIds=$workspaceIds]';

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (this.actualEnd != null) {
      json[r'actual_end'] = this.actualEnd!.toUtc().toIso8601String();
    } else {
      json[r'actual_end'] = null;
    }
    if (this.actualStart != null) {
      json[r'actual_start'] = this.actualStart!.toUtc().toIso8601String();
    } else {
      json[r'actual_start'] = null;
    }
    if (this.allDay != null) {
      json[r'all_day'] = this.allDay;
    } else {
      json[r'all_day'] = null;
    }
    if (this.assetUid != null) {
      json[r'asset_uid'] = this.assetUid;
    } else {
      json[r'asset_uid'] = null;
    }
    if (this.assigneeUserId != null) {
      json[r'assignee_user_id'] = this.assigneeUserId;
    } else {
      json[r'assignee_user_id'] = null;
    }
    if (this.description != null) {
      json[r'description'] = this.description;
    } else {
      json[r'description'] = null;
    }
    if (this.documentUid != null) {
      json[r'document_uid'] = this.documentUid;
    } else {
      json[r'document_uid'] = null;
    }
    if (this.dueAt != null) {
      json[r'due_at'] = this.dueAt!.toUtc().toIso8601String();
    } else {
      json[r'due_at'] = null;
    }
    if (this.note != null) {
      json[r'note'] = this.note;
    } else {
      json[r'note'] = null;
    }
    if (this.plannedEnd != null) {
      json[r'planned_end'] = this.plannedEnd!.toUtc().toIso8601String();
    } else {
      json[r'planned_end'] = null;
    }
    if (this.plannedStart != null) {
      json[r'planned_start'] = this.plannedStart!.toUtc().toIso8601String();
    } else {
      json[r'planned_start'] = null;
    }
    if (this.rrule != null) {
      json[r'rrule'] = this.rrule;
    } else {
      json[r'rrule'] = null;
    }
    if (this.ticketUid != null) {
      json[r'ticket_uid'] = this.ticketUid;
    } else {
      json[r'ticket_uid'] = null;
    }
    if (this.title != null) {
      json[r'title'] = this.title;
    } else {
      json[r'title'] = null;
    }
    if (this.visibility != null) {
      json[r'visibility'] = this.visibility;
    } else {
      json[r'visibility'] = null;
    }
    if (this.workspaceIds != null) {
      json[r'workspace_ids'] = this.workspaceIds;
    } else {
      json[r'workspace_ids'] = null;
    }
    return json;
  }

  /// Returns a new [ActivityChange] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static ActivityChange? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "ActivityChange[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "ActivityChange[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return ActivityChange(
        actualEnd: mapDateTime(json, r'actual_end', r''),
        actualStart: mapDateTime(json, r'actual_start', r''),
        allDay: mapValueOfType<bool>(json, r'all_day'),
        assetUid: mapValueOfType<String>(json, r'asset_uid'),
        assigneeUserId: mapValueOfType<String>(json, r'assignee_user_id'),
        description: mapValueOfType<String>(json, r'description'),
        documentUid: mapValueOfType<String>(json, r'document_uid'),
        dueAt: mapDateTime(json, r'due_at', r''),
        note: mapValueOfType<String>(json, r'note'),
        plannedEnd: mapDateTime(json, r'planned_end', r''),
        plannedStart: mapDateTime(json, r'planned_start', r''),
        rrule: mapValueOfType<String>(json, r'rrule'),
        ticketUid: mapValueOfType<String>(json, r'ticket_uid'),
        title: mapValueOfType<String>(json, r'title'),
        visibility: ActivityChangeVisibilityEnum.fromJson(json[r'visibility']),
        workspaceIds: json[r'workspace_ids'] is Iterable
            ? (json[r'workspace_ids'] as Iterable).cast<String>().toList(growable: false)
            : const [],
      );
    }
    return null;
  }

  static List<ActivityChange> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ActivityChange>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ActivityChange.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, ActivityChange> mapFromJson(dynamic json) {
    final map = <String, ActivityChange>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = ActivityChange.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of ActivityChange-objects as value to a dart map
  static Map<String, List<ActivityChange>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<ActivityChange>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = ActivityChange.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
  };
}


class ActivityChangeVisibilityEnum {
  /// Instantiate a new enum with the provided [value].
  const ActivityChangeVisibilityEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const workspace = ActivityChangeVisibilityEnum._(r'workspace');
  static const private = ActivityChangeVisibilityEnum._(r'private');

  /// List of all possible values in this [enum][ActivityChangeVisibilityEnum].
  static const values = <ActivityChangeVisibilityEnum>[
    workspace,
    private,
  ];

  static ActivityChangeVisibilityEnum? fromJson(dynamic value) => ActivityChangeVisibilityEnumTypeTransformer().decode(value);

  static List<ActivityChangeVisibilityEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ActivityChangeVisibilityEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ActivityChangeVisibilityEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [ActivityChangeVisibilityEnum] to String,
/// and [decode] dynamic data back to [ActivityChangeVisibilityEnum].
class ActivityChangeVisibilityEnumTypeTransformer {
  factory ActivityChangeVisibilityEnumTypeTransformer() => _instance ??= const ActivityChangeVisibilityEnumTypeTransformer._();

  const ActivityChangeVisibilityEnumTypeTransformer._();

  String encode(ActivityChangeVisibilityEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a ActivityChangeVisibilityEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  ActivityChangeVisibilityEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'workspace': return ActivityChangeVisibilityEnum.workspace;
        case r'private': return ActivityChangeVisibilityEnum.private;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [ActivityChangeVisibilityEnumTypeTransformer] instance.
  static ActivityChangeVisibilityEnumTypeTransformer? _instance;
}


