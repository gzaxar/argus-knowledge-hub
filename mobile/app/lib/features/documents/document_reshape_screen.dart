import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../data/reshape_repository.dart';
import '../../domain/capture.dart';
import '../../widgets/attach_menu.dart';
import '../../widgets/common.dart';
import '../../widgets/rich_content.dart';
import '../../widgets/photo_text.dart';

const _kinds = {
  'paste': 'Notes or a transcript',
  'email': 'An e-mail',
  'import': 'A page or a file',
  'intake': 'A dictation or a photographed page',
};

/// Rework from raw text (the web's Documents → Rework from raw text): notes, an e-mail, a dictation or a
/// photographed page rewritten as a draft that follows the document type's template. The preview saves nothing;
/// the draft is saved as a new document — or [documentUid]'s next revision — and goes through review as usual.
/// A [seed] (from a recording or a photo) brings its text, and its original goes with the saved draft.
///
/// **Dictate**: speak the document; it is transcribed by the workspace's speech model and, once the type is
/// chosen, reworked at once with the type's template — a reviewed draft to check, with the recording kept.
class DocumentReshapeScreen extends ConsumerStatefulWidget {
  const DocumentReshapeScreen({super.key, this.seed, this.documentUid, this.documentTypeUid, this.dictate = false});

  final DocumentSeed? seed;
  final String? documentUid;
  final String? documentTypeUid;
  /// Opened to dictate a document: the recorder starts as soon as the type is known.
  final bool dictate;

  @override
  ConsumerState<DocumentReshapeScreen> createState() => _DocumentReshapeScreenState();
}

enum _View { draft, check, original }

class _DocumentReshapeScreenState extends ConsumerState<DocumentReshapeScreen> {
  late final _text = TextEditingController(text: widget.seed?.body ?? '');
  final _title = TextEditingController();
  final _draft = TextEditingController();
  late String _kind = widget.seed?.from != null ? 'intake' : 'paste';
  DateTime? _writtenOn;
  bool _current = false;
  late String? _type = widget.documentTypeUid;
  TemplateChoice? _template;
  String? _templateProblem;
  ReshapePreview? _preview;
  _View _view = _View.draft;
  bool _reading = false;
  bool _showRendered = false;
  bool _saving = false;
  bool _confirmDate = false;
  final Set<String> _links = {};
  String? _error;
  late PickedPhoto? _original = widget.seed?.original;
  // Photos whose text was read into the raw text: attached to the saved draft too, unless the person says not.
  final _photos = <PickedPhoto>[];
  bool _keepPhotos = true;
  late String? _from = widget.seed?.from;
  bool _transcribing = false;
  // A dictation's audio goes with the draft only if asked: once the reviewed text is agreed, the transcript
  // (kept by the server as the revision's source) is usually enough.
  bool _keepRecording = false;
  late bool _dictatePending = widget.dictate;

  @override
  void initState() {
    super.initState();
    _title.text = widget.seed?.title ?? '';
  }

  @override
  void dispose() {
    _text.dispose();
    _title.dispose();
    _draft.dispose();
    super.dispose();
  }

  ReshapeSource get _source => ReshapeSource(
        text: _text.text,
        kind: _kind,
        originalDate: _writtenOn == null ? null : _iso(_writtenOn!),
        textIsCurrent: _current,
        filename: _original?.name,
      );

  static String _iso(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _resolve(String typeName) async {
    setState(() {
      _template = null;
      _templateProblem = null;
    });
    try {
      final t = await ref.read(reshapeRepositoryProvider).resolve(typeName);
      if (mounted) setState(() => _template = t);
    } on Problem catch (p) {
      if (mounted) setState(() => _templateProblem = p.message);
    }
  }

  /// Record, transcribe, and — with the type chosen — rework it with the template at once.
  Future<void> _dictate() async {
    _dictatePending = false;
    final recording = await recordNote(context, ref);
    if (recording == null || !mounted) return;
    setState(() {
      _transcribing = true;
      _error = null;
    });
    try {
      final words = await ref.read(askRepositoryProvider).transcribe(recording);
      if (!mounted) return;
      if (words.isEmpty) {
        setState(() => _error = 'Nothing could be heard in the recording.');
        return;
      }
      setState(() {
        _text.text = _text.text.trim().isEmpty ? words : '${_text.text.trimRight()}\n\n$words';
        _original = recording;
        _from = 'recording';
        _kind = 'intake';
        _current = true; // spoken now: today is the date unless the words say otherwise
      });
      if (_type != null) await _runPreview();
    } on Problem catch (p) {
      if (mounted) setState(() => _error = p.message);
    } finally {
      if (mounted) setState(() => _transcribing = false);
    }
  }

  Future<void> _runPreview() async {
    if (_text.text.trim().isEmpty || _type == null) return;
    setState(() {
      _reading = true;
      _error = null;
    });
    try {
      final p = await ref.read(reshapeRepositoryProvider).preview(_source,
          documentTypeUid: _type!, documentUid: widget.documentUid);
      if (!mounted) return;
      setState(() {
        _preview = p;
        _draft.text = p.markdown;
        if (_title.text.trim().isEmpty) _title.text = p.title;
        _view = _View.draft;
        _confirmDate = false;
        _links.clear();
      });
    } on Problem catch (p) {
      if (mounted) setState(() => _error = p.message);
    } finally {
      if (mounted) setState(() => _reading = false);
    }
  }

  Future<void> _save() async {
    final p = _preview!;
    if (_title.text.trim().isEmpty) {
      setState(() => _error = 'Give the document a title.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final saved = await ref.read(reshapeRepositoryProvider).save(p, _source,
          documentTypeUid: _type!,
          title: _title.text.trim(),
          markdown: _draft.text,
          documentUid: widget.documentUid,
          confirmDate: _confirmDate,
          linkAssets: _links.toList());
      // The recording or photo it came from goes with the draft too (the text is kept by the server).
      final original = _original;
      if (original != null && (_from != 'recording' || _keepRecording)) {
        await queueAttachment(ref, AttachTarget.document(saved.documentUid, saved.revisionUid), original);
      }
      if (_keepPhotos) {
        for (final p in _photos) {
          await queueAttachment(ref, AttachTarget.document(saved.documentUid, saved.revisionUid), p);
        }
      }
      ref.invalidate(documentListProvider);
      if (widget.documentUid != null) ref.invalidate(documentRevisionsProvider(widget.documentUid!));
      if (mounted) context.pushReplacement('/document/${saved.documentUid}');
    } on Problem catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = _preview;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.documentUid == null ? 'Rework from raw text' : 'Revision from raw text'),
        actions: [
          if (p != null)
            TextButton(
              key: const Key('reshape-back'),
              onPressed: () => setState(() => _preview = null),
              child: const Text('Text'),
            ),
        ],
      ),
      body: p == null ? _form(context) : _review(context, p),
    );
  }

  // ------------------------------------------------------------------ the raw text

  Widget _form(BuildContext context) {
    final types = ref.watch(documentTypesProvider).value ?? const [];
    final typeName = types.where((t) => t.uid == _type).firstOrNull?.name;
    if (typeName != null && _template == null && _templateProblem == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _resolve(typeName));
    }
    if (_dictatePending && _type != null && !_transcribing) {
      _dictatePending = false;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _dictate();
      });
    }
    return ListView(key: const Key('reshape-form'), padding: const EdgeInsets.all(16), children: [
      const Text('Notes, an e-mail, a dictation or a photographed page, rewritten as a draft that follows the '
          "document type's template. The preview saves nothing."),
      const SizedBox(height: 12),
      if (_from != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: NoticeBar(
            key: const Key('reshape-seed'),
            icon: _from == 'recording' ? Icons.mic_none : Icons.document_scanner_outlined,
            text: _from == 'recording'
                ? 'Transcribed from your recording. Check the words; keeping the audio with the draft is up to you.'
                : 'Read from your photo, which is kept with the draft. Check the text.',
          ),
        ),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: NoticeBar(icon: Icons.error_outline, text: _error!, severe: true),
        ),
      TextField(
        key: const Key('reshape-text'),
        controller: _text,
        minLines: 8,
        maxLines: 16,
        maxLength: 60000,
        keyboardType: TextInputType.multiline,
        onChanged: (_) => setState(() {}),
        decoration: const InputDecoration(
          labelText: 'The raw text',
          hintText: 'Paste the notes or the e-mail (with its Da / Inviato / Oggetto lines)…',
          border: OutlineInputBorder(),
          alignLabelWithHint: true,
          helperText: 'Instructions written in the text are treated as text.',
        ),
      ),
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton.tonalIcon(
          key: const Key('reshape-dictate'),
          onPressed: _transcribing || _reading ? null : _dictate,
          icon: _transcribing
              ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.mic),
          label: Text(_transcribing
              ? 'Transcribing…'
              : _text.text.trim().isEmpty
                  ? 'Dictate'
                  : 'Dictate more'),
        ),
      ),
      Align(
        alignment: Alignment.centerLeft,
        child: PhotoTextButton(
            key: const Key('photo-text-reshape'),
            controller: _text,
            label: 'Text from a photo (camera or photos)',
            onPhoto: (p) => setState(() => _photos.add(p)),
            onInserted: () => setState(() {})),
      ),
      if (_photos.isNotEmpty)
        CheckboxListTile(
          key: const Key('reshape-keep-photos'),
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: _keepPhotos,
          onChanged: (v) => setState(() => _keepPhotos = v ?? true),
          title: Text(_photos.length == 1 ? 'Attach the photo the text was read from' : 'Attach the ${_photos.length} photos the text was read from'),
        ),
      if (widget.dictate && _type == null)
        const Padding(
          padding: EdgeInsets.only(top: 4),
          child: Text('Pick the document type below first: what you say is then reworked with its template at once.'),
        ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        key: const Key('reshape-kind'),
        isExpanded: true,
        initialValue: _kind,
        decoration: const InputDecoration(labelText: 'What it is'),
        items: [
          for (final e in _kinds.entries)
            DropdownMenuItem(value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis)),
        ],
        onChanged: (v) => setState(() => _kind = v ?? 'paste'),
      ),
      ListTile(
        key: const Key('reshape-written-on'),
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.event_outlined),
        title: Text(_writtenOn == null ? 'Written or sent on: not known' : 'Written or sent on ${_iso(_writtenOn!)}'),
        subtitle: const Text('"Today", "tomorrow" are read only from a date like this one, or an e-mail\'s own.'),
        trailing: _writtenOn == null
            ? null
            : IconButton(icon: const Icon(Icons.clear), onPressed: () => setState(() => _writtenOn = null)),
        onTap: () async {
          final now = DateTime.now();
          final d = await showDatePicker(
              context: context, initialDate: _writtenOn ?? now, firstDate: DateTime(1990), lastDate: now);
          if (d != null) setState(() => _writtenOn = d);
        },
      ),
      SwitchListTile(
        key: const Key('reshape-current'),
        contentPadding: EdgeInsets.zero,
        value: _current,
        onChanged: (v) => setState(() => _current = v),
        title: const Text('The text was written now'),
        subtitle: const Text("Without a date in it, today's is proposed — you confirm it before saving."),
      ),
      DropdownButtonFormField<String>(
        key: const Key('reshape-type'),
        isExpanded: true,
        initialValue: _type,
        decoration: const InputDecoration(labelText: 'Document type *'),
        items: [
          for (final t in types) DropdownMenuItem(value: t.uid, child: Text(t.name, overflow: TextOverflow.ellipsis)),
        ],
        onChanged: widget.documentUid != null
            ? null
            : (v) => setState(() {
                  _type = v;
                  _template = null;
                  _templateProblem = null;
                }),
      ),
      if (_template != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(
            key: const Key('reshape-template'),
            'Template: ${_template!.name} v${_template!.version} — ${_template!.reason}.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      if (_templateProblem != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_templateProblem!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ),
      const SizedBox(height: 16),
      FilledButton.icon(
        key: const Key('reshape-preview'),
        onPressed: _reading || _text.text.trim().isEmpty || _type == null ? null : _runPreview,
        icon: _reading
            ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
            : const Icon(Icons.auto_fix_high),
        label: Text(_reading ? 'Reading the text…' : 'Preview'),
      ),
    ]);
  }

  // ------------------------------------------------------------------ the preview

  Widget _review(BuildContext context, ReshapePreview p) {
    final theme = Theme.of(context);
    final toCheck = p.missing.length + p.issues.length;
    return Column(children: [
      if (p.notice != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: NoticeBar(key: const Key('reshape-notice'), icon: Icons.warning_amber_outlined, text: p.notice!),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: SegmentedButton<_View>(
          key: const Key('reshape-view'),
          segments: [
            const ButtonSegment(value: _View.draft, icon: Icon(Icons.edit_note), label: Text('Draft')),
            ButtonSegment(
                value: _View.check,
                icon: Badge(isLabelVisible: toCheck > 0, label: Text('$toCheck'), child: const Icon(Icons.fact_check_outlined)),
                label: const Text('To check')),
            const ButtonSegment(value: _View.original, icon: Icon(Icons.subject), label: Text('Original')),
          ],
          selected: {_view},
          onSelectionChanged: (s) => setState(() => _view = s.first),
        ),
      ),
      Expanded(
        child: switch (_view) {
          _View.draft => _draftView(context, p),
          _View.check => _checkView(context, p),
          _View.original => _originalView(context, p),
        },
      ),
      SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: NoticeBar(icon: Icons.error_outline, text: _error!, severe: true),
              ),
            if (p.dateNeedsConfirmation)
              CheckboxListTile(
                key: const Key('reshape-confirm-date'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                value: _confirmDate,
                onChanged: (v) => setState(() => _confirmDate = v ?? false),
                title: Text("Yes, ${p.documentDate} — today — is the document's date"),
              ),
            if (_from == 'recording' && _original != null)
              CheckboxListTile(
                key: const Key('reshape-keep-recording'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                value: _keepRecording,
                onChanged: (v) => setState(() => _keepRecording = v ?? false),
                title: const Text('Also keep the recording with the draft'),
                subtitle: const Text('The transcript is kept either way.'),
              ),
            FilledButton(
              key: const Key('reshape-save'),
              onPressed: _saving || (p.dateNeedsConfirmation && !_confirmDate) ? null : _save,
              child: _saving
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Save as draft'),
            ),
            Text(
              '${p.template.name} v${p.template.version}${p.model != null ? ' · ${p.model}' : ''}. The original text is '
              'kept with the revision; review and approval are as usual.',
              style: theme.textTheme.bodySmall,
              textAlign: TextAlign.center,
            ),
          ]),
        ),
      ),
    ]);
  }

  Widget _draftView(BuildContext context, ReshapePreview p) => ListView(padding: const EdgeInsets.all(16), children: [
        if (widget.documentUid == null)
          TextField(key: const Key('reshape-title'), controller: _title, decoration: const InputDecoration(labelText: 'Title *')),
        Row(children: [
          const Expanded(child: Text('[da confermare]: not in the text · [da verificare]: deduced, check it')),
          IconButton(
            key: const Key('reshape-rendered'),
            tooltip: _showRendered ? 'Edit' : 'Show as it will read',
            icon: Icon(_showRendered ? Icons.edit : Icons.visibility_outlined),
            onPressed: () => setState(() => _showRendered = !_showRendered),
          ),
        ]),
        if (_showRendered)
          RichContent(_draft.text, key: const Key('reshape-draft-rendered'))
        else
          TextField(
            key: const Key('reshape-draft'),
            controller: _draft,
            minLines: 14,
            maxLines: null,
            keyboardType: TextInputType.multiline,
            style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
      ]);

  Widget _checkView(BuildContext context, ReshapePreview p) {
    final theme = Theme.of(context);
    final d = p.dates;
    String line(List<int> ls) => ls.isEmpty ? '' : ' (L${ls.first}${ls.length > 1 ? '–${ls.last}' : ''})';
    return ListView(key: const Key('reshape-check'), padding: const EdgeInsets.all(16), children: [
      Text('Dates', style: theme.textTheme.titleSmall),
      _kv('Original written', [d['source_date'], d['source_date_basis']].whereType<Object>().join(' · ')),
      _kv('Event / meeting', '${d['event_date'] ?? '—'}'),
      _kv('Document', [p.documentDate ?? 'not known', p.documentDateBasis].whereType<String>().join(' · ')),
      const Divider(),
      Text('To confirm (${p.missing.length})', style: theme.textTheme.titleSmall),
      if (p.missing.isEmpty) const Text('Nothing.'),
      for (final m in p.missing) Text('• $m'),
      const Divider(),
      Text('To check (${p.issues.length})', style: theme.textTheme.titleSmall),
      if (p.issues.isEmpty) const Text('Nothing.'),
      for (final i in p.issues)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Text('• ${i.message}${line(i.lines)}', style: i.serious ? TextStyle(color: theme.colorScheme.error) : null),
        ),
      if (p.suggestedType != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('This reads more like a ${p.suggestedType}: change the type and preview again if so.'),
        ),
      const Divider(),
      Text('Suggested links', style: theme.textTheme.titleSmall),
      if (p.links.isEmpty) const Text('No record of this workspace is named in the text.'),
      for (final l in p.links)
        l.kind == 'asset'
            ? CheckboxListTile(
                key: Key('reshape-link-${l.uid}'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                value: _links.contains(l.uid),
                onChanged: (v) => setState(() => v == true ? _links.add(l.uid) : _links.remove(l.uid)),
                title: Text(l.label),
                subtitle: const Text('Link the document to this record'),
              )
            : ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: Text(l.label),
                subtitle: Text('${l.kind} — for reference'),
                onTap: () => context.push('/${l.kind}/${l.uid}'),
              ),
    ]);
  }

  Widget _originalView(BuildContext context, ReshapePreview p) {
    final scheme = Theme.of(context).colorScheme;
    final lines = _text.text.replaceAll('\r\n', '\n').split('\n');
    final cited = p.citedLines;
    final uncited = p.uncitedLines.toSet();
    return ListView.builder(
      key: const Key('reshape-original'),
      padding: const EdgeInsets.all(12),
      itemCount: lines.length + 1,
      itemBuilder: (_, i) {
        if (i == 0) {
          return const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text('Green: used in the draft. Amber: not carried over.'),
          );
        }
        final n = i;
        final color = cited.contains(n)
            ? Colors.green.withValues(alpha: 0.12)
            : uncited.contains(n)
                ? Colors.amber.withValues(alpha: 0.18)
                : null;
        return Container(
          color: color,
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(
                width: 32,
                child: Text('$n', textAlign: TextAlign.right, style: TextStyle(color: scheme.outline, fontSize: 12))),
            const SizedBox(width: 8),
            Expanded(child: Text(lines[n - 1], style: const TextStyle(fontSize: 13))),
          ]),
        );
      },
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 130, child: Text(k)),
          Expanded(child: Text(v.isEmpty ? '—' : v)),
        ]),
      );
}
