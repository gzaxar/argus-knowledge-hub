import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../domain/models.dart';

/// The map's background tiles: OpenStreetMap unless the build names the installation's own tile server
/// (`--dart-define=ARGUS_MAP_TILES=https://…/{z}/{x}/{y}.png`), as the web does. Null draws no tiles (tests).
final mapTilesProvider = Provider<String?>(
    (_) => const String.fromEnvironment('ARGUS_MAP_TILES', defaultValue: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'));

/// LNF, Frascati: where a map opens before it knows better.
const lnf = LatLng(41.8217, 12.6726);

const _layerColours = {'equipment': Color(0xFF2563EB), 'places': Color(0xFF059669)};
Color layerColour(String? layer) => _layerColours[layer] ?? const Color(0xFF64748B);

/// The tiles and their attribution (OpenStreetMap's terms ask for it), when there are tiles.
List<Widget> baseLayers(WidgetRef ref) {
  final tiles = ref.watch(mapTilesProvider);
  if (tiles == null) return const [];
  return [
    TileLayer(urlTemplate: tiles, userAgentPackageName: 'it.infn.argus.field', maxZoom: 20),
    const RichAttributionWidget(attributions: [TextSourceAttribution('OpenStreetMap contributors')]),
  ];
}

/// Shapes as map layers — outlines under routes under positions, so every point stays tappable — each tap
/// handed to [onTap] with its feature.
List<Widget> shapeLayers<T extends Object>(
  List<({PlaceShape shape, Color colour, T value})> items, {
  void Function(T value)? onTap,
  LayerHitNotifier<T>? polygonHits,
  LayerHitNotifier<T>? lineHits,
}) {
  Widget tappable(Widget layer, LayerHitNotifier<T>? hits) => onTap == null || hits == null
      ? layer
      : GestureDetector(
          onTap: () {
            final hit = hits.value?.hitValues;
            if (hit != null && hit.isNotEmpty) onTap(hit.first);
          },
          child: layer);
  return [
    tappable(
        PolygonLayer<T>(hitNotifier: polygonHits, polygons: [
          for (final i in items)
            for (final area in i.shape.areas)
              Polygon<T>(
                  points: area.first,
                  holePointsList: area.length > 1 ? area.sublist(1) : null,
                  color: i.colour.withValues(alpha: 0.15),
                  borderColor: i.colour,
                  borderStrokeWidth: 2,
                  hitValue: i.value),
        ]),
        polygonHits),
    tappable(
        PolylineLayer<T>(hitNotifier: lineHits, polylines: [
          for (final i in items)
            for (final line in i.shape.lines)
              Polyline<T>(points: line, color: i.colour, strokeWidth: 4, hitValue: i.value),
        ]),
        lineHits),
    MarkerLayer(markers: [
      for (final i in items)
        for (final p in i.shape.points)
          Marker(
            point: p,
            width: 28,
            height: 28,
            child: GestureDetector(
              onTap: onTap == null ? null : () => onTap(i.value),
              child: Center(
                child: Container(
                  width: 16,
                  height: 16,
                  decoration: BoxDecoration(
                      color: i.colour, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)),
                ),
              ),
            ),
          ),
    ]),
  ];
}

/// The camera that shows all these points (one point: close in around it).
MapOptions fittedOptions(List<LatLng> points, {double fallbackZoom = 16}) {
  if (points.length > 1 && LatLngBounds.fromPoints(points).north != LatLngBounds.fromPoints(points).south) {
    return MapOptions(
        initialCameraFit: CameraFit.bounds(bounds: LatLngBounds.fromPoints(points), padding: const EdgeInsets.all(24),
            maxZoom: 19),
        interactionOptions: const InteractionOptions(flags: InteractiveFlag.none));
  }
  return MapOptions(
      initialCenter: points.isEmpty ? lnf : points.first,
      initialZoom: points.isEmpty ? fallbackZoom : 18,
      interactionOptions: const InteractionOptions(flags: InteractiveFlag.none));
}
