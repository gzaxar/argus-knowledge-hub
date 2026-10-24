import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/attribute_form.dart';
import '../../widgets/common.dart';
import '../../widgets/photo_text.dart';

/// Changing a ticket after it was reported: its title, description, priority and the attributes its type
/// defines (typed as on a record: AttributeFields). Its state moves by the workflow's transitions on the
/// ticket screen, not here. Only what was changed is sent.
class TicketEditScreen extends ConsumerStatefulWidget {
  const TicketEditScreen({super.key, required this.uid});

  final String uid;

  @override
  ConsumerState<TicketEditScreen> createState() => _TicketEditScreenState();
}

class _TicketEditScreenState extends ConsumerState<TicketEditScreen> {
  final _form = AttributeFormController();
  TextEditingController? _title;
  TextEditingController? _description;
  String? _priority;
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _form.dispose();
    _title?.dispose();
    _description?.dispose();
    super.dispose();
  }

  void _start(TicketDetail t) {
    if (_title != null) return;
    _title = TextEditingController(text: t.title);
    _description = TextEditingController(text: t.description ?? '');
    _priority = t.priority;
  }

  Future<void> _save(TicketDetail t, List<AttributeDef> editable) async {
    final title = _title!.text.trim();
    if (title.isEmpty) {
      setState(() => _error = 'The title is required.');
      return;
    }
    final problem = _form.validate(editable);
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    final description = _description!.text.trim();
    final attributes = _form.collect(editable, t.attributes);
    final changes = <String, Object?>{
      if (title != t.title) 'title': title,
      if (description != (t.description ?? '').trim()) 'description': description.isEmpty ? null : description,
      if (_priority != t.priority) 'priority': _priority,
      if (jsonEncode(attributes) != jsonEncode(t.attributes)) 'attributes': attributes,
    };
    if (changes.isEmpty) {
      context.pop();
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref
          .read(ticketRepositoryProvider)
          .update(t.uid, changes, version: t.version, key: '${t.uid}-${DateTime.now().millisecondsSinceEpoch}');
      ref.invalidate(ticketDetailProvider(t.uid));
      ref.invalidate(ticketListProvider);
      if (mounted) context.pop();
    } on Problem catch (p) {
      if (p.code == ProblemCode.stale) {
        ref.invalidate(ticketDetailProvider(t.uid));
        setState(() => _error = 'Someone changed this ticket meanwhile. Reopen it and try again.');
      } else {
        setState(() => _error = p.message);
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(ticketDetailProvider(widget.uid));
    return Scaffold(
      appBar: AppBar(title: const Text('Edit ticket')),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(ticketDetailProvider(widget.uid))),
        data: (t) {
          _start(t);
          final defs = t.schemaUid == null
              ? const AsyncValue<List<AttributeDef>>.data([])
              : ref.watch(schemaAttributesProvider(t.schemaUid!));
          final priorities = ref.watch(ticketPrioritiesProvider).value ?? const [];
          return defs.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(schemaAttributesProvider(t.schemaUid!))),
            data: (defs) {
              for (final def in defs) {
                _form.ensure(def, t.attributes);
              }
              final editable = defs.where((d) => d.editable).toList();
              final options = {...priorities, ?_priority}.toList();
              return ListView(
                key: const Key('ticket-edit-list'),
                padding: const EdgeInsets.all(16),
                children: [
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: NoticeBar(icon: Icons.error_outline, text: _error!, severe: true),
                    ),
                  TextField(
                    key: const Key('ticket-edit-title'),
                    controller: _title,
                    decoration: const InputDecoration(labelText: 'Title *'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('ticket-edit-description'),
                    controller: _description,
                    minLines: 3,
                    maxLines: 10,
                    decoration: InputDecoration(
                        labelText: 'Description',
                        helperText: 'Markdown is kept as written',
                        suffixIcon: PhotoTextButton(key: const Key('photo-text-ticket-description'), controller: _description!)),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    key: const Key('ticket-edit-priority'),
                    initialValue: _priority,
                    decoration: const InputDecoration(labelText: 'Priority'),
                    items: [
                      const DropdownMenuItem(value: null, child: Text('—')),
                      for (final p in options) DropdownMenuItem(value: p, child: Text(p)),
                    ],
                    onChanged: (v) => setState(() => _priority = v),
                  ),
                  const SizedBox(height: 12),
                  if (editable.isNotEmpty) ...[
                    const SectionHeader('Details'),
                    AttributeFields(defs: editable, controller: _form),
                  ],
                  const SizedBox(height: 16),
                  FilledButton(
                    key: const Key('ticket-edit-save'),
                    onPressed: _saving ? null : () => _save(t, editable),
                    child: _saving
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Save'),
                  ),
                ],
              );
            },
          );
        },
      ),
    );
  }
}
