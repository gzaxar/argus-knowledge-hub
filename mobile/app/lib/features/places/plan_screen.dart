import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/common.dart';

/// A floor plan: zoomed and moved with two fingers, the records placed on it as pins. Opened from a record
/// ([assetUid]), its pin is red, and a tap places the record there (asked first) — indoors, where GPS is weak,
/// this is how a unit is put where it is. A plan placed on the map gives the record its position too.
class PlanScreen extends ConsumerStatefulWidget {
  const PlanScreen({super.key, required this.planUid, this.assetUid});

  final String planUid;
  final String? assetUid;

  @override
  ConsumerState<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends ConsumerState<PlanScreen> {
  final _view = TransformationController();
  bool _fitted = false;
  bool _saving = false;

  @override
  void dispose() {
    _view.dispose();
    super.dispose();
  }

  Future<void> _tapped(PlanInfo plan, Offset at) async {
    final asset = widget.assetUid;
    if (asset == null || _saving) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Place it here?'),
        content: Text(plan.onMap
            ? 'On ${plan.ref.name}, at ${at.dx.round()}, ${at.dy.round()}. The plan is placed on the map: this gives it its '
                'position too.'
            : 'On ${plan.ref.name}, at ${at.dx.round()}, ${at.dy.round()}.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(key: const Key('plan-place-confirm'), onPressed: () => Navigator.pop(d, true), child: const Text('Place it')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final now = await ref.read(indoorProvider(asset).future).catchError((_) => const IndoorInfo());
      await ref.read(locationRepositoryProvider).placeOnPlan(asset,
          planUid: plan.ref.uid, x: double.parse(at.dx.toStringAsFixed(1)), y: double.parse(at.dy.toStringAsFixed(1)),
          placeUid: now.placeUid);
      ref.invalidate(planInfoProvider(widget.planUid));
      ref.invalidate(indoorProvider(asset));
      ref.invalidate(assetLocationProvider(asset));
      messenger.showSnackBar(const SnackBar(content: Text('Placed on the plan.')));
    } on Problem catch (p) {
      messenger.showSnackBar(SnackBar(content: Text(p.message)));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final info = ref.watch(planInfoProvider(widget.planUid));
    final image = ref.watch(planImageProvider(widget.planUid));
    final plan = info.value;
    return Scaffold(
      appBar: AppBar(title: Text(plan?.ref.name ?? 'Plan')),
      body: info.hasError || image.hasError
          ? ProblemView(info.error ?? image.error!, onRetry: () {
              ref.invalidate(planInfoProvider(widget.planUid));
              ref.invalidate(planImageProvider(widget.planUid));
            })
          : plan == null || image.value == null
              ? const Center(child: CircularProgressIndicator())
              : Column(children: [
                  ListTile(
                    dense: true,
                    title: Text([plan.placeName, plan.levelName].whereType<String>().join(' · ')),
                    subtitle: Text(widget.assetUid == null
                        ? '${plan.placed.length} placed on it'
                        : 'Tap where it is to place it there.'),
                  ),
                  if (_saving) const LinearProgressIndicator(),
                  Expanded(
                    child: LayoutBuilder(builder: (context, box) {
                      final w = plan.ref.width, h = plan.ref.height;
                      if (!_fitted && box.maxWidth > 0) {
                        final scale = (box.maxWidth / w) < (box.maxHeight / h) ? box.maxWidth / w : box.maxHeight / h;
                        _view.value = Matrix4.identity()..scaleByDouble(scale, scale, 1, 1);
                        _fitted = true;
                      }
                      final pinSize = 18.0 / (_view.value.getMaxScaleOnAxis().clamp(0.01, 100));
                      return InteractiveViewer(
                        key: const Key('plan-view'),
                        transformationController: _view,
                        constrained: false,
                        minScale: 0.01,
                        maxScale: 20,
                        boundaryMargin: const EdgeInsets.all(200),
                        onInteractionUpdate: (_) => setState(() {}),
                        child: GestureDetector(
                          key: const Key('plan-surface'),
                          onTapUp: (d) => _tapped(plan, d.localPosition),
                          child: SizedBox(
                            width: w,
                            height: h,
                            child: Stack(children: [
                              Positioned.fill(
                                  child: plan.mime == 'image/svg+xml'
                                      ? SvgPicture.memory(image.value!, fit: BoxFit.fill)
                                      : Image.memory(image.value!, fit: BoxFit.fill, gaplessPlayback: true)),
                              for (final p in plan.placed)
                                Positioned(
                                  key: Key('plan-pin-${p.uid}'),
                                  left: p.x - pinSize / 2,
                                  top: p.y - pinSize / 2,
                                  width: pinSize,
                                  height: pinSize,
                                  child: Tooltip(
                                    message: p.name,
                                    child: DecoratedBox(
                                      decoration: BoxDecoration(
                                          color: p.uid == widget.assetUid ? Colors.red : const Color(0xFF2563EB),
                                          shape: BoxShape.circle,
                                          border: Border.all(color: Colors.white, width: pinSize / 8)),
                                    ),
                                  ),
                                ),
                            ]),
                          ),
                        ),
                      );
                    }),
                  ),
                ]),
    );
  }
}
