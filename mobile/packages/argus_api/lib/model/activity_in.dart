//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//
// @dart=2.18

// ignore_for_file: unused_element, unused_import
// ignore_for_file: always_put_required_named_parameters_first
// ignore_for_file: constant_identifier_names
// ignore_for_file: lines_longer_than_80_chars

part of openapi.api;

class ActivityIn {
  /// Returns a new [ActivityIn] instance.
  ActivityIn({
    this.actualEnd,
    this.actualStart,
    this.allDay = false,
    this.assetUid,
    this.assigneeUserId,
    this.description,
    this.documentUid,
    this.dueAt,
    this.note,
    this.plannedEnd,
    this.plannedStart,
    this.provenance,
    this.rrule,
    this.status,
    this.ticketUid,
    this.timezone = 'UTC',
    required this.title,
    this.uid,
    this.visibility,
  });

  DateTime? actualEnd;

  DateTime? actualStart;

  bool allDay;

  String? assetUid;

  String? assigneeUserId;

  String? description;

  String? documentUid;

  DateTime? dueAt;

  String? note;

  DateTime? plannedEnd;

  DateTime? plannedStart;

  Object? provenance;

  String? rrule;

  ActivityInStatusEnum? status;

  String? ticketUid;

  String timezone;

  String title;

  String? uid;

  ActivityInVisibilityEnum? visibility;

  @override
  bool operator ==(Object other) => identical(this, other) || other is ActivityIn &&
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
    other.provenance == provenance &&
    other.rrule == rrule &&
    other.status == status &&
    other.ticketUid == ticketUid &&
    other.timezone == timezone &&
    other.title == title &&
    other.uid == uid &&
    other.visibility == visibility;

  @override
  int get hashCode =>
    // ignore: unnecessary_parenthesis
    (actualEnd == null ? 0 : actualEnd!.hashCode) +
    (actualStart == null ? 0 : actualStart!.hashCode) +
    (allDay.hashCode) +
    (assetUid == null ? 0 : assetUid!.hashCode) +
    (assigneeUserId == null ? 0 : assigneeUserId!.hashCode) +
    (description == null ? 0 : description!.hashCode) +
    (documentUid == null ? 0 : documentUid!.hashCode) +
    (dueAt == null ? 0 : dueAt!.hashCode) +
    (note == null ? 0 : note!.hashCode) +
    (plannedEnd == null ? 0 : plannedEnd!.hashCode) +
    (plannedStart == null ? 0 : plannedStart!.hashCode) +
    (provenance == null ? 0 : provenance!.hashCode) +
    (rrule == null ? 0 : rrule!.hashCode) +
    (status == null ? 0 : status!.hashCode) +
    (ticketUid == null ? 0 : ticketUid!.hashCode) +
    (timezone.hashCode) +
    (title.hashCode) +
    (uid == null ? 0 : uid!.hashCode) +
    (visibility == null ? 0 : visibility!.hashCode);

  @override
  String toString() => 'ActivityIn[actualEnd=$actualEnd, actualStart=$actualStart, allDay=$allDay, assetUid=$assetUid, assigneeUserId=$assigneeUserId, description=$description, documentUid=$documentUid, dueAt=$dueAt, note=$note, plannedEnd=$plannedEnd, plannedStart=$plannedStart, provenance=$provenance, rrule=$rrule, status=$status, ticketUid=$ticketUid, timezone=$timezone, title=$title, uid=$uid, visibility=$visibility]';

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
      json[r'all_day'] = this.allDay;
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
    if (this.provenance != null) {
      json[r'provenance'] = this.provenance;
    } else {
      json[r'provenance'] = null;
    }
    if (this.rrule != null) {
      json[r'rrule'] = this.rrule;
    } else {
      json[r'rrule'] = null;
    }
    if (this.status != null) {
      json[r'status'] = this.status;
    } else {
      json[r'status'] = null;
    }
    if (this.ticketUid != null) {
      json[r'ticket_uid'] = this.ticketUid;
    } else {
      json[r'ticket_uid'] = null;
    }
      json[r'timezone'] = this.timezone;
      json[r'title'] = this.title;
    if (this.uid != null) {
      json[r'uid'] = this.uid;
    } else {
      json[r'uid'] = null;
    }
    if (this.visibility != null) {
      json[r'visibility'] = this.visibility;
    } else {
      json[r'visibility'] = null;
    }
    return json;
  }

  /// Returns a new [ActivityIn] instance and imports its values from
  /// [value] if it's a [Map], null otherwise.
  // ignore: prefer_constructors_over_static_methods
  static ActivityIn? fromJson(dynamic value) {
    if (value is Map) {
      final json = value.cast<String, dynamic>();

      // Ensure that the map contains the required keys.
      // Note 1: the values aren't checked for validity beyond being non-null.
      // Note 2: this code is stripped in release mode!
      assert(() {
        requiredKeys.forEach((key) {
          assert(json.containsKey(key), 'Required key "ActivityIn[$key]" is missing from JSON.');
          assert(json[key] != null, 'Required key "ActivityIn[$key]" has a null value in JSON.');
        });
        return true;
      }());

      return ActivityIn(
        actualEnd: mapDateTime(json, r'actual_end', r''),
        actualStart: mapDateTime(json, r'actual_start', r''),
        allDay: mapValueOfType<bool>(json, r'all_day') ?? false,
        assetUid: mapValueOfType<String>(json, r'asset_uid'),
        assigneeUserId: mapValueOfType<String>(json, r'assignee_user_id'),
        description: mapValueOfType<String>(json, r'description'),
        documentUid: mapValueOfType<String>(json, r'document_uid'),
        dueAt: mapDateTime(json, r'due_at', r''),
        note: mapValueOfType<String>(json, r'note'),
        plannedEnd: mapDateTime(json, r'planned_end', r''),
        plannedStart: mapDateTime(json, r'planned_start', r''),
        provenance: mapValueOfType<Object>(json, r'provenance'),
        rrule: mapValueOfType<String>(json, r'rrule'),
        status: ActivityInStatusEnum.fromJson(json[r'status']),
        ticketUid: mapValueOfType<String>(json, r'ticket_uid'),
        timezone: mapValueOfType<String>(json, r'timezone') ?? 'UTC',
        title: mapValueOfType<String>(json, r'title')!,
        uid: mapValueOfType<String>(json, r'uid'),
        visibility: ActivityInVisibilityEnum.fromJson(json[r'visibility']),
      );
    }
    return null;
  }

  static List<ActivityIn> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ActivityIn>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ActivityIn.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }

  static Map<String, ActivityIn> mapFromJson(dynamic json) {
    final map = <String, ActivityIn>{};
    if (json is Map && json.isNotEmpty) {
      json = json.cast<String, dynamic>(); // ignore: parameter_assignments
      for (final entry in json.entries) {
        final value = ActivityIn.fromJson(entry.value);
        if (value != null) {
          map[entry.key] = value;
        }
      }
    }
    return map;
  }

  // maps a json object with a list of ActivityIn-objects as value to a dart map
  static Map<String, List<ActivityIn>> mapListFromJson(dynamic json, {bool growable = false,}) {
    final map = <String, List<ActivityIn>>{};
    if (json is Map && json.isNotEmpty) {
      // ignore: parameter_assignments
      json = json.cast<String, dynamic>();
      for (final entry in json.entries) {
        map[entry.key] = ActivityIn.listFromJson(entry.value, growable: growable,);
      }
    }
    return map;
  }

  /// The list of required keys that must be present in a JSON.
  static const requiredKeys = <String>{
    'title',
  };
}


class ActivityInStatusEnum {
  /// Instantiate a new enum with the provided [value].
  const ActivityInStatusEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const planned = ActivityInStatusEnum._(r'planned');
  static const inProgress = ActivityInStatusEnum._(r'in_progress');
  static const completed = ActivityInStatusEnum._(r'completed');
  static const cancelled = ActivityInStatusEnum._(r'cancelled');

  /// List of all possible values in this [enum][ActivityInStatusEnum].
  static const values = <ActivityInStatusEnum>[
    planned,
    inProgress,
    completed,
    cancelled,
  ];

  static ActivityInStatusEnum? fromJson(dynamic value) => ActivityInStatusEnumTypeTransformer().decode(value);

  static List<ActivityInStatusEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ActivityInStatusEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ActivityInStatusEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [ActivityInStatusEnum] to String,
/// and [decode] dynamic data back to [ActivityInStatusEnum].
class ActivityInStatusEnumTypeTransformer {
  factory ActivityInStatusEnumTypeTransformer() => _instance ??= const ActivityInStatusEnumTypeTransformer._();

  const ActivityInStatusEnumTypeTransformer._();

  String encode(ActivityInStatusEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a ActivityInStatusEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  ActivityInStatusEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'planned': return ActivityInStatusEnum.planned;
        case r'in_progress': return ActivityInStatusEnum.inProgress;
        case r'completed': return ActivityInStatusEnum.completed;
        case r'cancelled': return ActivityInStatusEnum.cancelled;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [ActivityInStatusEnumTypeTransformer] instance.
  static ActivityInStatusEnumTypeTransformer? _instance;
}



class ActivityInVisibilityEnum {
  /// Instantiate a new enum with the provided [value].
  const ActivityInVisibilityEnum._(this.value);

  /// The underlying value of this enum member.
  final String value;

  @override
  String toString() => value;

  String toJson() => value;

  static const workspace = ActivityInVisibilityEnum._(r'workspace');
  static const private = ActivityInVisibilityEnum._(r'private');

  /// List of all possible values in this [enum][ActivityInVisibilityEnum].
  static const values = <ActivityInVisibilityEnum>[
    workspace,
    private,
  ];

  static ActivityInVisibilityEnum? fromJson(dynamic value) => ActivityInVisibilityEnumTypeTransformer().decode(value);

  static List<ActivityInVisibilityEnum> listFromJson(dynamic json, {bool growable = false,}) {
    final result = <ActivityInVisibilityEnum>[];
    if (json is List && json.isNotEmpty) {
      for (final row in json) {
        final value = ActivityInVisibilityEnum.fromJson(row);
        if (value != null) {
          result.add(value);
        }
      }
    }
    return result.toList(growable: growable);
  }
}

/// Transformation class that can [encode] an instance of [ActivityInVisibilityEnum] to String,
/// and [decode] dynamic data back to [ActivityInVisibilityEnum].
class ActivityInVisibilityEnumTypeTransformer {
  factory ActivityInVisibilityEnumTypeTransformer() => _instance ??= const ActivityInVisibilityEnumTypeTransformer._();

  const ActivityInVisibilityEnumTypeTransformer._();

  String encode(ActivityInVisibilityEnum data) => data.value;

  /// Decodes a [dynamic value][data] to a ActivityInVisibilityEnum.
  ///
  /// If [allowNull] is true and the [dynamic value][data] cannot be decoded successfully,
  /// then null is returned. However, if [allowNull] is false and the [dynamic value][data]
  /// cannot be decoded successfully, then an [UnimplementedError] is thrown.
  ///
  /// The [allowNull] is very handy when an API changes and a new enum value is added or removed,
  /// and users are still using an old app with the old code.
  ActivityInVisibilityEnum? decode(dynamic data, {bool allowNull = true}) {
    if (data != null) {
      switch (data) {
        case r'workspace': return ActivityInVisibilityEnum.workspace;
        case r'private': return ActivityInVisibilityEnum.private;
        default:
          if (!allowNull) {
            throw ArgumentError('Unknown enum value to decode: $data');
          }
      }
    }
    return null;
  }

  /// Singleton [ActivityInVisibilityEnumTypeTransformer] instance.
  static ActivityInVisibilityEnumTypeTransformer? _instance;
}


