import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { indoorApi, type PlanLayerId, type PlanSceneView } from "../../api/client";
import { usePlanImage } from "../../components/PlanView";
import { RACK, anchors, arc, bodyOf, drawnRelations, floorOf, relationColour, unitBox } from "../../lib/scene3d";
import { LAYER_COLOUR } from "./PlanLayersPage";

type Shown = "places" | "beamline" | "racks" | "fixed" | "devices" | "zones" | "paths";
const SHOWN: { id: Shown; label: string }[] = [
  { id: "places", label: "Rooms" }, { id: "racks", label: "Racks and units" }, { id: "beamline", label: "Beamline" },
  { id: "fixed", label: "Fixed plant" }, { id: "devices", label: "Other devices" }, { id: "zones", label: "Zones" },
  { id: "paths", label: "Cables and pipes" },
];
const UNIT_COLOURS = ["#334155", "#1d4ed8", "#047857", "#7c3aed", "#b45309", "#be123c", "#0e7490"];
const colourOfType = (t: string) => {
  let h = 0;
  for (const c of t) h = (h * 17 + c.charCodeAt(0)) >>> 0;
  return UNIT_COLOURS[h % UNIT_COLOURS.length];
};

interface Picked { uid: string; name: string; key: string | null; type: string; rack?: boolean; inRack?: string;
  /** A room or a zone: chosen only when nothing else is under the pointer, since everything stands inside one. */
  area?: boolean }

/** A simplified 3D view of a floor plan: the drawing on the floor, rooms as glass walls, racks with their units at
 *  their height, beamline, plant and devices; on request, the relations between them as arcs — all of them, some
 *  types, or only those of the record selected. Drag to turn, scroll to zoom, right-drag to move. */
export default function Plan3DPage() {
  const { uid = "" } = useParams();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["plan-scene", uid], queryFn: () => indoorApi.scene(uid), enabled: !!uid });
  const image = usePlanImage(uid);
  const [on, setOn] = useState<Set<Shown>>(new Set(["places", "racks", "beamline", "fixed", "devices"]));
  const [relationsOn, setRelationsOn] = useState(false);
  const [types, setTypes] = useState<Set<string> | null>(null);
  const [onlySelected, setOnlySelected] = useState(true);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [hover, setHover] = useState<{ text: string; x: number; y: number } | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const world = useRef<{ groups: Record<string, THREE.Group>; relations: THREE.Group; select: THREE.BoxHelper;
                         scene: THREE.Scene; byUid: Map<string, THREE.Object3D>; reset: () => void } | null>(null);

  const v = q.data;
  const allTypes = useMemo(() => [...new Set((v?.relations ?? []).map((r) => r.type))].sort(), [v]);
  const chosen = types ?? new Set(allTypes);

  // The scene: built once per plan.
  useEffect(() => {
    const el = host.current;
    if (!el || !v) return;
    const W = el.clientWidth, H = el.clientHeight;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#eef2f7");
    const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 5000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight("#ffffff", "#94a3b8", 1.6));
    const sun = new THREE.DirectionalLight("#ffffff", 1.4);
    sun.position.set(30, 60, 20);
    scene.add(sun);

    const [fw, fd] = floorOf(v, v.width_px, v.height_px);
    // The whole floor in view, from the south and above, whatever the shape of the window: the distance at which
    // its width fits the horizontal field and its depth the vertical one, with a margin.
    const reset = () => {
      const half = THREE.MathUtils.degToRad(camera.fov / 2);
      const across = (fw / 2) / (Math.tan(half) * camera.aspect);
      const deep = (fd / 2) / Math.tan(half);
      const dist = 1.18 * Math.max(across, deep * 0.75);
      controls.target.set(fw / 2, 0, fd / 2);
      camera.position.set(fw / 2, dist * 0.82, fd / 2 + dist * 0.57);   // about 55° above the floor
      controls.update();
    };
    reset();

    // The drawing on the floor.
    const floorMat = new THREE.MeshBasicMaterial({ color: "#ffffff", side: THREE.DoubleSide });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(fw, fd), floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(fw / 2, 0, fd / 2);
    scene.add(floor);
    if (image.data) {
      new THREE.TextureLoader().load(image.data, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
        floorMat.map = tex;
        floorMat.needsUpdate = true;
      });
    }

    const groups: Record<string, THREE.Group> = {};
    for (const s of SHOWN) {
      groups[s.id] = new THREE.Group();
      scene.add(groups[s.id]);
    }
    const byUid = new Map<string, THREE.Object3D>();
    const tag = (o: THREE.Object3D, p: Picked) => {
      o.userData = p;
      byUid.set(p.uid, o);
    };

    // Rooms as glass walls, zones as tinted floor, routes as lines just above it.
    for (const s of v.outlines) {
      const shape = new THREE.Shape(s.points.map(([x, y]) => {
        const [wx, wz] = floorOf(v, x, y);
        return new THREE.Vector2(wx, -wz);
      }));
      const room = s.layer === "places";
      const geo = new THREE.ExtrudeGeometry(shape, { depth: room ? 2.8 : 0.03, bevelEnabled: false });
      const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({
        color: room ? LAYER_COLOUR.places : LAYER_COLOUR.zones, transparent: true, opacity: room ? 0.06 : 0.22,
        depthWrite: false, side: THREE.DoubleSide }));
      mesh.rotation.x = -Math.PI / 2;
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 30),
        new THREE.LineBasicMaterial({ color: room ? "#0f766e" : "#a16207", transparent: true, opacity: 0.6 }));
      edges.rotation.x = -Math.PI / 2;
      const g = new THREE.Group();
      g.add(mesh, edges);
      tag(mesh, { uid: s.uid, name: s.name, key: s.key, type: s.type, area: true });
      groups[room ? "places" : "zones"].add(g);
    }
    for (const r of v.routes) {
      const pts = r.points.map(([x, y]) => {
        const [wx, wz] = floorOf(v, x, y);
        return new THREE.Vector3(wx, 0.08, wz);
      });
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: LAYER_COLOUR.paths }));
      tag(line, { uid: r.uid, name: r.name, key: r.key, type: r.type });
      groups.paths.add(line);
    }

    // Records standing on the plan; racks as cabinets with their units inside.
    const unitsOf = new Map<string, PlanSceneView["units"]>();
    for (const u of v.units) unitsOf.set(u.rack_uid, [...(unitsOf.get(u.rack_uid) ?? []), u]);
    for (const i of v.items) {
      const [x, z] = floorOf(v, i.x, i.y);
      const b = bodyOf(i);
      const rack = i.layer === "racks";
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(b.w, b.h, b.d), new THREE.MeshLambertMaterial({
        color: rack ? "#1e293b" : LAYER_COLOUR[i.layer as PlanLayerId], transparent: rack, opacity: rack ? 0.25 : 1,
        depthWrite: !rack }));
      mesh.position.set(x, rack ? RACK.base + b.h / 2 : b.y, z);
      tag(mesh, { uid: i.uid, name: i.name, key: i.key, type: i.type, rack });
      const g = new THREE.Group();
      g.add(mesh);
      if (rack) {
        const frame3 = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: "#0f172a" }));
        frame3.position.copy(mesh.position);
        g.add(frame3);
        for (const u of unitsOf.get(i.uid) ?? []) {
          const ub = unitBox(u);
          const zero = u.kind === "zero_u" || u.start_u == null;
          const box = new THREE.Mesh(new THREE.BoxGeometry(zero ? 0.05 : RACK.w - 0.08, ub.h - 0.004, zero ? 0.05 : 0.3),
            new THREE.MeshLambertMaterial({ color: colourOfType(u.type) }));
          box.position.set(x + (zero ? RACK.w / 2 - 0.06 : 0), ub.y, z + ub.dz);
          tag(box, { uid: u.uid, name: u.name, key: u.key, type: u.type, inRack: i.uid });
          g.add(box);
        }
      }
      groups[i.layer === "racks" ? "racks" : i.layer in groups ? i.layer : "devices"].add(g);
    }

    const relations = new THREE.Group();
    scene.add(relations);
    const select = new THREE.BoxHelper(new THREE.Object3D(), "#f59e0b");
    select.visible = false;
    scene.add(select);
    world.current = { groups, relations, select, scene, byUid, reset };

    // Picking: a click (not a drag) selects; hovering names what is under the pointer.
    const ray = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const hit = (ev: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(pointer, camera);
      const visible = (o: THREE.Object3D): boolean => o.visible && (!o.parent || visible(o.parent));
      const hits = ray.intersectObjects([...byUid.values()], false).filter((x) => visible(x.object) && x.object.userData.uid);
      return hits.find((x) => !x.object.userData.area) ?? hits[0];
    };
    let down: [number, number] | null = null;
    const onDown = (e: PointerEvent) => { down = [e.clientX, e.clientY]; };
    const onUp = (e: PointerEvent) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const h = hit(e);
      setPicked(h ? (h.object.userData as Picked) : null);
    };
    let frame = 0;
    const onMove = (e: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const h = hit(e);
        const r = el.getBoundingClientRect();
        setHover(h ? { text: `${h.object.userData.key || h.object.userData.name} · ${h.object.userData.type}`,
                       x: e.clientX - r.left, y: e.clientY - r.top } : null);
      });
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("pointermove", onMove);
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    ro.observe(el);
    let alive = true;
    const loop = () => {
      if (!alive) return;
      controls.update();
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    };
    loop();
    return () => {
      alive = false;
      ro.disconnect();
      cancelAnimationFrame(frame);
      controls.dispose();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose?.();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
      });
      floorMat.map?.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      world.current = null;
    };
  }, [v, image.data]);

  // Layers on and off.
  useEffect(() => {
    const w = world.current;
    if (!w) return;
    for (const s of SHOWN) w.groups[s.id].visible = on.has(s.id);
  }, [on, v, image.data]);

  // The selection and the relations drawn.
  useEffect(() => {
    const w = world.current;
    if (!w || !v) return;
    const o = picked ? w.byUid.get(picked.uid) : undefined;
    w.select.visible = !!o;
    if (o) w.select.setFromObject(o);
    for (const o of w.relations.children as THREE.Mesh[]) {
      o.geometry.dispose();
      (o.material as THREE.Material).dispose();
    }
    w.relations.clear();
    if (!relationsOn) return;
    const at = anchors(v);
    for (const r of drawnRelations(v, chosen, picked?.uid ?? null, onlySelected)) {
      const a = at.get(r.from), b = at.get(r.to);
      if (!a || !b) continue;
      const curve = new THREE.CatmullRomCurve3(arc(a, b).map((p) => new THREE.Vector3(...p)));
      w.relations.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 32, 0.05, 6, false),
        new THREE.MeshBasicMaterial({ color: relationColour(r.type) })));
    }
  }, [picked, relationsOn, chosen, onlySelected, v, image.data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.isLoading) return <p className="p-6 text-sm text-slate-500">Loading the plan…</p>;
  if (q.isError || !v) return <p className="p-6 text-sm text-red-600">The plan could not be loaded.</p>;

  const names = new Map<string, string>([...v.items, ...v.units, ...v.outlines, ...v.routes].map((x) => [x.uid, x.key || x.name]));
  const mine = picked ? v.relations.filter((r) => r.from === picked.uid || r.to === picked.uid) : [];
  const chip = (active: boolean) => `rounded-full border px-2.5 py-1 text-xs ${active ? "border-slate-400 bg-white text-slate-900" : "border-slate-200 bg-slate-50 text-slate-500"}`;
  const toggle = <T,>(set: Set<T>, x: T) => { const n = new Set(set); if (n.has(x)) n.delete(x); else n.add(x); return n; };

  return (
    <div className="flex flex-col gap-3 p-4 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{v.name} · 3D</h1>
          <p className="text-sm text-slate-600">
            <Link to={`/plans/${v.uid}`} className="text-indigo-700 hover:underline">Back to the plan</Link>
            {" · "}Drag to turn, scroll to zoom, right-drag to move.
            {!v.scale_known && <span className="text-amber-700"> The plan is not placed on the map: its scale is assumed.</span>}
          </p>
        </div>
        <button type="button" onClick={() => world.current?.reset()} className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50">Reset view</button>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="What to show">
        {SHOWN.map((s) => (
          <button key={s.id} type="button" aria-pressed={on.has(s.id)} onClick={() => setOn(toggle(on, s.id))} className={chip(on.has(s.id))}>{s.label}</button>
        ))}
        <button type="button" aria-pressed={relationsOn} onClick={() => setRelationsOn(!relationsOn)}
                className={`${chip(relationsOn)} font-medium`}>Relations {v.relations.length}</button>
      </div>
      {relationsOn && (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Relation types">
          <label className="mr-2 flex items-center gap-1 text-xs text-slate-700">
            <input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} />
            only those of the record selected
          </label>
          {allTypes.map((t) => (
            <button key={t} type="button" aria-pressed={chosen.has(t)} onClick={() => setTypes(toggle(chosen, t))} className={chip(chosen.has(t))}>
              <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: relationColour(t) }} />{t}
            </button>
          ))}
          {allTypes.length === 0 && <span className="text-xs text-slate-500">No relations between what this plan shows.</span>}
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-[1fr_18rem]">
        <div ref={host} className="relative h-[68vh] min-h-[22rem] overflow-hidden rounded border border-slate-200"
             role="img" aria-label={`3D view of ${v.name}`}>
          {hover && (
            <div className="pointer-events-none absolute z-10 rounded bg-slate-900/85 px-2 py-0.5 text-xs text-white"
                 style={{ left: hover.x + 12, top: hover.y + 12 }}>{hover.text}</div>
          )}
        </div>
        <aside className="space-y-2 text-sm">
          {!picked ? <p className="text-slate-500">Click a rack, a unit, a room or a device to see what it is and how it is related.</p> : (
            <section aria-label="Selected" className="rounded border border-slate-200 bg-white p-3">
              <Link to={`/assets/${picked.uid}`} className="font-medium text-indigo-700 hover:underline">{picked.key || picked.name}</Link>
              <div className="text-xs text-slate-500">{picked.name !== picked.key && picked.key ? `${picked.name} · ` : ""}{picked.type}</div>
              {picked.rack && <button type="button" onClick={() => navigate(`/racks/${picked.uid}`)} className="mt-2 text-xs text-indigo-700 underline">Open the rack</button>}
              {picked.inRack && <button type="button" onClick={() => navigate(`/racks/${picked.inRack}?unit=${picked.uid}`)} className="mt-2 text-xs text-indigo-700 underline">Open it in its rack</button>}
              {mine.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-slate-700">
                  {mine.map((r, k) => (
                    <li key={k}>
                      <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: relationColour(r.type) }} />
                      {r.from === picked.uid ? <>{r.type} <b>{names.get(r.to)}</b></> : <><b>{names.get(r.from)}</b> {r.type} it</>}
                    </li>
                  ))}
                </ul>
              )}
              {mine.length > 0 && !relationsOn && (
                <button type="button" onClick={() => setRelationsOn(true)} className="mt-2 text-xs text-indigo-700 underline">Show them in 3D</button>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
