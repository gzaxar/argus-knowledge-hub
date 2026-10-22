import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../data/ask_repository.dart';
import '../../domain/capture.dart';
import '../../widgets/attach_menu.dart';
import '../../widgets/common.dart';
import '../../widgets/rich_content.dart';
import '../shell/app_shell.dart';
import 'voice.dart';

/// Ask: a question answered from the workspace's records, typed or spoken, as a conversation
/// (the web's Ask page). The lookups behind each answer are shown, so the person sees which
/// records it rests on; an answer that was cut short says so.
///
/// Hands-free: answers are read aloud and, after one is read, the app listens for the next
/// question, until the person says nothing or turns it off.
class AskScreen extends ConsumerStatefulWidget {
  const AskScreen({super.key});

  @override
  ConsumerState<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends ConsumerState<AskScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _turns = <AskTurn>[];
  String? _conversationId;
  StreamSubscription<AskEvent>? _answering;
  bool _listening = false;
  bool _handsFree = false;
  int? _speaking; // the turn being read aloud
  String? _preparing; // a recording being transcribed, a photo being read

  late final Voice _voice;

  @override
  void initState() {
    super.initState();
    _voice = ref.read(voiceProvider);
  }

  @override
  void dispose() {
    _answering?.cancel();
    _voice.stopListening();
    _voice.quiet();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  bool get _busy => _answering != null;

  void _toBottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
        }
      });

  void _send([String? text]) {
    final question = (text ?? _input.text).trim();
    if (question.isEmpty || _busy) return;
    _input.clear();
    final turn = AskTurn(question: question);
    setState(() => _turns.add(turn));
    _toBottom();
    _answering = ref.read(askRepositoryProvider).ask(question, conversationId: _conversationId).listen(
      (e) => setState(() {
        switch (e) {
          case AskConversationStarted(:final id):
            _conversationId = id;
          case AskText(:final text):
            turn.answer += text;
          case AskTextReset():
            turn.answer = '';
          case AskLookup(:final index):
            final at = turn.lookups.indexWhere((l) => l.index == index);
            at < 0 ? turn.lookups.add(e) : turn.lookups[at] = e;
          case AskDone(:final answer, :final stopped, :final error):
            turn
              ..answer = answer.isEmpty ? turn.answer : answer
              ..stopped = stopped
              ..error = error;
        }
        _toBottom();
      }),
      onError: (Object e) => setState(() {
        _answering = null; // cancelOnError: onDone does not follow
        turn
          ..stopped = 'failed'
          ..error = e is Problem ? e.message : e.toString();
      }),
      onDone: () {
        if (!mounted) return;
        setState(() {
          _answering = null;
          turn.stopped ??= 'failed';
        });
        if (_handsFree && turn.stopped != 'failed' && turn.answer.isNotEmpty) _readThenListen(turn);
      },
      cancelOnError: true,
    );
  }

  void _stop() {
    _answering?.cancel();
    setState(() {
      _answering = null;
      if (_turns.isNotEmpty) _turns.last.stopped ??= 'cancelled';
    });
  }

  Future<void> _readAloud(AskTurn turn) async {
    final i = _turns.indexOf(turn);
    if (_speaking == i) {
      await _voice.quiet();
      if (mounted) setState(() => _speaking = null);
      return;
    }
    setState(() => _speaking = i);
    await _voice.speak(spoken(turn.answer));
    if (mounted && _speaking == i) setState(() => _speaking = null);
  }

  Future<void> _readThenListen(AskTurn turn) async {
    await _readAloud(turn);
    if (mounted && _handsFree && !_busy && !_listening) await _listen();
  }

  Future<void> _listen() async {
    if (_listening) {
      await _voice.stopListening();
      return;
    }
    if (!await _voice.canListen()) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Speech recognition is not available. Allow the microphone for ARGUS Field in the '
                "phone's settings.")));
      }
      return;
    }
    await _voice.quiet();
    if (!mounted) return;
    setState(() {
      _listening = true;
      _speaking = null;
    });
    await _voice.listen((words, last) {
      if (!mounted) return;
      setState(() {
        _input.text = words;
        if (last) _listening = false;
      });
      if (last) {
        if (words.trim().isNotEmpty) {
          _send(words);
        } else if (_handsFree) {
          setState(() => _handsFree = false); // nothing said: the conversation is over
        }
      }
    });
  }

  void _toggleHandsFree() {
    setState(() => _handsFree = !_handsFree);
    if (!_handsFree) {
      _voice.quiet();
      _voice.stopListening();
      setState(() => _speaking = null);
    } else if (!_busy && !_listening) {
      _listen();
    }
  }

  void _newConversation() {
    _stop();
    _voice.quiet();
    setState(() {
      _turns.clear();
      _conversationId = null;
      _speaking = null;
    });
  }

  Future<void> _history() async {
    final picked = await showModalBottomSheet<AskConversationSummary>(
      context: context,
      showDragHandle: true,
      builder: (_) => const _History(),
    );
    if (picked == null || !mounted) return;
    try {
      final turns = await ref.read(askRepositoryProvider).conversation(picked.id);
      _stop();
      setState(() {
        _turns
          ..clear()
          ..addAll(turns);
        _conversationId = picked.id;
      });
      _toBottom();
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final available = ref.watch(askAvailabilityProvider);
    return Scaffold(
      appBar: AppBar(
        leading: const ShellMenuButton(),
        title: const Text('Ask ARGUS'),
        actions: [
          IconButton(
            key: const Key('ask-handsfree'),
            tooltip: _handsFree ? 'Hands-free on: answers are read and the app listens' : 'Hands-free',
            isSelected: _handsFree,
            icon: const Icon(Icons.headset_off_outlined),
            selectedIcon: const Icon(Icons.headset_mic),
            onPressed: _toggleHandsFree,
          ),
          IconButton(
              key: const Key('ask-history'),
              tooltip: 'Earlier conversations',
              icon: const Icon(Icons.history),
              onPressed: _history),
          IconButton(
              key: const Key('ask-new'),
              tooltip: 'New conversation',
              icon: const Icon(Icons.add_comment_outlined),
              onPressed: _turns.isEmpty ? null : _newConversation),
        ],
      ),
      body: available.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(askAvailabilityProvider)),
        data: (a) => !a.usable
            ? Center(
                child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.smart_toy_outlined, size: 48, color: Theme.of(context).colorScheme.outline),
                  const SizedBox(height: 12),
                  Text('The assistant is not available', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  Text(a.reason ?? '', key: const Key('ask-unavailable'), textAlign: TextAlign.center),
                ]),
              ))
            : Column(children: [
                Expanded(
                  child: _turns.isEmpty
                      ? const _Hint()
                      : ListView.builder(
                          controller: _scroll,
                          padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
                          itemCount: _turns.length,
                          itemBuilder: (_, i) => _TurnView(
                            turn: _turns[i],
                            speaking: _speaking == i,
                            onReadAloud: () => _readAloud(_turns[i]),
                            onRate: _conversationId == null ? null : (rating) => _rate(i, rating),
                          ),
                        ),
                ),
                _composer(context),
              ]),
      ),
    );
  }

  /// Besides asking: registering equipment, and writing a document by voice or from a photo.
  Future<void> _actions() async {
    final action = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final (k, icon, title, sub) in const [
            ('register-photo', Icons.add_a_photo_outlined, 'Register equipment from a photo',
                'Its nameplate is read and the form filled in'),
            ('scan', Icons.qr_code_scanner, 'Find or register by its label', 'QR code, barcode, serial or printed text'),
            ('doc-voice', Icons.mic_none, 'Write a document by voice', 'Dictate it: what you say is transcribed'),
            ('doc-photo', Icons.document_scanner_outlined, 'Write a document from a photo',
                'A page, a sign, a whiteboard: its text is read'),
          ])
            ListTile(
              key: Key('ask-action-$k'),
              leading: Icon(icon),
              title: Text(title),
              subtitle: Text(sub),
              onTap: () => Navigator.pop(sheet, k),
            ),
        ]),
      ),
    );
    if (action == null || !mounted) return;
    switch (action) {
      case 'register-photo':
        context.push('/register?photo=1');
      case 'scan':
        context.push('/scan');
      case 'doc-voice':
        final recording = await recordNote(context, ref);
        if (recording == null || !mounted) return;
        await _startDocument('Transcribing your recording…', 'recording', recording,
            () => ref.read(askRepositoryProvider).transcribe(recording));
      case 'doc-photo':
        final reader = ref.read(textReaderProvider);
        if (!reader.available) {
          _say('Reading text from a photo needs the app on a phone.');
          return;
        }
        final photo = await ref.read(photoSourceProvider).take();
        if (photo == null || !mounted) return;
        await _startDocument('Reading the text…', 'photo', photo, () => reader.read(photo));
    }
  }

  /// The new-document editor, started from what was said or read — or a word that nothing could be.
  Future<void> _startDocument(String working, String from, PickedPhoto original, Future<String> Function() read) async {
    setState(() => _preparing = working);
    try {
      final text = (await read()).trim();
      if (!mounted) return;
      if (text.isEmpty) {
        _say(from == 'recording' ? 'Nothing could be heard in the recording.' : 'No text could be read in the photo.');
        return;
      }
      context.push('/documents/new',
          extra: DocumentSeed(title: firstLineOf(text), body: text, original: original, from: from));
    } on Problem catch (p) {
      _say(p.message);
    } finally {
      if (mounted) setState(() => _preparing = null);
    }
  }

  void _say(String message) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));

  /// Rate an answer: up at once; down after asking, optionally, what was wrong.
  Future<void> _rate(int index, String rating) async {
    final turn = _turns[index];
    final conversationId = _conversationId;
    if (conversationId == null || turn.rating != null) return;
    String? comment;
    if (rating == 'down') {
      comment = await showDialog<String>(context: context, builder: (_) => const _FeedbackDialog());
      if (comment == null || !mounted) return;
    }
    try {
      final reported = await ref.read(askRepositoryProvider).rate(conversationId, index, rating, comment: comment);
      if (!mounted) return;
      setState(() => turn.rating = rating);
      _say(reported ? 'Thanks — sent, without your name, to the people who improve Ask ARGUS.' : 'Thanks!');
    } on Problem catch (p) {
      if (!mounted) return;
      if (p.message.contains('rated already')) setState(() => turn.rating = rating);
      _say(p.message);
    }
  }

  Widget _composer(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_preparing != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(children: [
                const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                const SizedBox(width: 8),
                Text(_preparing!, key: const Key('ask-preparing')),
              ]),
            ),
          Row(children: [
          IconButton(
            key: const Key('ask-actions'),
            tooltip: 'Register equipment, write a document…',
            icon: const Icon(Icons.add_circle_outline),
            onPressed: _busy || _preparing != null ? null : _actions,
          ),
          Expanded(
            child: TextField(
              key: const Key('ask-input'),
              controller: _input,
              minLines: 1,
              maxLines: 4,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: InputDecoration(
                hintText: _listening ? 'Listening…' : 'Ask about equipment, tickets, procedures',
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: 4),
          IconButton.filledTonal(
            key: const Key('ask-mic'),
            tooltip: _listening ? 'Stop listening' : 'Speak',
            style: _listening ? IconButton.styleFrom(backgroundColor: scheme.errorContainer) : null,
            icon: Icon(_listening ? Icons.mic : Icons.mic_none),
            onPressed: _busy ? null : _listen,
          ),
          _busy
              ? IconButton.filled(
                  key: const Key('ask-stop'), tooltip: 'Stop', icon: const Icon(Icons.stop), onPressed: _stop)
              : IconButton.filled(
                  key: const Key('ask-send'), tooltip: 'Ask', icon: const Icon(Icons.send), onPressed: _send),
          ]),
        ]),
      ),
    );
  }
}

class _Hint extends StatelessWidget {
  const _Hint();

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            'Ask a question, typed or spoken: “how is the vacuum pump on this line reset?”, '
            '“what failed on this position last month?”.\n\n'
            'Answers come from this workspace’s records, and name the ones they rest on. '
            'Check them before acting.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ),
      );
}

/// What was wrong with an answer, optionally: the text (maybe empty) to send it, null to cancel.
class _FeedbackDialog extends StatefulWidget {
  const _FeedbackDialog();

  @override
  State<_FeedbackDialog> createState() => _FeedbackDialogState();
}

class _FeedbackDialogState extends State<_FeedbackDialog> {
  final _comment = TextEditingController();

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Not useful'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          TextField(
            key: const Key('ask-feedback-comment'),
            controller: _comment,
            autofocus: true,
            maxLines: 4,
            maxLength: 5000,
            decoration: const InputDecoration(hintText: 'What was wrong or missing? (optional)'),
          ),
          Text('Sent without your name: the question, the answer and how it was found (workspace, model, lookups).',
              style: Theme.of(context).textTheme.bodySmall),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
              key: const Key('ask-feedback-send'),
              onPressed: () => Navigator.pop(context, _comment.text),
              child: const Text('Send')),
        ],
      );
}

class _TurnView extends StatelessWidget {
  const _TurnView({required this.turn, required this.speaking, required this.onReadAloud, this.onRate});

  final AskTurn turn;
  final bool speaking;
  final VoidCallback onReadAloud;
  /// Rate the answer (up | down); null while the conversation is not saved yet.
  final void Function(String rating)? onRate;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final notice = switch (turn.stopped) {
      'exhausted' => 'The search was cut short: this answer may be incomplete.',
      'cancelled' => 'Stopped.',
      'failed' => turn.error ?? 'The assistant could not answer.',
      _ => null,
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(left: 48, bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(color: scheme.primaryContainer, borderRadius: BorderRadius.circular(16)),
          child: Text(turn.question, style: TextStyle(color: scheme.onPrimaryContainer)),
        ),
      ),
      if (turn.lookups.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            for (final l in turn.lookups)
              Chip(
                visualDensity: VisualDensity.compact,
                avatar: l.done
                    ? Icon(l.error == null ? Icons.manage_search : Icons.error_outline, size: 16)
                    : const SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                label: Text(l.summary ?? _toolLabel(l.tool), style: theme.textTheme.labelSmall),
              ),
          ]),
        ),
      if (turn.answer.isNotEmpty)
        Container(
          padding: const EdgeInsets.fromLTRB(14, 10, 4, 4),
          decoration: BoxDecoration(color: scheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(16)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SelectionArea(
              child: RichContent(turn.answer,
                  key: const Key('ask-answer'),
                  selectable: false,
                  codeLink: turn.finished ? turn.recordLinks : const {},
                  onLink: (path) => context.push(path)),
            ),
            if (turn.finished)
              Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                if (onRate != null && turn.rating == null) ...[
                  IconButton(
                    key: const Key('ask-rate-up'),
                    tooltip: 'Useful',
                    icon: const Icon(Icons.thumb_up_outlined),
                    onPressed: () => onRate!('up'),
                  ),
                  IconButton(
                    key: const Key('ask-rate-down'),
                    tooltip: 'Not useful',
                    icon: const Icon(Icons.thumb_down_outlined),
                    onPressed: () => onRate!('down'),
                  ),
                ] else if (turn.rating != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: Icon(turn.rating == 'up' ? Icons.thumb_up : Icons.thumb_down,
                        size: 18, color: scheme.outline),
                  ),
                IconButton(
                  key: const Key('ask-read-aloud'),
                  tooltip: speaking ? 'Stop reading' : 'Read aloud',
                  icon: Icon(speaking ? Icons.stop_circle_outlined : Icons.volume_up_outlined),
                  onPressed: onReadAloud,
                ),
              ]),
          ]),
        )
      else if (!turn.finished)
        const Padding(
          padding: EdgeInsets.all(8),
          child: Align(alignment: Alignment.centerLeft, child: Text('Looking it up…')),
        ),
      if (notice != null)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: NoticeBar(icon: Icons.info_outline, text: notice),
        ),
      const SizedBox(height: 16),
    ]);
  }

  static String _toolLabel(String tool) => tool.replaceAll('_', ' ');
}

class _History extends ConsumerWidget {
  const _History();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(askConversationsProvider);
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.6,
      child: list.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(askConversationsProvider)),
        data: (items) => items.isEmpty
            ? const Center(child: Text('No earlier conversations.'))
            : ListView(children: [
                for (final c in items)
                  ListTile(
                    leading: const Icon(Icons.chat_bubble_outline),
                    title: Text(c.title, maxLines: 2, overflow: TextOverflow.ellipsis),
                    subtitle: c.updatedAt == null ? null : Text(formatWhenDate(c.updatedAt)),
                    onTap: () => Navigator.pop(context, c),
                  ),
              ]),
      ),
    );
  }
}


/// A document's title from its first words: the first line or sentence, at most 80 characters.
String firstLineOf(String text) {
  final first = text.trim().split(RegExp(r'[\n.!?]')).firstWhere((l) => l.trim().isNotEmpty, orElse: () => '').trim();
  final bare = first.replaceFirst(RegExp(r'^#+\s*'), '');
  return bare.length <= 80 ? bare : '${bare.substring(0, 77).trimRight()}…';
}
