import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../app/queue.dart';
import '../../core/problem.dart';
import '../../data/activity_repository.dart';
import '../../widgets/common.dart';

/// The phone's lists: Today, Upcoming, Completed — by the phone's time zone.
final activityListProvider = FutureProvider.autoDispose.family<ActivityPage, String>((ref, view) async {
  ref.watch(workspaceIdProvider);
  final tz = await ref.watch(deviceTimezoneProvider.future);
  return ref.watch(activityRepositoryProvider).list(view: view, timezone: tz, filters: const {'mine': 'true'});
});

/// What the workspace view asks: a range, by planned or done date, filtered.
class ActivityQuery {
  const ActivityQuery({required this.from, required this.to, this.basis = 'planned', this.filters = const {}});
  final DateTime from, to;
  final String basis;
  final Map<String, String> filters;

  @override
  bool operator ==(Object other) =>
      other is ActivityQuery && other.from == from && other.to == to && other.basis == basis &&
      _same(other.filters, filters);
  @override
  int get hashCode => Object.hash(from, to, basis, Object.hashAllUnordered(filters.entries.map((e) => '${e.key}=${e.value}')));
  static bool _same(Map a, Map b) => a.length == b.length && a.entries.every((e) => b[e.key] == e.value);
}

final workspaceActivitiesProvider = FutureProvider.autoDispose.family<ActivityPage, ActivityQuery>((ref, q) async {
  ref.watch(workspaceIdProvider);
  final tz = await ref.watch(deviceTimezoneProvider.future);
  return ref.watch(activityRepositoryProvider)
      .list(from: q.from, to: q.to, basis: q.basis, timezone: tz, filters: q.filters, limit: 500);
});

String _statusLabel(String s) => switch (s) {
      'in_progress' => 'Under way',
      'completed' => 'Done',
      'cancelled' => 'Cancelled',
      'skipped' => 'Skipped',
      _ => 'Planned',
    };

IconData _statusIcon(String s) => switch (s) {
      'in_progress' => Icons.play_circle_outline,
      'completed' => Icons.check_circle,
      'cancelled' => Icons.cancel_outlined,
      'skipped' => Icons.redo,
      _ => Icons.radio_button_unchecked,
    };

String whenText(BuildContext context, ActivityItem a) {
  final d = a.when;
  if (d == null) return 'No date';
  final l = MaterialLocalizations.of(context);
  final day = l.formatMediumDate(d);
  return a.allDay ? day : '$day ${l.formatTimeOfDay(TimeOfDay.fromDateTime(d))}';
}

/// Activities: yours today, upcoming and done; and the workspace's, by range, as a calendar or a list.
class ActivitiesScreen extends ConsumerStatefulWidget {
  const ActivitiesScreen({super.key});

  @override
  ConsumerState<ActivitiesScreen> createState() => _ActivitiesScreenState();
}

class _ActivitiesScreenState extends ConsumerState<ActivitiesScreen> {
  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 4,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Activities'),
            actions: [
              IconButton(
                key: const Key('activities-capture'),
                tooltip: 'Capture by voice',
                icon: const Icon(Icons.mic),
                onPressed: () => context.push('/capture'),
              ),
            ],
            bottom: const TabBar(isScrollable: true, tabs: [
              Tab(key: Key('activities-today'), text: 'Today'),
              Tab(key: Key('activities-upcoming'), text: 'Upcoming'),
              Tab(key: Key('activities-completed'), text: 'Completed'),
              Tab(key: Key('activities-workspace'), text: 'Workspace'),
            ]),
          ),
          body: const TabBarView(children: [
            _MyList(view: 'today'),
            _MyList(view: 'upcoming'),
            _MyList(view: 'completed'),
            WorkspaceActivities(),
          ]),
        ),
      );
}

class _MyList extends ConsumerWidget {
  const _MyList({required this.view});
  final String view;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(activityListProvider(view));
    return r.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(activityListProvider(view))),
      data: (page) => RefreshIndicator(
        onRefresh: () async => ref.invalidate(activityListProvider(view)),
        child: page.items.isEmpty
            ? ListView(children: [
                Padding(
                  padding: const EdgeInsets.all(32),
                  child: Text(
                    switch (view) {
                      'today' => 'Nothing for today. Capture one with the microphone.',
                      'upcoming' => 'Nothing planned in the next 30 days.',
                      _ => 'Nothing done in the last 30 days.',
                    },
                    textAlign: TextAlign.center,
                  ),
                ),
              ])
            : ListView(key: Key('activities-$view-list'), children: [
                for (final a in page.items) ActivityTile(activity: a, onChanged: () => ref.invalidate(activityListProvider(view))),
              ]),
      ),
    );
  }
}

/// One activity in a list: when, what, its state; start or complete it in place where allowed.
class ActivityTile extends ConsumerWidget {
  const ActivityTile({super.key, required this.activity, this.onChanged});
  final ActivityItem activity;
  final VoidCallback? onChanged;

  Future<void> _act(BuildContext context, WidgetRef ref, String action) async {
    try {
      final queue = ref.read(queueProvider.notifier);
      final c = await queue.enqueue(
            kind: 'activity.action',
            key: 'activity-action:${const Uuid().v4()}',
            target: activity.id,
            label: '${action == 'complete' ? 'Done' : 'Started'}: ${activity.title}',
            payload: {'id': activity.id, 'action': action, 'body': const <String, Object?>{}},
          );
      final sent = await queue.sendNow(c);
      if (sent.needsPerson) throw Problem(ProblemCode.invalid, describe(sent));
      if (sent.open && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describe(sent))));
      }
      onChanged?.call();
    } on Problem catch (p) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final a = activity;
    final scheme = Theme.of(context).colorScheme;
    return ListTile(
      key: Key('activity-${a.id}'),
      leading: Icon(_statusIcon(a.status), color: a.overdue ? scheme.error : null, semanticLabel: _statusLabel(a.status)),
      title: Text(a.title),
      subtitle: Text([
        whenText(context, a),
        _statusLabel(a.status),
        if (a.overdue) 'overdue',
        if (a.recurring) (a.recurrence ?? 'repeats'),
        if (a.visibility == 'private') 'only me',
      ].join(' · ')),
      onTap: () => context.push('/activity/${Uri.encodeComponent(a.id)}'),
      trailing: !a.mayChange || !a.open
          ? null
          : a.status == 'planned' && (a.plannedStart == null || !a.plannedStart!.isAfter(DateTime.now().add(const Duration(hours: 12))))
              ? IconButton(
                  key: Key('activity-start-${a.id}'),
                  tooltip: 'Start',
                  icon: const Icon(Icons.play_arrow),
                  onPressed: () => _act(context, ref, 'start'))
              : a.status == 'in_progress'
                  ? IconButton(
                      key: Key('activity-complete-${a.id}'),
                      tooltip: 'Done',
                      icon: const Icon(Icons.check),
                      onPressed: () => _act(context, ref, 'complete'))
                  : null,
    );
  }
}

/// The workspace's activities over a range: by planned date or by the date the work was done; as a calendar
/// (day by day, with times) or a list; filtered; with counts. Only what you may see is shown or counted.
class WorkspaceActivities extends ConsumerStatefulWidget {
  const WorkspaceActivities({super.key});

  @override
  ConsumerState<WorkspaceActivities> createState() => _WorkspaceActivitiesState();
}

class _WorkspaceActivitiesState extends ConsumerState<WorkspaceActivities> {
  late DateTimeRange _range = _week(DateTime.now());
  String _basis = 'planned';
  bool _calendar = true;
  final Set<String> _statuses = {};
  bool _mine = false;
  bool? _recurring;
  String? _visibility;

  static DateTimeRange _week(DateTime d) {
    final start = DateTime(d.year, d.month, d.day).subtract(Duration(days: d.weekday - 1));
    return DateTimeRange(start: start, end: start.add(const Duration(days: 7)));
  }

  ActivityQuery get _query => ActivityQuery(from: _range.start, to: _range.end, basis: _basis, filters: {
        if (_statuses.isNotEmpty) 'status': (_statuses.toList()..sort()).join(','),
        if (_mine) 'mine': 'true',
        if (_recurring != null) 'recurring': '$_recurring',
        'visibility': ?_visibility,
      });

  @override
  Widget build(BuildContext context) {
    final q = _query;
    final r = ref.watch(workspaceActivitiesProvider(q));
    final l = MaterialLocalizations.of(context);
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
        child: Row(children: [
          IconButton(
              tooltip: 'Previous',
              icon: const Icon(Icons.chevron_left),
              onPressed: () => setState(() => _range = DateTimeRange(
                  start: _range.start.subtract(_range.duration), end: _range.start))),
          Expanded(
            child: TextButton(
              key: const Key('activities-range'),
              onPressed: () async {
                final picked = await showDateRangePicker(
                    context: context,
                    firstDate: DateTime(2000),
                    lastDate: DateTime(2100),
                    initialDateRange: DateTimeRange(start: _range.start, end: _range.end.subtract(const Duration(days: 1))));
                if (picked != null) {
                  setState(() => _range = DateTimeRange(start: picked.start, end: picked.end.add(const Duration(days: 1))));
                }
              },
              child: Text('${l.formatMediumDate(_range.start)} – ${l.formatMediumDate(_range.end.subtract(const Duration(days: 1)))}'),
            ),
          ),
          IconButton(
              tooltip: 'Next',
              icon: const Icon(Icons.chevron_right),
              onPressed: () => setState(() => _range = DateTimeRange(start: _range.end, end: _range.end.add(_range.duration)))),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          SegmentedButton<String>(
            key: const Key('activities-basis'),
            segments: const [
              ButtonSegment(value: 'planned', label: Text('Planned for')),
              ButtonSegment(value: 'actual', label: Text('Done on')),
            ],
            selected: {_basis},
            onSelectionChanged: (s) => setState(() => _basis = s.first),
          ),
          SegmentedButton<bool>(
            key: const Key('activities-mode'),
            segments: const [
              ButtonSegment(value: true, icon: Icon(Icons.calendar_view_week), label: Text('Calendar')),
              ButtonSegment(value: false, icon: Icon(Icons.list), label: Text('List')),
            ],
            selected: {_calendar},
            onSelectionChanged: (s) => setState(() => _calendar = s.first),
          ),
        ]),
      ),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          for (final s in const ['planned', 'in_progress', 'completed', 'skipped', 'cancelled'])
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: FilterChip(
                key: Key('activities-filter-$s'),
                label: Text('${_statusLabel(s)}${r.value != null ? ' ${r.value!.counts[s] ?? 0}' : ''}'),
                selected: _statuses.contains(s),
                onSelected: (v) => setState(() => v ? _statuses.add(s) : _statuses.remove(s)),
              ),
            ),
          if (r.value != null && (r.value!.counts['overdue'] ?? 0) > 0)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: Chip(
                  key: const Key('activities-overdue'),
                  avatar: const Icon(Icons.warning_amber, size: 16),
                  label: Text('Overdue ${r.value!.counts['overdue']}')),
            ),
          FilterChip(label: const Text('Mine'), selected: _mine, onSelected: (v) => setState(() => _mine = v)),
          const SizedBox(width: 6),
          FilterChip(
              key: const Key('activities-filter-recurring'),
              label: const Text('Recurring'),
              selected: _recurring == true,
              onSelected: (v) => setState(() => _recurring = v ? true : null)),
          const SizedBox(width: 6),
          FilterChip(
              label: const Text('Only me'),
              selected: _visibility == 'private',
              onSelected: (v) => setState(() => _visibility = v ? 'private' : null)),
        ]),
      ),
      Expanded(
        child: r.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(workspaceActivitiesProvider(q))),
          data: (page) => page.items.isEmpty
              ? Center(
                  child: Text(_basis == 'planned' ? 'Nothing planned in this range.' : 'Nothing done in this range.'))
              : _calendar
                  ? _CalendarView(page: page, range: _range, basis: _basis, onChanged: () => ref.invalidate(workspaceActivitiesProvider(q)))
                  : ListView(key: const Key('activities-workspace-list'), children: [
                      for (final a in page.items)
                        ActivityTile(activity: a, onChanged: () => ref.invalidate(workspaceActivitiesProvider(q))),
                      if (page.nextOffset != null)
                        const Padding(
                            padding: EdgeInsets.all(16),
                            child: Text('More in this range: narrow the range or the filters.', textAlign: TextAlign.center)),
                    ]),
        ),
      ),
    ]);
  }
}

/// Day by day across the range, in local time: each day's activities by their time.
class _CalendarView extends StatelessWidget {
  const _CalendarView({required this.page, required this.range, required this.basis, this.onChanged});
  final ActivityPage page;
  final DateTimeRange range;
  final String basis;
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    DateTime? keyOf(ActivityItem a) {
      final d = basis == 'actual' ? (a.actualStart ?? a.actualEnd) : (a.plannedStart ?? a.dueAt);
      return d == null ? null : DateTime(d.year, d.month, d.day);
    }

    final byDay = <DateTime, List<ActivityItem>>{};
    for (final a in page.items) {
      var k = keyOf(a);
      if (k == null) continue;
      if (k.isBefore(range.start)) k = range.start;             // began before the range: shown on its first day
      byDay.putIfAbsent(k, () => []).add(a);
    }
    final l = MaterialLocalizations.of(context);
    final days = <DateTime>[];
    for (var d = range.start; d.isBefore(range.end); d = DateTime(d.year, d.month, d.day + 1)) {
      days.add(d);
    }
    return ListView(key: const Key('activities-calendar'), children: [
      for (final d in days) ...[
        Container(
          width: double.infinity,
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          child: Text(l.formatFullDate(d), style: Theme.of(context).textTheme.titleSmall),
        ),
        if ((byDay[d] ?? const []).isEmpty)
          const Padding(padding: EdgeInsets.fromLTRB(16, 6, 16, 6), child: Text('—'))
        else
          for (final a in byDay[d]!) ActivityTile(activity: a, onChanged: onChanged),
      ],
    ]);
  }
}
