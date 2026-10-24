import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../data/activity_repository.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';
import 'activities_screen.dart';
import '../../widgets/photo_text.dart';

final activityDetailProvider = FutureProvider.autoDispose.family<ActivityItem, String>((ref, id) {
  ref.watch(workspaceIdProvider);
  return ref.watch(activityRepositoryProvider).get(id);
});

/// One activity: what, when (planned, and when it was actually done — not when it was recorded), its links,
/// where it came from; start, complete, skip or cancel it; change it — for an occurrence of a series: this one,
/// this and the future ones, or the whole series; and the workspaces it is in (a series' occurrences are in the
/// series' workspaces, so those change for this and the future ones, or for all).
class ActivityScreen extends ConsumerStatefulWidget {
  const ActivityScreen({super.key, required this.id});
  final String id;

  @override
  ConsumerState<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends ConsumerState<ActivityScreen> {
  bool _busy = false;

  Future<void> _run(Future<ActivityItem> Function() f) async {
    setState(() => _busy = true);
    try {
      final out = await f();
      ref.invalidate(activityListProvider);
      if (out.id != widget.id && mounted) {
        context.pushReplacement('/activity/${Uri.encodeComponent(out.id)}');
      } else {
        ref.invalidate(activityDetailProvider(widget.id));
      }
    } on Problem catch (p) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _edit(ActivityItem a) async {
    final title = TextEditingController(text: a.title);
    final description = TextEditingController(text: a.description ?? '');
    var when = a.plannedStart;
    var scope = 'this';
    final mine = ref.read(myWorkspacesProvider).value ?? const <WorkspaceChoice>[];
    var workspaces = [...a.workspaceIds];
    bool workspacesChanged() => workspaces.length != a.workspaceIds.length || !workspaces.every(a.workspaceIds.contains);
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheet) => StatefulBuilder(
        builder: (sheet, set) => Padding(
          padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.viewInsetsOf(sheet).bottom + 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            TextField(key: const Key('activity-edit-title'), controller: title, decoration: const InputDecoration(labelText: 'Title')),
            TextField(
                controller: description,
                minLines: 2,
                maxLines: 5,
                decoration: InputDecoration(
                    labelText: 'Description',
                    suffixIcon: PhotoTextButton(key: const Key('photo-text-activity-description'), controller: description))),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event_outlined),
              title: Text(when == null ? 'Planned: no date' : 'Planned: ${MaterialLocalizations.of(sheet).formatFullDate(when!)}'
                  '${a.allDay || when == null ? '' : ', ${MaterialLocalizations.of(sheet).formatTimeOfDay(TimeOfDay.fromDateTime(when!))}'}'),
              onTap: () async {
                final d = await showDatePicker(
                    context: sheet, initialDate: when ?? DateTime.now(), firstDate: DateTime(2000), lastDate: DateTime(2100));
                if (d == null || !sheet.mounted) return;
                final t = a.allDay ? null : await showTimePicker(
                    context: sheet, initialTime: when != null ? TimeOfDay.fromDateTime(when!) : TimeOfDay.now());
                set(() => when = DateTime(d.year, d.month, d.day, t?.hour ?? 0, t?.minute ?? 0));
              },
            ),
            if (mine.length > 1) ...[
              const SizedBox(height: 8),
              Text('In the workspaces', style: Theme.of(sheet).textTheme.labelLarge),
              Wrap(spacing: 8, children: [
                for (final w in mine)
                  FilterChip(
                    key: Key('activity-edit-ws-${w.id}'),
                    label: Text(w.name),
                    selected: workspaces.contains(w.id),
                    onSelected: (on) => set(() => on ? workspaces.add(w.id) : workspaces.remove(w.id)),
                  ),
              ]),
              if (a.recurring && workspacesChanged() && scope == 'this')
                const Text('The workspaces belong to the series: choose “This and future” or “All”.'),
              const SizedBox(height: 8),
            ],
            if (a.recurring)
              SegmentedButton<String>(
                key: const Key('activity-edit-scope'),
                segments: const [
                  ButtonSegment(value: 'this', label: Text('This one')),
                  ButtonSegment(value: 'future', label: Text('This and future')),
                  ButtonSegment(value: 'series', label: Text('All')),
                ],
                selected: {scope},
                onSelectionChanged: (s) => set(() => scope = s.first),
              ),
            const SizedBox(height: 12),
            FilledButton(
                key: const Key('activity-edit-save'),
                onPressed: (workspaces.isEmpty && a.workspaceIds.isNotEmpty) || (a.recurring && workspacesChanged() && scope == 'this')
                    ? null
                    : () => Navigator.pop(sheet, true),
                child: const Text('Save')),
          ]),
        ),
      ),
    );
    if (ok != true) return;
    final changes = <String, Object?>{
      if (title.text.trim() != a.title) 'title': title.text.trim(),
      if (description.text.trim() != (a.description ?? '')) 'description': description.text.trim(),
      if (when != null && when != a.plannedStart) 'planned_start': withOffset(when!),
      if (workspacesChanged()) 'workspace_ids': workspaces,
    };
    if (changes.isEmpty) return;
    await _run(() => ref.read(activityRepositoryProvider).change(a.id, changes, scope: scope));
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(activityDetailProvider(widget.id));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Activity'),
        actions: [
          if (r.value?.mayChange == true)
            IconButton(key: const Key('activity-edit'), tooltip: 'Change', icon: const Icon(Icons.edit), onPressed: _busy ? null : () => _edit(r.value!)),
        ],
      ),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(activityDetailProvider(widget.id))),
        data: (a) {
          final l = MaterialLocalizations.of(context);
          String at(DateTime? d) => d == null ? '—' : (a.allDay ? l.formatFullDate(d) : '${l.formatFullDate(d)}, ${l.formatTimeOfDay(TimeOfDay.fromDateTime(d))}');
          final repo = ref.read(activityRepositoryProvider);
          final transcript = (a.json['provenance'] as Map?)?['transcript'];
          final mine = ref.watch(myWorkspacesProvider).value ?? const <WorkspaceChoice>[];
          final named = [for (final id in a.workspaceIds) mine.where((w) => w.id == id).firstOrNull?.name];
          final others = named.where((n) => n == null).length;
          return ListView(key: const Key('activity-body'), padding: const EdgeInsets.all(16), children: [
            Text(a.title, key: const Key('activity-title'), style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 4),
            Text([
              switch (a.status) { 'in_progress' => 'Under way', 'completed' => 'Done', 'cancelled' => 'Cancelled', 'skipped' => 'Skipped', _ => 'Planned' },
              if (a.overdue) 'overdue',
              a.visibility == 'private' ? 'only its owner and assignee see it' : 'the workspace sees it',
            ].join(' · ')),
            if ((a.description ?? '').isNotEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Text(a.description!)),
            const Divider(height: 24),
            if (a.plannedStart != null) _row('Planned', at(a.plannedStart)),
            if (a.dueAt != null) _row('Due', at(a.dueAt)),
            if (a.actualStart != null) _row('Started', at(a.actualStart)),
            if (a.actualEnd != null) _row('Done', at(a.actualEnd)),
            if (a.createdAt != null) _row('Recorded', at(a.createdAt)),
            if (a.recurring) _row('Repeats', a.recurrence ?? ''),
            if (a.workspaceIds.length > 1 || others > 0)
              _row('Workspaces', [...named.whereType<String>(), if (others > 0) '$others other'].join(', ')),
            if (a.note != null) _row('Note', a.note!),
            if (a.assetUid != null)
              ListTile(contentPadding: EdgeInsets.zero, leading: const Icon(Icons.memory_outlined), title: const Text('The asset'),
                  onTap: () => context.push('/asset/${a.assetUid}')),
            if (a.ticketUid != null)
              ListTile(contentPadding: EdgeInsets.zero, leading: const Icon(Icons.confirmation_number_outlined),
                  title: const Text('The ticket (not changed by this activity)'), onTap: () => context.push('/ticket/${a.ticketUid}')),
            if (transcript != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Captured by voice: “$transcript”', style: Theme.of(context).textTheme.bodySmall),
              ),
            if (a.mayChange) ...[
              const SizedBox(height: 16),
              Wrap(spacing: 8, runSpacing: 8, children: [
                if (a.status == 'planned')
                  FilledButton.icon(key: const Key('activity-start'), onPressed: _busy ? null : () => _run(() => repo.act(a.id, 'start')),
                      icon: const Icon(Icons.play_arrow), label: const Text('Start')),
                if (a.open)
                  FilledButton.icon(key: const Key('activity-complete'), onPressed: _busy ? null : () => _run(() => repo.act(a.id, 'complete')),
                      icon: const Icon(Icons.check), label: const Text('Done')),
                if (a.status == 'planned' && a.recurring)
                  OutlinedButton(key: const Key('activity-skip'), onPressed: _busy ? null : () => _run(() => repo.act(a.id, 'skip')),
                      child: const Text('Skip this one')),
                if (a.open)
                  OutlinedButton(key: const Key('activity-cancel'), onPressed: _busy ? null : () => _run(() => repo.act(a.id, 'cancel')),
                      child: const Text('Cancel')),
                if (!a.open)
                  OutlinedButton(key: const Key('activity-reopen'), onPressed: _busy ? null : () => _run(() => repo.act(a.id, 'reopen')),
                      child: const Text('Reopen')),
              ]),
            ],
          ]);
        },
      ),
    );
  }

  Widget _row(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 96, child: Text(k, style: const TextStyle(fontWeight: FontWeight.w500))),
          Expanded(child: Text(v)),
        ]),
      );
}
