import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:uuid/uuid.dart';

import '../core/blob_store.dart';
import '../core/local_store.dart';
import '../core/problem.dart';
import '../domain/capture.dart';
import 'api_service.dart';
import 'activity_repository.dart';
import 'capture_repositories.dart';
import 'replacement_repositories.dart';

/// Where a pending command is (flutter-app-design §5.2).
enum CommandStatus { queued, sending, accepted, rejected, conflict, expired }

/// A photo or file a command carries, kept on the device until the server has it.
class AttachmentRef {
  const AttachmentRef({required this.localId, required this.name, required this.mimeType, required this.size});

  final String localId;
  final String name;
  final String mimeType;
  final int size;

  Map<String, Object?> toJson() => {'local_id': localId, 'name': name, 'mime_type': mimeType, 'size': size};

  static AttachmentRef fromJson(Map<String, dynamic> j) => AttachmentRef(
      localId: j['local_id'] as String, name: j['name'] as String, mimeType: j['mime_type'] as String,
      size: (j['size'] as num).toInt());
}

/// A finished request waiting for the server. It is not a fact: only its author sees it, labelled
/// pending, until the server accepts it (I-MOB-3).
class PendingCommand {
  PendingCommand({
    required this.id,
    required this.key,
    required this.kind,
    required this.workspaceId,
    required this.label,
    required this.payload,
    this.target,
    this.seenVersion,
    this.attachments = const [],
    this.dependsOn = const [],
    required this.createdAt,
    this.serverOffset = Duration.zero,
    this.status = CommandStatus.queued,
    this.attempts = 0,
    this.nextAttemptAt,
    this.lastError,
    this.lastCode,
    this.reviewItem,
    this.note,
  });

  final String id;
  final String key; // the idempotency key, the same for every retry (§3.2)
  final String kind; // ticket.create, ticket.comment, ticket.transition, attachment.upload, replacement.submit, intake.outcome, activity.create, activity.action
  final String workspaceId;
  final String label; // what the person did, in their words: "Report: pump tripped"
  final Map<String, Object?> payload;
  final String? target; // the record uid, or the client uid of a record created offline
  final String? seenVersion;
  final List<AttachmentRef> attachments;
  final List<String> dependsOn;
  final DateTime createdAt; // device time
  final Duration serverOffset; // server time minus device time, when it was captured
  CommandStatus status;
  int attempts;
  DateTime? nextAttemptAt;
  String? lastError;
  String? lastCode;
  String? reviewItem;
  String? note; // e.g. "proposed: waits for an approver"

  DateTime get capturedAt => createdAt.add(serverOffset);

  bool get open => status == CommandStatus.queued || status == CommandStatus.sending;
  bool get needsPerson =>
      status == CommandStatus.rejected || status == CommandStatus.conflict || status == CommandStatus.expired;

  Map<String, Object?> toJson() => {
        'id': id,
        'key': key,
        'kind': kind,
        'workspace_id': workspaceId,
        'label': label,
        'payload': payload,
        'target': target,
        'seen_version': seenVersion,
        'attachments': [for (final a in attachments) a.toJson()],
        'depends_on': dependsOn,
        'created_at': createdAt.toUtc().toIso8601String(),
        'server_offset_ms': serverOffset.inMilliseconds,
        'status': status.name,
        'attempts': attempts,
        'next_attempt_at': nextAttemptAt?.toUtc().toIso8601String(),
        'last_error': lastError,
        'last_code': lastCode,
        'review_item': reviewItem,
        'note': note,
      };

  static PendingCommand fromJson(Map<String, dynamic> j) => PendingCommand(
        id: j['id'] as String,
        key: j['key'] as String,
        kind: j['kind'] as String,
        workspaceId: j['workspace_id'] as String,
        label: (j['label'] ?? '') as String,
        payload: Map<String, Object?>.from(j['payload'] as Map),
        target: j['target'] as String?,
        seenVersion: j['seen_version'] as String?,
        attachments: [for (final a in (j['attachments'] as List? ?? const [])) AttachmentRef.fromJson(Map.from(a as Map))],
        dependsOn: [for (final d in (j['depends_on'] as List? ?? const [])) d as String],
        createdAt: DateTime.parse(j['created_at'] as String).toLocal(),
        serverOffset: Duration(milliseconds: (j['server_offset_ms'] as num? ?? 0).toInt()),
        status: CommandStatus.values.byName(j['status'] as String),
        attempts: (j['attempts'] as num? ?? 0).toInt(),
        nextAttemptAt: j['next_attempt_at'] == null ? null : DateTime.parse(j['next_attempt_at'] as String).toLocal(),
        lastError: j['last_error'] as String?,
        lastCode: j['last_code'] as String?,
        reviewItem: j['review_item'] as String?,
        note: j['note'] as String?,
      );
}

/// The queue on disk: one entry per command in the encrypted store, and the files they carry in the
/// encrypted blob store (an attachment saved before there was one is still read from the store).
class CommandStore {
  CommandStore(this._store, [BlobStore? files]) : _files = files;
  final LocalStore _store;
  final BlobStore? _files;

  static const commands = 'argus.queue.';
  static const blobs = 'argus.blob.';

  Future<List<PendingCommand>> load() async {
    final out = <PendingCommand>[];
    for (final v in (await _store.readPrefix(commands)).values) {
      try {
        out.add(PendingCommand.fromJson(jsonDecode(v) as Map<String, dynamic>));
      } catch (_) {
        // an unreadable entry is not silently applied
      }
    }
    out.sort((a, b) => a.createdAt.compareTo(b.createdAt));
    return out;
  }

  Future<void> save(PendingCommand c) => _store.write('$commands${c.id}', jsonEncode(c.toJson()));

  Future<void> saveBlob(String localId, Uint8List bytes) =>
      _files != null ? _files.put(localId, bytes) : _store.write('$blobs$localId', base64Encode(bytes));

  Future<Uint8List?> blob(String localId) async {
    final file = await _files?.get(localId);
    if (file != null) return file;
    final raw = await _store.read('$blobs$localId');
    return raw == null ? null : base64Decode(raw);
  }

  /// A command and its attachments leave the device: after `accepted`, or when the person discards it.
  Future<void> remove(PendingCommand c) async {
    for (final a in c.attachments) {
      await _files?.delete(a.localId);
      await _store.delete('$blobs${a.localId}');
    }
    await _store.delete('$commands${c.id}');
  }
}

/// Sends one command through the same API as a live request, stamped with its key and capture time.
class CommandExecutor {
  CommandExecutor(this._api, this._store);
  final ApiService _api;
  final CommandStore _store;

  /// Returns a note for the person, or throws the server's problem.
  Future<String?> run(PendingCommand c) async {
    final api = _api.capturing(c.capturedAt);
    final p = c.payload;
    switch (c.kind) {
      case 'ticket.create':
        await TicketCommands(api).create(
          uid: p['uid'] as String,
          title: p['title'] as String,
          description: (p['description'] ?? '') as String,
          subjectUid: p['asset_uid'] as String?,
          kindUid: p['schema_uid'] as String?,
          attributes: Map<String, Object?>.from((p['attributes'] ?? const {}) as Map),
        );
        return null;
      case 'ticket.comment':
        await TicketCommands(api).comment(p['ticket_uid'] as String, p['comment_uid'] as String, p['body'] as String);
        return null;
      case 'ticket.transition':
        final r = await TicketCommands(api).transition(p['ticket_uid'] as String, p['to'] as String,
            version: (p['version'] as num).toInt(), key: c.key,
            comment: p['comment'] as String?, resolution: p['resolution'] as String?);
        return r.proposed ? 'Proposed: a person confirms it on the web.' : null;
      case 'attachment.upload':
        final a = c.attachments.single;
        final bytes = await _store.blob(a.localId);
        if (bytes == null) throw Problem(ProblemCode.invalid, 'The file is no longer on this device.');
        await UploadRepository(api).uploadAndAttach(PickedPhoto(bytes: bytes, name: a.name, mimeType: a.mimeType),
            ticketUid: p['ticket_uid'] as String?, assetUid: p['asset_uid'] as String?,
            documentUid: p['document_uid'] as String?, revisionUid: p['revision_uid'] as String?, key: c.key);
        return null;
      case 'replacement.submit':
        final d = ReplacementDraft(
            commandUid: p['command_uid'] as String,
            positionUid: p['position_uid'] as String,
            seenInstallationUid: p['seen_installation_uid'] as String?)
          ..outgoingUid = p['outgoing_uid'] as String?
          ..incomingUid = p['incoming_uid'] as String
          ..at = DateTime.parse(p['at'] as String)
          ..precision = (p['precision'] ?? 'instant') as String
          ..reason = (p['reason'] ?? 'Replacement') as String
          ..condition = p['condition'] as String?
          ..workReference = p['work_reference'] as String?
          ..evidence = p['evidence'] == null ? null : Map<String, Object?>.from(p['evidence'] as Map);
        final r = await ReplacementRepository(api).submit(d);
        return r.applied ? 'Replaced.' : 'Waiting for review: ${r.reasons.join('; ')}.';
      case 'activity.create':
        // The uid was chosen on the phone and the key is the same at every retry: one activity, however often.
        await ActivityRepository(api).create(Map<String, Object?>.from(p), key: c.key);
        return null;
      case 'activity.action':
        await ActivityRepository(api).act(p['id'] as String, p['action'] as String,
            body: Map<String, Object?>.from((p['body'] ?? const {}) as Map), key: c.key);
        return null;
      case 'intake.outcome':
        await IntakeRepository(api).recordOutcome(p['run_id'] as String, p['record_uid'] as String,
            Map<String, Object?>.from((p['final'] ?? const {}) as Map));
        return null;
    }
    throw Problem(ProblemCode.invalid, 'This version cannot send "${c.kind}".');
  }
}

/// How a problem ends a command (flutter-app-design §5.3 step 6): kept for the person, or retried.
enum Outcome { retryLater, stopSync, rejected, conflict, expired }

Outcome outcomeOf(Problem p) => switch (p.code) {
      ProblemCode.offline => Outcome.stopSync,
      ProblemCode.unauthenticated || ProblemCode.revoked || ProblemCode.clientTooOld => Outcome.stopSync,
      ProblemCode.inProgress || ProblemCode.unknown => Outcome.retryLater,
      ProblemCode.stale || ProblemCode.conflict => p.reviewItem != null ? Outcome.conflict : Outcome.rejected,
      ProblemCode.expired => Outcome.expired,
      _ => Outcome.rejected,
    };

/// Exponential backoff with jitter, capped (§5.3 step 7).
Duration backoff(int attempts, [Random? random]) {
  final base = Duration(seconds: min(900, 5 * pow(2, attempts).toInt()));
  final jitter = (random ?? Random()).nextDouble() * 0.3 + 0.85;
  return base * jitter;
}

const maxAttempts = 8;

String newCommandId() => const Uuid().v4();
