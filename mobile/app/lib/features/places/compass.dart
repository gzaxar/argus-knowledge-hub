import 'dart:io' show Platform;
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_compass/flutter_compass.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geomag/geomag.dart';

/// Where the top of the phone points, in degrees clockwise from true north, and how far off the phone says it
/// may be (null: it does not say).
class Heading {
  const Heading(this.trueDeg, this.accuracyDeg);

  final double trueDeg;
  final double? accuracyDeg;

  /// Too unsure to steer by: the phone asks to be calibrated (or says nothing).
  bool get poor => accuracyDeg == null || accuracyDeg! > 30;
}

/// The phone's heading near ([lat], [lon]) — a stream of [Heading], null while there is none. iOS reports true
/// north already; Android reports magnetic north, turned to true north here by the magnetic declination there
/// (the World Magnetic Model; about 3–4° east in Italy). No compass on the phone: one null and nothing more.
typedef HeadingSource = Stream<Heading?> Function({double? lat, double? lon});

Stream<Heading?> deviceHeading({double? lat, double? lon}) {
  final events = FlutterCompass.events;
  if (events == null) return Stream.value(null);
  final declination =
      Platform.isAndroid && lat != null && lon != null ? GeoMag().calculate(lat, lon).dec : 0.0;
  return events.map((e) {
    final h = e.heading;
    // An iPhone without location access has no true heading: it reports -1.
    if (h == null || h.isNaN || (Platform.isIOS && h < 0)) return null;
    return Heading(((h + declination) % 360 + 360) % 360, e.accuracy?.abs());
  });
}

/// Replaced in tests with a fixed heading.
final headingSourceProvider = Provider<HeadingSource>((ref) => deviceHeading);

/// A plan's dial: true north as the drawing has it ([northDeg], clockwise from the plan's top) and, with a
/// heading, the way the phone faces on the plan. Read from the plan as it is shown: turned with the phone
/// ([turnedDeg]), the arrows turn with it.
class PlanCompass extends StatelessWidget {
  const PlanCompass({super.key, required this.northDeg, this.heading, this.turnedDeg = 0});

  final double northDeg;
  final Heading? heading;
  final double turnedDeg;

  @override
  Widget build(BuildContext context) {
    final facing = heading == null ? null : northDeg + heading!.trueDeg;
    double rad(double deg) => (deg - turnedDeg) * math.pi / 180;
    return Container(
      width: 64,
      height: 64,
      decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.92),
          shape: BoxShape.circle,
          border: Border.all(color: const Color(0xFFCBD5E1)),
          boxShadow: const [BoxShadow(blurRadius: 3, color: Color(0x33000000))]),
      child: Stack(alignment: Alignment.center, children: [
        Transform.rotate(
          key: const Key('plan-north'),
          angle: rad(northDeg),
          child: const Column(mainAxisSize: MainAxisSize.min, children: [
            Text('N', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Color(0xFFDC2626))),
            Icon(Icons.navigation, size: 22, color: Color(0xFFDC2626)),
            SizedBox(height: 22),
          ]),
        ),
        if (facing != null)
          Transform.rotate(
            key: const Key('plan-facing'),
            angle: rad(facing),
            child: Icon(Icons.arrow_upward, size: 26,
                color: heading!.poor ? const Color(0xFF94A3B8) : const Color(0xFF2563EB)),
          ),
      ]),
    );
  }
}
