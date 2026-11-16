import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../app/providers.dart';
import '../app/queue.dart';
import '../core/problem.dart';
import '../data/command_queue.dart';
import '../domain/capture.dart';
import '../features/capture/media_source.dart';

/// Where an attachment goes: a ticket, a piece of equipment, or a document's open revision.
class AttachTarget {
  const AttachTarget.ticket(String uid) : this._(ticketUid: uid, noun: 'the ticket');
  const AttachTarget.asset(String uid) : this._(assetUid: uid, noun: 'the equipment');
  const AttachTarget.document(String uid, String revisionUid)
      : this._(documentUid: uid, revisionUid: revisionUid, noun: 'the document');
  const AttachTarget._({this.ticketUid, this.assetUid, this.documentUid, this.revisionUid, required this.noun});

  final String? ticketUid;
  final String? assetUid;
  final String? documentUid;
  final String? revisionUid;
  final String noun;

  String get uid => ticketUid ?? assetUid ?? documentUid!;

  Map<String, Object?> get payload => {
        'ticket_uid': ?ticketUid,
        'asset_uid': ?assetUid,
        'document_uid': ?documentUid,
        'revision_uid': ?revisionUid,
      };
}

/// What a file is, as a person says it.
String kindOf(String mimeType) => mimeType.startsWith('image/')
    ? 'Photo'
    : mimeType.startsWith('video/')
        ? 'Video'
        : mimeType.startsWith('audio/')
            ? 'Recorded note'
            : mimeType == 'application/geo+json'
                ? 'Location'
                : 'File';

IconData iconOf(String? mimeType) {
  final m = mimeType ?? '';
  if (m.startsWith('image/')) return Icons.image_outlined;
  if (m.startsWith('video/')) return Icons.videocam_outlined;
  if (m.startsWith('audio/')) return Icons.mic_none;
  if (m == 'application/geo+json') return Icons.place_outlined;
  if (m == 'application/pdf') return Icons.picture_as_pdf_outlined;
  return Icons.attach_file;
}

/// The person chooses what to attach and takes it: a photo, a video, a recorded note or where they are.
/// It is queued like every change (sent now when ARGUS can be reached, kept on the device until then).
/// Returns the command, or null when nothing was taken.
Future<PendingCommand?> attachTo(BuildContext context, WidgetRef ref, AttachTarget target,
    {List<String> dependsOn = const []}) async {
  final kind = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        for (final (k, icon, label) in const [
          ('photo', Icons.photo_camera_outlined, 'Photo'),
          ('gallery', Icons.photo_library_outlined, 'Photo from the phone'),
          ('video', Icons.videocam_outlined, 'Video'),
          ('audio', Icons.mic_none, 'Recorded note'),
          ('place', Icons.my_location, 'Where I am'),
        ])
          ListTile(key: Key('attach-$k'), leading: Icon(icon), title: Text(label), onTap: () => Navigator.pop(sheet, k)),
      ]),
    ),
  );
  if (kind == null || !context.mounted) return null;
  final media = ref.read(mediaSourceProvider);
  PickedPhoto? file;
  try {
    file = kind == 'audio'
        ? await showModalBottomSheet<PickedPhoto>(
            context: context,
            isDismissible: false,
            enableDrag: false,
            builder: (_) => _RecordSheet(media.recorder()),
          )
        : switch (kind) {
            'photo' => await ref.read(photoSourceProvider).take(),
            'gallery' => await ref.read(photoSourceProvider).take(fromGallery: true),
            'video' => await media.video(),
            _ => await media.place(),
          };
  } on Problem catch (p) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    return null;
  }
  if (file == null) return null;
  return queueAttachment(ref, target, file, dependsOn: dependsOn);
}

/// Sends a file to a record through the queue: now when ARGUS can be reached, later when it cannot.
Future<PendingCommand> queueAttachment(WidgetRef ref, AttachTarget target, PickedPhoto file,
    {List<String> dependsOn = const []}) async {
  final queue = ref.read(queueProvider.notifier);
  final command = await queue.enqueue(
    kind: 'attachment.upload',
    key: 'attach:${target.uid}:${const Uuid().v4()}',
    target: target.uid,
    label: '${kindOf(file.mimeType)} for ${target.noun}',
    payload: target.payload,
    attachments: [QueueController.photo(file)],
    dependsOn: dependsOn,
  );
  return queue.sendNow(command);
}

/// Records a note: the recording sheet, until the person stops (the file) or cancels (null).
Future<PickedPhoto?> recordNote(BuildContext context, WidgetRef ref) => showModalBottomSheet<PickedPhoto>(
      context: context,
      isDismissible: false,
      enableDrag: false,
      builder: (_) => _RecordSheet(ref.read(mediaSourceProvider).recorder()),
    );

class _RecordSheet extends StatefulWidget {
  const _RecordSheet(this.recorder);

  final NoteRecorder recorder;

  @override
  State<_RecordSheet> createState() => _RecordSheetState();
}

class _RecordSheetState extends State<_RecordSheet> {
  final _clock = Stopwatch();
  Timer? _tick;
  String? _error;
  bool _started = false;

  @override
  void initState() {
    super.initState();
    widget.recorder.start().then((_) {
      if (!mounted) return;
      _clock.start();
      _tick = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
      setState(() => _started = true);
    }, onError: (Object e) {
      if (mounted) setState(() => _error = e is Problem ? e.message : '$e');
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  String get _elapsed {
    final s = _clock.elapsed.inSeconds;
    return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.mic, size: 48, color: _started ? Theme.of(context).colorScheme.error : null),
            const SizedBox(height: 8),
            Text(_error ?? (_started ? 'Recording $_elapsed' : 'Starting…'),
                key: const Key('record-status'), style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 16),
            Wrap(alignment: WrapAlignment.center, spacing: 16, runSpacing: 8, children: [
              TextButton(
                key: const Key('record-cancel'),
                onPressed: () async {
                  if (_started) await widget.recorder.cancel();
                  if (context.mounted) Navigator.pop(context);
                },
                child: const Text('Cancel'),
              ),
              FilledButton.icon(
                key: const Key('record-stop'),
                onPressed: !_started
                    ? null
                    : () async {
                        final file = await widget.recorder.stop();
                        if (context.mounted) Navigator.pop(context, file);
                      },
                icon: const Icon(Icons.stop),
                label: const Text('Stop and attach'),
              ),
            ]),
          ]),
        ),
      );
}
