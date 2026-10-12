import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../widgets/common.dart';

/// Locations observed in the field that disagree with the approved one (or where there is none): a person
/// accepts one — it becomes the record's location, the old one kept — or rejects it.
class LocationReviewsScreen extends ConsumerWidget {
  const LocationReviewsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(locationReviewsProvider);
    Future<void> decide(int id, bool accept) async {
      try {
        await ref.read(locationRepositoryProvider).decide(id, accept: accept);
      } on Problem catch (p) {
        if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(p.message)));
      }
      ref.invalidate(locationReviewsProvider);
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Locations to review')),
      body: r.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(locationReviewsProvider)),
        data: (items) => items.isEmpty
            ? const Center(child: Text('Nothing to review.'))
            : ListView(children: [
                for (final o in items)
                  Card(
                    key: Key('location-review-${o.id}'),
                    margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        InkWell(
                          onTap: o.record == null ? null : () => context.push(o.record!.route),
                          child: Text(o.record?.title ?? 'Record', style: Theme.of(context).textTheme.titleMedium),
                        ),
                        const SizedBox(height: 4),
                        Text('Seen at ${o.latitude.toStringAsFixed(6)}, ${o.longitude.toStringAsFixed(6)}'
                            '${o.accuracy == null ? '' : ' (±${o.accuracy!.round()} m)'}'
                            '${o.observedBy == null ? '' : ' by ${o.observedBy}'}'
                            '${o.at == null ? '' : ', ${formatWhenDate(o.at)}'}'),
                        Text(o.approved == null
                            ? 'It has no location yet.'
                            : '${o.distance?.round() ?? '?'} m from its approved location '
                                '(${o.approved!.latitude.toStringAsFixed(6)}, ${o.approved!.longitude.toStringAsFixed(6)}).'),
                        Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                          TextButton(onPressed: () => decide(o.id, false), child: const Text('Reject')),
                          FilledButton(
                              key: Key('location-accept-${o.id}'),
                              onPressed: () => decide(o.id, true),
                              child: const Text('Accept')),
                        ]),
                      ]),
                    ),
                  ),
              ]),
      ),
    );
  }
}
