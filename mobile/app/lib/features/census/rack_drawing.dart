import 'package:flutter/material.dart';

import '../../domain/census.dart';

/// The rack as surveyed so far: its units numbered from the bottom, each unit of the survey where the person put
/// it, two in the same unit in red. With [onPickU] a tap on a unit number puts the [current] unit there.
class RackDrawing extends StatelessWidget {
  const RackDrawing({super.key, required this.units, required this.items, this.current, this.onPickU, this.onTap});

  final int units;
  final List<CensusItem> items;
  final String? current;
  final void Function(int u)? onPickU;
  final void Function(CensusItem item)? onTap;

  /// Who takes each unit of a face; a unit taken twice is a clash.
  static Map<int, List<CensusItem>> occupancy(List<CensusItem> items, String face) {
    final out = <int, List<CensusItem>>{};
    for (final i in items) {
      final s = i.span;
      final f = (i.value('face') ?? 'front').toString();
      if (s == null || i.decision == 'skip' || (f != face && f != 'both')) continue;
      for (var u = s.from; u <= s.to; u++) {
        (out[u] ??= []).add(i);
      }
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final front = occupancy(items, 'front');
    final rear = occupancy(items, 'rear');
    const rowH = 18.0;
    Widget cell(Map<int, List<CensusItem>> taken, int u) {
      final here = taken[u] ?? const [];
      final clash = here.length > 1;
      final mine = here.any((i) => i.id == current);
      final first = here.isEmpty ? null : here.first;
      final starts = first != null && first.span!.to == u;
      return GestureDetector(
        onTap: first != null && onTap != null ? () => onTap!(first) : null,
        child: Container(
          height: rowH,
          decoration: BoxDecoration(
            color: clash
                ? scheme.errorContainer
                : mine
                    ? scheme.primaryContainer
                    : here.isEmpty
                        ? null
                        : scheme.secondaryContainer,
            border: Border(bottom: BorderSide(color: scheme.outlineVariant, width: 0.5)),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 4),
          alignment: Alignment.centerLeft,
          child: starts
              ? Text(clash ? here.map((i) => i.title).join(' / ') : first.title,
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11))
              : null,
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Column(children: [
        const Row(children: [
          SizedBox(width: 34),
          Expanded(child: Text('Front', style: TextStyle(fontSize: 12))),
          SizedBox(width: 8),
          Expanded(child: Text('Rear', style: TextStyle(fontSize: 12))),
        ]),
        Column(key: const Key('census-rack-drawing'), children: [
          for (var u = units; u >= 1; u--) // U1 at the bottom
            Row(children: [
              SizedBox(
                width: 34,
                child: InkWell(
                  key: Key('census-u-$u'),
                  onTap: onPickU == null ? null : () => onPickU!(u),
                  child: Text('$u', textAlign: TextAlign.right,
                      style: TextStyle(fontSize: 11, color: onPickU == null ? null : scheme.primary)),
                ),
              ),
              const SizedBox(width: 4),
              Expanded(child: cell(front, u)),
              const SizedBox(width: 8),
              Expanded(child: cell(rear, u)),
            ]),
        ]),
      ]),
    );
  }
}
