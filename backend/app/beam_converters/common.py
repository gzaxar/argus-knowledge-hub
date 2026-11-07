"""What every converter needs: a safe expression evaluator, beam-line expansion, the survey, the guess of a
ring from its bends, and the assembly of a canonical document from placed elements."""
from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Callable, Optional

from app.beam_converters import ConversionError, Options

FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
         "acos": math.acos, "atan": math.atan, "atan2": math.atan2, "exp": math.exp, "log": math.log,
         "log10": math.log10, "abs": abs, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
         "floor": math.floor, "ceil": math.ceil, "round": round}
CONSTANTS = {"pi": math.pi, "twopi": 2 * math.pi, "e": math.e, "degrad": 180 / math.pi, "raddeg": math.pi / 180,
             "clight": 299792458.0, "emass": 0.51099895e-3, "pmass": 0.93827208816, "nmass": 0.93956542052,
             "mumass": 0.1056583755, "qelect": 1.602176634e-19}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod}


class Evaluator:
    """Arithmetic with named variables, evaluated lazily (MAD-X `:=` is deferred) and never with eval():
    only numbers, names, + - * / ^, unary minus and the functions above."""

    def __init__(self, resolve_attr: Optional[Callable[[str, str], Optional[float]]] = None):
        self.exprs: dict[str, str] = {}
        self.resolve_attr = resolve_attr
        self._busy: set = set()

    def define(self, name: str, expr: str) -> None:
        self.exprs[name.lower()] = expr

    def var(self, name: str) -> float:
        name = name.lower()
        if name in CONSTANTS and name not in self.exprs:
            return CONSTANTS[name]
        if name not in self.exprs:
            return 0.0                          # MAD-X: an undefined variable is zero
        if name in self._busy:
            raise ConversionError(f"the variable {name} is defined in terms of itself")
        self._busy.add(name)
        try:
            return self.eval(self.exprs[name])
        finally:
            self._busy.discard(name)

    def eval(self, text) -> float:
        if isinstance(text, (int, float)):
            return float(text)
        src = str(text).strip()
        if not src:
            return 0.0
        src = re.sub(r"(\w+)->(\w+)", lambda m: f"__attr__{m.group(1)}__{m.group(2)}", src).replace("^", "**")
        try:
            node = ast.parse(src, mode="eval").body
        except SyntaxError as e:
            raise ConversionError(f"cannot read the expression {text!r}") from e
        return float(self._node(node))

    def _node(self, n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id.startswith("__attr__") and self.resolve_attr:
                element, attr = n.id[len("__attr__"):].split("__", 1)
                return self.resolve_attr(element, attr) or 0.0
            return self.var(n.id)
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](self._node(n.left), self._node(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = self._node(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id.lower() in FUNCS:
            return FUNCS[n.func.id.lower()](*[self._node(a) for a in n.args])
        raise ConversionError(f"unsupported expression: {ast.dump(n)[:80]}")


def split_top(text: str, sep: str = ",") -> list[str]:
    """Split at `sep` outside brackets and quotes."""
    out, depth, cur, quote = [], 0, [], None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return [x.strip() for x in out]


def expand_line(name: str, lines: dict[str, list[str]], depth: int = 0) -> list[str]:
    """A LINE's members, expanded: `2*X` repeats, `-X` reverses, `(A, B)` groups, nested lines recursively."""
    if depth > 50:
        raise ConversionError(f"the line {name} contains itself")
    out: list[str] = []
    for item in lines[name]:
        out += _expand_item(item.strip(), lines, depth)
    return out


def _expand_item(item: str, lines: dict, depth: int) -> list[str]:
    if not item:
        return []
    m = re.match(r"^(\d+)\s*\*\s*(.+)$", item)
    if m:
        return _expand_item(m.group(2), lines, depth) * int(m.group(1))
    if item.startswith("-"):
        return list(reversed(_expand_item(item[1:].strip(), lines, depth)))
    if item.startswith("(") and item.endswith(")"):
        return [x for part in split_top(item[1:-1]) for x in _expand_item(part, lines, depth)]
    key = item.lower()
    if key in lines:
        return expand_line(key, lines, depth + 1)
    return [key]


# --------------------------------------------------------------------------- placed elements → canonical

NAME_HINTS = [  # (prefix of the element name, kind) — only when the simulator's class cannot say it
    (r"^(kck|kick|kik)", "kicker"), (r"^(sep|spt|sept)", "septum"), (r"^(bpm|bps|bpm_)", "bpm"),
    (r"^(scr|flg|yag|otr)", "screen"),
]
# A marker is how a lattice places what the simulation does not compute — a pump, a valve, a gauge — and the
# beam model keeps it: MAD-X is one of the formats it reads, not the measure of what is on the beam line.
# Its name says what it is, when it follows the usual conventions; otherwise it stays a marker.
MARKER_HINTS = [
    (r"^(vpi|vpu|sip|igp|tmp|ngp|pmp|pump|ionp|vip)", "pump_port"),
    (r"^(vg|gauge|pig)", "gauge_port"),
    (r"^(fv|vfv|fast_?valve)", "fast_valve"),
    (r"^(vvs|vvg|vlv|valve|gv|vv)", "gate_valve"),
    (r"^(bel|blw|bellow)", "bellows"),
    (r"^flange", "flange"),
    (r"^(win|vwin)", "vacuum_window"),
    *NAME_HINTS,
]
OBSERVES = {"bpm": ["beam.position.x", "beam.position.y"], "screen": ["beam.size.x", "beam.size.y"]}


@dataclass
class Placed:
    """One element where the line puts it: its name in the file, normalised kind, entry `s`, and parameters.
    `family` is the definition it was made from when the format says (MAD-X `QF1: QF`); `location` is where
    the file defines it (file:line), when known."""
    name: str
    kind: str
    s: float
    length: float
    native_type: str
    native: dict
    physics: dict = field(default_factory=dict)
    optics: dict = field(default_factory=dict)
    capabilities: Optional[list] = None
    family: Optional[str] = None
    location: Optional[str] = None
    component: dict = field(default_factory=dict)      # more v2 component fields: boundaries, aliases…
    label: Optional[str] = None                        # its label in the file, when not its name


def hint(name: str, kind: str, options: Options) -> str:
    if not options.name_hints or kind not in ("generic", "corrector", "dipole", "generic_monitor", "marker"):
        return kind
    for pattern, k in (MARKER_HINTS if kind == "marker" else NAME_HINTS):
        if re.match(pattern, name.lower()):
            return k
    return kind


def survey(placed: list[Placed], total: Optional[float] = None) -> tuple[list[dict], dict]:
    """The reference trajectory in the horizontal plane, from lengths and bend angles alone: each element's
    entry point and heading (x, y in m, yaw in rad), starting at the origin heading along +x. Returns the
    geometries and where the path ends, so a ring's closure can be checked."""
    x = y = yaw = 0.0
    pos = 0.0
    out = []

    def advance(dist: float, angle: float = 0.0):
        nonlocal x, y, yaw
        if dist <= 0:
            return
        if abs(angle) > 1e-12:
            r = dist / angle
            x += r * (math.sin(yaw + angle) - math.sin(yaw))
            y -= r * (math.cos(yaw + angle) - math.cos(yaw))
            yaw += angle
        else:
            x += dist * math.cos(yaw)
            y += dist * math.sin(yaw)

    for p in placed:
        advance(p.s - pos)
        pos = max(pos, p.s)
        out.append({"x": round(x, 6), "y": round(y, 6), "yaw": round(yaw, 9)})
        advance(p.length, float(p.physics.get("angle") or 0.0) if p.kind == "dipole" else 0.0)
        pos = p.s + p.length
    if total is not None:
        advance(total - pos)
    return out, {"x": x, "y": y, "yaw": yaw}


def total_bend(placed: list[Placed]) -> float:
    return sum(float(p.physics.get("angle") or 0.0) for p in placed if p.kind == "dipole")


def is_ring(placed: list[Placed]) -> bool:
    return abs(abs(total_bend(placed)) - 2 * math.pi) < 0.01


def build(placed: list[Placed], *, source: str, filename: str, options: Options, line_name: str,
          total_length: Optional[float], beam: dict, simulator_version: Optional[str] = None,
          keep_order_ids: bool = False) -> dict:
    """A canonical document from the placed elements: one system, one path, one design dataset carrying `s`,
    the survey, the normalised physics, any optics, and the simulator's own type and parameters whole."""
    if not placed:
        raise ConversionError(f"{filename}: no elements on the beam line {line_name}")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", PurePath(filename or "model").stem).strip("-") or "model"
    model_id = options.model_id or stem.lower()
    ring = options.topology == "closed" or (options.topology == "auto" and is_ring(placed))
    geometry, end = survey(placed, total_length)
    counts: dict[str, int] = {}
    for p in placed:
        counts[p.name.upper()] = counts.get(p.name.upper(), 0) + 1
    seen: dict[str, int] = {}
    elements, values, order = [], {}, []
    for p, g in zip(placed, geometry):
        base = p.name.upper()
        seen[base] = seen.get(base, 0) + 1
        ident = base if counts[base] == 1 or seen[base] == 1 else f"{base}#{seen[base]}"
        el = {"id": ident, "type": p.kind, "native": {"source": source, "type": p.native_type}}
        if p.capabilities is not None:
            el["capabilities"] = p.capabilities
        if p.kind in OBSERVES:
            el["observes"] = OBSERVES[p.kind]
        elements.append(el)
        order.append(ident)
        values[ident] = {"s": round(p.s, 9), "geometry": g, "physics": {"length": p.length, **p.physics},
                         **({"optics": p.optics} if p.optics else {}),
                         "native": {"source": source, "type": p.native_type, "parameters": p.native,
                                    **({"name": p.label} if p.label else {})}}
    system_id = options.system_id or line_name.lower()
    kind = options.system_kind or ("Storage ring" if ring else "Other")
    species = options.species or beam.get("species")
    params = {k: v for k, v in {"species": species, "charge": beam.get("charge"),
                                "reference_energy": options.reference_energy or beam.get("reference_energy"),
                                "reference_momentum": beam.get("reference_momentum"),
                                "rest_mass": beam.get("rest_mass")}.items() if v is not None}
    length = total_length if total_length is not None else (placed[-1].s + placed[-1].length)
    closure = math.hypot(end["x"], end["y"])
    v1 = {
        "format": "argus.beam-model/1",
        "model": {k: v for k, v in {"id": model_id, "name": options.model_name or f"{line_name.upper()} ({PurePath(filename).name})",
                                    "source": f"{source} file {PurePath(filename).name}", "version": options.version,
                                    "simulator": source}.items() if v},
        "systems": [{"id": system_id, "name": options.model_name or line_name.upper(), "kind": kind,
                     "beams": [{"id": "beam", "kind": "particle", "parameters": params}] if params else []}],
        "paths": [{"id": line_name.lower(), "name": line_name.upper(), "system": system_id,
                   "topology": "closed" if ring else "open", "elements": order, "length": round(length, 9)}],
        "elements": elements,
        "datasets": [{"id": f"{line_name.lower()}-design", "name": f"{line_name.upper()} from {PurePath(filename).name}",
                      "kind": "design", "path": line_name.lower(), "simulator": source,
                      **({"simulator_version": simulator_version} if simulator_version else {}),
                      "values": values}],
        "conversion": {"converter": source, "file": PurePath(filename).name, "elements": len(order),
                       "total_bend": round(total_bend(placed), 9), "ring": ring,
                       "survey_closure_m": round(closure, 6) if ring else None},
    }
    return v1 if options.output == "1" else to_v2(v1, placed, source=source, filename=filename)


def _by_id(existing: list, incoming: list) -> None:
    known = {x.get("id") for x in existing}
    existing.extend(x for x in incoming if x.get("id") not in known)


def merge_paths(parts: list[dict], *, filename: str) -> dict:
    """One model from documents converted from one file, each with a single path: their paths and datasets side
    by side and each component once, however many paths place it. What the file says differently about one
    component is reported: the type in `conflicts` (the first stays), a value in `differs` (each dataset keeps
    its own, so a magnet can bend one way on the way in and the other on the way out)."""
    doc = parts[0]
    reports = [p.pop("conversion", {}) for p in parts]
    types = {c["id"]: c.get("type") for c in doc["components"]}
    conflicts: list[dict] = []
    for part in parts[1:]:
        for c in part["components"]:
            if c["id"] in types and c.get("type") != types[c["id"]]:
                conflicts.append({"component": c["id"], "kept": types[c["id"]], "also": c.get("type"),
                                  "path": part["paths"][0]["id"]})
        for key in ("systems", "components", "definitions", "observables", "connections"):
            if part.get(key):
                doc[key] = doc.get(key) or []
                _by_id(doc[key], part[key])
                types = {c["id"]: c.get("type") for c in doc["components"]}
        doc["paths"].extend(part["paths"])
        doc["datasets"].extend(part["datasets"])
    seen: dict[str, dict[str, dict]] = {}
    for d in doc["datasets"]:
        for ident, values in d["values"].items():
            for key, value in (values.get("physics") or {}).items():
                seen.setdefault(ident, {}).setdefault(key, {})[d["path"]] = value
    differs = [{"component": ident, "parameter": key, "values": by_path}
               for ident, parameters in sorted(seen.items()) for key, by_path in sorted(parameters.items())
               if len({json_key(v) for v in by_path.values()}) > 1]
    doc["conversion"] = {
        "converter": reports[0].get("converter"), "file": PurePath(filename).name, "elements": len(doc["components"]),
        "placements": sum(r.get("elements", 0) for r in reports),
        "total_bend": sum(r.get("total_bend", 0.0) for r in reports), "ring": False, "survey_closure_m": None,
        "paths": [{"id": p["id"], "elements": r.get("elements"), "ring": r.get("ring"),
                   "total_bend": r.get("total_bend")} for p, r in zip(doc["paths"], reports)],
        "conflicts": conflicts, "differs": differs,
    }
    return doc


def json_key(value) -> str:
    """A value to compare by: numbers to the precision a lattice file means."""
    return f"{value:.9g}" if isinstance(value, float) else repr(value)


# Normalised physics key → the native parameter it comes from (case-insensitive), for value provenance.
_NATIVE_OF = {"length": ("L", "LENGTH"), "angle": ("ANGLE",), "k1": ("K1",), "k2": ("K2",), "k3": ("K3",),
              "kick": ("KICK", "HKICK", "VKICK"), "ks": ("KS",), "e1": ("E1",), "e2": ("E2",),
              "voltage": ("VOLT", "VOLTAGE"), "frequency": ("FREQ", "FREQUENCY"), "harmonic": ("HARMON",),
              "phase": ("LAG", "PHASE")}


def to_v2(v1: dict, placed: list[Placed], *, source: str, filename: str) -> dict:
    """The v2 form of a converted model: components with their native name and file, definitions for every
    element the line uses more than once (and every family the format names), and per-value provenance
    saying which native parameter each normalised value was read from."""
    from app.beam_model_core.upgrade import upgrade
    conversion = v1.pop("conversion", None)
    doc = upgrade(v1)
    file = PurePath(filename or "").name or None
    by_id = {c["id"]: c for c in doc["components"]}
    values = doc["datasets"][0]["values"] if doc.get("datasets") else {}
    uses: dict[str, int] = {}
    for p in placed:
        uses[p.name.upper()] = uses.get(p.name.upper(), 0) + 1
    definitions: dict[str, dict] = {}
    seen: dict[str, int] = {}
    for p in placed:
        base = p.name.upper()
        seen[base] = seen.get(base, 0) + 1
        ident = base if seen[base] == 1 else f"{base}#{seen[base]}"
        c = by_id.get(ident)
        if c is None:
            continue
        c["native"] = {k: v for k, v in (("format", source), ("type", p.native_type), ("name", p.name),
                                         ("file", file), ("location", p.location)) if v}
        for k, v in p.component.items():
            c.setdefault(k, v)
        def_id = p.family.upper() if p.family else (base if uses[base] > 1 else None)
        if def_id:
            c["definition"] = def_id
            definitions.setdefault(def_id, {"id": def_id, "type": p.kind, "parameters": {"length": p.length},
                                            "native": {"format": source, "type": p.native_type, "name": def_id,
                                                       **({"file": file} if file else {})}})
            if p.family:
                c["family"] = p.family.upper()
        v = values.get(ident)
        if v is not None:
            prov = {}
            upper = {k.upper(): k for k in p.native}
            for key in (v.get("physics") or {}):
                hit = next((upper[n] for n in _NATIVE_OF.get(key, (key.upper(),)) if n in upper), None)
                if hit is not None:
                    prov[key] = {k: x for k, x in (("source", source), ("file", file), ("symbol", hit),
                                                   ("location", p.location)) if x}
            if prov:
                v["provenance"] = prov
    if definitions:
        doc["definitions"] = list(definitions.values())
    doc["provenance"] = {"converter": source, "sources": [{"file": file, "format": source}] if file else []}
    if conversion is not None:
        doc["conversion"] = conversion
    return doc
