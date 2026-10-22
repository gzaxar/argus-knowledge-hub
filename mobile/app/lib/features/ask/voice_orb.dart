import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'voice_turns.dart';

/// The hands-free conversation's luminous core: what ARGUS is doing, shown by movement and shape as well as
/// colour, with the state in words beside it (the caller's label) for everyone and for screen readers.
///
/// - idle: a faint glow breathing slowly;
/// - listening: rings that follow the microphone's level (a steady pulse where the phone reports none);
/// - processing: traces of light running in towards the core, turning slowly — moving, not stuck;
/// - speaking: waves leaving the core, each spoken word adding a beat;
/// - error: the core takes an angular shape and a warm colour, briefly, then holds still.
///
/// With the system's reduced motion on, each state is drawn still, with an icon. The animation runs only while the
/// orb is on screen: its ticker follows [TickerMode], which the app's tabs and covered pages switch off.
class VoiceOrb extends StatefulWidget {
  const VoiceOrb({super.key, required this.state, this.level = 0, this.words = 0, this.size = 168, this.label});

  final TurnState state;
  final double level;
  final int words;
  final double size;
  final String? label;

  @override
  State<VoiceOrb> createState() => _VoiceOrbState();
}

class _VoiceOrbState extends State<VoiceOrb> with TickerProviderStateMixin {
  late final AnimationController _loop = AnimationController(vsync: this, duration: const Duration(seconds: 6));
  // A state change: the shape and colour move to the new state's (and the error's shape settles) in 400 ms.
  late final AnimationController _change =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 400), value: 1);
  late final AnimationController _beat =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 260), value: 0);
  TurnState? _from;
  double _level = 0;
  bool _reduced = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduced = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    _run();
  }

  @override
  void didUpdateWidget(VoiceOrb old) {
    super.didUpdateWidget(old);
    if (old.state != widget.state) {
      _from = old.state;
      _change.forward(from: _reduced ? 1 : 0);
      _run();
    }
    if (widget.words != old.words && widget.state == TurnState.speaking && !_reduced) _beat.forward(from: 0);
    // The level, smoothed: rings that jump at every sample tire the eye.
    _level = _level * 0.6 + widget.level.clamp(0.0, 1.0) * 0.4;
  }

  /// The loop runs only where something moves: not in the error's still state, not with reduced motion.
  void _run() {
    final still = _reduced || widget.state == TurnState.error;
    if (still) {
      _loop.stop();
    } else if (!_loop.isAnimating) {
      _loop.repeat();
    }
  }

  @override
  void dispose() {
    _loop.dispose();
    _change.dispose();
    _beat.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Semantics(
      label: widget.label,
      liveRegion: true,
      child: SizedBox.square(
        dimension: widget.size,
        child: Stack(alignment: Alignment.center, children: [
          RepaintBoundary(
            child: AnimatedBuilder(
              animation: Listenable.merge([_loop, _change, _beat]),
              builder: (_, _) => CustomPaint(
                size: Size.square(widget.size),
                painter: OrbPainter(
                  state: widget.state,
                  from: _from,
                  t: _loop.value,
                  change: _change.value,
                  level: _level,
                  beat: 1 - _beat.value,
                  reduced: _reduced,
                  dark: dark,
                ),
              ),
            ),
          ),
          if (_reduced)
            Icon(_icon(widget.state), size: widget.size * 0.2, color: Colors.white.withValues(alpha: 0.9)),
        ]),
      ),
    );
  }

  static IconData _icon(TurnState s) => switch (s) {
        TurnState.idle => Icons.pause_circle_outline,
        TurnState.listening => Icons.mic,
        TurnState.processing => Icons.manage_search,
        TurnState.speaking => Icons.graphic_eq,
        TurnState.error => Icons.error_outline,
      };
}

/// The orb's colours: a cool palette for the working states, a warm one for a problem.
Color orbColor(TurnState s) => switch (s) {
      TurnState.idle => const Color(0xFF5B7DB1),
      TurnState.listening => const Color(0xFF22B8CF),
      TurnState.processing => const Color(0xFF7C6CF2),
      TurnState.speaking => const Color(0xFF20C997),
      TurnState.error => const Color(0xFFF08C00),
    };

class OrbPainter extends CustomPainter {
  OrbPainter({
    required this.state,
    required this.from,
    required this.t,
    required this.change,
    required this.level,
    required this.beat,
    required this.reduced,
    required this.dark,
  });

  final TurnState state;
  final TurnState? from;
  final double t; // 0–1, the slow loop
  final double change; // 0–1, the move from the previous state
  final double level; // 0–1, the microphone
  final double beat; // 1 at a spoken word, fading to 0
  final bool reduced;
  final bool dark;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.shortestSide * 0.24;
    final color = Color.lerp(orbColor(from ?? state), orbColor(state), Curves.easeOut.transform(change))!;
    final wave = reduced ? 0.0 : math.sin(t * 2 * math.pi);

    // The halo: a wide, soft glow, stronger while something is happening.
    final glow = switch (state) { TurnState.idle => 0.18, TurnState.error => 0.22, _ => 0.32 };
    canvas.drawCircle(
        c,
        r * 2,
        Paint()
          ..shader = RadialGradient(colors: [color.withValues(alpha: glow), color.withValues(alpha: 0)])
              .createShader(Rect.fromCircle(center: c, radius: r * 2)));

    switch (state) {
      case TurnState.listening:
        _rings(canvas, c, r, color);
      case TurnState.processing:
        _traces(canvas, c, r, color);
      case TurnState.speaking:
        _waves(canvas, c, r, color);
      case TurnState.idle || TurnState.error:
        break;
    }

    // The core: round while all is well; angular, still, for a problem.
    final breath = switch (state) {
      TurnState.idle => 1 + 0.03 * wave,
      TurnState.listening => 1 + 0.06 * level,
      TurnState.speaking => 1 + 0.07 * beat,
      TurnState.processing => 1 + 0.02 * wave,
      TurnState.error => 1.0,
    };
    final core = r * breath;
    final shader = RadialGradient(
      colors: [Colors.white.withValues(alpha: 0.95), color, color.withValues(alpha: 0.65)],
      stops: const [0, 0.55, 1],
    ).createShader(Rect.fromCircle(center: c, radius: core));
    final paint = Paint()..shader = shader;
    if (state == TurnState.error) {
      // A shudder as the problem arrives (the move's first moments), then a still hexagon.
      final shake = reduced ? 0.0 : math.sin(change * math.pi * 3) * (1 - change) * 0.12;
      canvas.drawPath(_polygon(c, core, 6, shake), paint);
    } else {
      canvas.drawCircle(c, core, paint);
    }
    canvas.drawCircle(
        c,
        core,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2
          ..color = Colors.white.withValues(alpha: dark ? 0.35 : 0.55));
  }

  /// Listening: three rings, wider as the voice gets louder; a regular pulse when there is no level to follow.
  void _rings(Canvas canvas, Offset c, double r, Color color) {
    for (var i = 0; i < 3; i++) {
      final phase = reduced ? 0.5 : (t * 3 + i / 3) % 1;
      final reach = level > 0.02 ? 0.25 + level * 0.75 : 0.45 + 0.15 * math.sin(phase * 2 * math.pi);
      final radius = r * (1.15 + reach * (0.35 + i * 0.22));
      canvas.drawCircle(
          c,
          radius,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2.2 - i * 0.5
            ..color = color.withValues(alpha: 0.55 - i * 0.14));
    }
  }

  /// Processing: twelve traces of light on spokes that turn slowly, each running in to the core.
  void _traces(Canvas canvas, Offset c, double r, Color color) {
    const n = 12;
    for (var i = 0; i < n; i++) {
      final angle = 2 * math.pi * i / n + (reduced ? 0 : t * 2 * math.pi / 3);
      final p = reduced ? 0.5 : (t * 4 + i / n) % 1; // 0 far out, 1 at the core
      final outer = r * (2.0 - 0.95 * p);
      final inner = outer - r * 0.22;
      final dir = Offset(math.cos(angle), math.sin(angle));
      canvas.drawLine(
          c + dir * outer,
          c + dir * inner,
          Paint()
            ..strokeWidth = 2.4
            ..strokeCap = StrokeCap.round
            ..color = color.withValues(alpha: 0.15 + 0.7 * p));
    }
  }

  /// Speaking: waves leaving the core and fading as they spread; a spoken word adds a bright ring.
  void _waves(Canvas canvas, Offset c, double r, Color color) {
    for (var i = 0; i < 3; i++) {
      final p = reduced ? 0.35 : (t * 3 + i / 3) % 1;
      canvas.drawCircle(
          c,
          r * (1.05 + p * 0.95),
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2.5 * (1 - p) + 0.5
            ..color = color.withValues(alpha: 0.6 * (1 - p)));
    }
    if (beat > 0) {
      canvas.drawCircle(
          c,
          r * (1.1 + 0.25 * (1 - beat)),
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 3
            ..color = Colors.white.withValues(alpha: 0.45 * beat));
    }
  }

  Path _polygon(Offset c, double radius, int sides, double shake) {
    final path = Path();
    for (var i = 0; i <= sides; i++) {
      final a = -math.pi / 2 + 2 * math.pi * i / sides;
      final rr = radius * (1 + (i.isEven ? shake : -shake));
      final p = c + Offset(math.cos(a), math.sin(a)) * rr;
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    return path..close();
  }

  @override
  bool shouldRepaint(OrbPainter o) =>
      o.state != state || o.t != t || o.change != change || o.level != level || o.beat != beat || o.reduced != reduced ||
      o.dark != dark || o.from != from;
}
