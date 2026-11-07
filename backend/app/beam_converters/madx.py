"""MAD-X: sequence and LINE files (.madx, .seq, .str), and TFS tables (a twiss or survey output, .tfs).

The language read is the part lattice files use: comments, variables (`=` and deferred `:=`, `const`/`real`
prefixes), element definitions with inheritance (`QF: QUADRUPOLE, L=0.3, K1=kqf; Q1: QF;`), `SEQUENCE ...
ENDSEQUENCE` with `REFER` (centre, entry, exit) and `AT ... FROM`, `LINE = (...)` with repetition and
reversal, `BEAM` and `USE`. Macros, `IF`/`WHILE` and `CALL` are not executed: a file that needs them is
reported, not guessed at. A TFS table brings the optics too (BETX, ALFX, DX, MUX ...).

`s` in the canonical model is an element's entry: from a centred `AT` it is AT − L/2, from a TFS row S − L.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import PurePath
from typing import Optional

from app.beam_converters import ConversionError, Converter, Options, register
from app.beam_converters.common import Evaluator, Placed, build, expand_line, hint, merge_paths, split_top

KINDS = {
    "drift": "drift", "sbend": "dipole", "rbend": "dipole", "quadrupole": "quadrupole", "sextupole": "sextupole",
    "octupole": "generic", "multipole": "generic", "hkicker": "corrector", "vkicker": "corrector",
    "kicker": "corrector", "tkicker": "corrector", "rfcavity": "rf_cavity", "crabcavity": "rf_cavity",
    "monitor": "bpm", "hmonitor": "bpm", "vmonitor": "bpm", "instrument": "generic_monitor", "marker": "marker",
    "collimator": "collimator", "rcollimator": "collimator", "ecollimator": "collimator", "solenoid": "solenoid",
    "placeholder": "generic", "elseparator": "generic", "srotation": "generic", "yrotation": "generic",
    "translation": "generic", "changeref": "generic", "beambeam": "generic", "matrix": "generic",
    "rfmultipole": "generic", "dipedge": "marker", "nllens": "generic",
}
PARTICLES = {"electron": (-1, 0.51099895e-3), "positron": (1, 0.51099895e-3), "proton": (1, 0.93827208816),
             "antiproton": (-1, 0.93827208816), "posmuon": (1, 0.1056583755), "negmuon": (-1, 0.1056583755)}
UNSUPPORTED = re.compile(r"^\s*(macro|if|while|call|exec)\b", re.I)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return "\n".join(re.split(r"//|!", line, maxsplit=1)[0] for line in text.splitlines())


def _attrs(parts: list[str]) -> dict[str, str]:
    out = {}
    for p in parts:
        m = re.match(r"^([A-Za-z_][\w.]*)\s*:?=\s*(.+)$", p, re.S)
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
        elif re.match(r"^-?[A-Za-z_]\w*$", p):
            out[p.lstrip("-").lower()] = "0" if p.startswith("-") else "1"
    return out


class _Lattice:
    def __init__(self):
        self.ev = Evaluator(resolve_attr=self.attr)
        self.defs: dict[str, tuple[str, dict]] = {}       # name -> (parent class or element, attributes)
        self.sequences: dict[str, dict] = {}
        self.lines: dict[str, list[str]] = {}
        self.beam: dict[str, str] = {}
        self.use: Optional[str] = None
        self.order: list[str] = []
        self.skipped: list[str] = []

    def base_class(self, name: str, depth: int = 0) -> str:
        name = name.lower()
        if name in KINDS or name in ("sequence", "line"):
            return name
        if depth > 30 or name not in self.defs:
            return name
        return self.base_class(self.defs[name][0], depth + 1)

    def merged(self, name: str, depth: int = 0) -> dict:
        """An element's attributes with what it inherits."""
        name = name.lower()
        if name not in self.defs or depth > 30:
            return {}
        parent, attrs = self.defs[name]
        return {**self.merged(parent, depth + 1), **attrs}

    def attr(self, element: str, key: str) -> Optional[float]:
        a = self.merged(element)
        return self.ev.eval(a[key]) if key in a else None

    def number(self, attrs: dict, key: str, default: float = 0.0) -> float:
        return self.ev.eval(attrs[key]) if key in attrs else default


def parse(text: str) -> _Lattice:
    lat = _Lattice()
    in_seq: Optional[str] = None
    for raw in _strip_comments(text).split(";"):
        st = " ".join(raw.split())
        if not st:
            continue
        if UNSUPPORTED.match(st):
            lat.skipped.append(st[:60])
            continue
        low = st.lower()
        st = re.sub(r"^(const|real|int)\s+", "", st, flags=re.I)
        low = st.lower()
        if low.startswith("endsequence"):
            in_seq = None
            continue
        m = re.match(r"^([A-Za-z_][\w.]*)\s*:?=\s*(.+)$", st)
        if m:                                   # a variable: `k = 1.2` or the deferred `k := kqf*2`
            lat.ev.define(m.group(1), m.group(2))
            continue
        m = re.match(r"^([A-Za-z_][\w.$]*)\s*:\s*line\s*=\s*\((.*)\)\s*$", st, re.I)
        if m:
            lat.lines[m.group(1).lower()] = split_top(m.group(2))
            continue
        m = re.match(r"^([A-Za-z_][\w.$]*)\s*:\s*([A-Za-z_][\w.]*)\s*(?:,(.*))?$", st)
        if m:
            label, cls, rest = m.group(1).lower(), m.group(2).lower(), m.group(3) or ""
            attrs = _attrs(split_top(rest))
            if cls == "sequence":
                in_seq = label
                lat.sequences[label] = {"attrs": attrs, "items": []}
                continue
            lat.defs.setdefault(label, (cls, attrs)) if in_seq else lat.defs.__setitem__(label, (cls, attrs))
            if in_seq:
                lat.sequences[in_seq]["items"].append((label, attrs))
            continue
        parts = split_top(st)
        head = parts[0].lower()
        if head == "beam":
            lat.beam.update(_attrs(parts[1:]))
        elif head == "use":
            a = _attrs(parts[1:])
            lat.use = (a.get("sequence") or a.get("period") or "").lower() or lat.use
        elif in_seq and re.match(r"^[A-Za-z_][\w.$]*$", parts[0]):
            lat.sequences[in_seq]["items"].append((parts[0].lower(), _attrs(parts[1:])))
        elif re.match(r"^[A-Za-z_][\w.]*\s*->\s*\w+\s*:?=", st):
            lat.skipped.append(st[:60])
    return lat


def _physics(lat: _Lattice, kind: str, a: dict, length: float) -> dict:
    n = lambda k: lat.number(a, k)  # noqa: E731
    out: dict = {}
    if kind == "dipole":
        out["angle"] = n("angle")
        for k in ("e1", "e2", "k1", "tilt"):
            if k in a:
                out[k] = n(k)
    elif kind == "quadrupole":
        out["k1"] = n("k1")
    elif kind == "sextupole":
        out["k2"] = n("k2")
    elif kind == "corrector":
        if "kick" in a or "hkick" in a or "vkick" in a:
            out["kick"] = n("kick") or n("hkick") or n("vkick")
    elif kind == "rf_cavity":
        for k, name in (("volt", "voltage"), ("freq", "frequency"), ("lag", "lag"), ("harmon", "harmonic")):
            if k in a:
                out[name] = n(k)
    elif kind == "solenoid":
        out["ks"] = n("ks")
    return out


def _native(lat: _Lattice, a: dict) -> dict:
    out = {}
    for k, v in a.items():
        if k in ("at", "from", "refpos"):
            continue
        try:
            out[k.upper()] = lat.ev.eval(v)
        except Exception:  # noqa: BLE001 — a string attribute (an aperture type, a file) is kept as written
            out[k.upper()] = v.strip("\"'")
    return out


def _capabilities(cls: str, kind: str) -> Optional[list]:
    if kind == "corrector":
        plane = {"hkicker": ["horizontal_steering"], "vkicker": ["vertical_steering"]}.get(
            cls, ["horizontal_steering", "vertical_steering"])
        return ["beam_transport", "steering", "powered", *plane]
    return None


def _placed(lat: _Lattice, name: str, attrs: dict, s: float, length: float, options: Options) -> Optional[Placed]:
    cls = lat.base_class(name)
    base = KINDS.get(cls)
    if base is None:
        return None
    if base == "drift" and not options.keep_drifts:
        return None
    if base == "marker" and not options.keep_markers:
        return None
    # The physics follows the simulator's class; the name only refines the kind (a HKICKER called KCK…
    # is a fast kicker, an RBEND called SEP… a septum).
    kind = hint(name, base, options)
    caps = _capabilities(cls, base)
    if caps is not None and kind == "kicker":
        caps = caps + ["pulsed"]
    # The family it was made from: `q1: qf` places q1, an instance of the user's qf (not a bare class).
    parent = lat.defs.get(name.lower(), (None,))[0]
    family = parent if parent and parent.lower() in lat.defs else None
    element = _element_name(name, options)
    # MAD-X names are case-insensitive and MAD-X writes them in capitals: so does the native name.
    return Placed(name=element.upper(), kind=kind, s=s, length=length, native_type=cls.upper(),
                  native=_native(lat, attrs), physics=_physics(lat, base, attrs, length), capabilities=caps,
                  family=family, label=name.upper() if element != name else None)


def _element_name(label: str, options: Options) -> str:
    """The element a label is: with `same_element_suffixes`, DHPTT001_IN and DHPTT001_OUT are DHPTT001."""
    endings = (x.strip().lower() for x in (options.same_element_suffixes or "").split(","))
    for suffix in sorted(endings, key=len, reverse=True):    # the longest first: _TL_IN before _IN
        if suffix and label.endswith(suffix) and len(label) > len(suffix):
            return label[:-len(suffix)]
    return label


def _from_sequence(lat: _Lattice, seq_name: str, options: Options) -> tuple[list[Placed], float]:
    seq = lat.sequences[seq_name]
    refer = (seq["attrs"].get("refer") or "centre").lower()
    positions: dict[str, float] = {}
    placed: list[Placed] = []
    for name, local in seq["items"]:
        a = {**lat.merged(name), **local}
        length = lat.number(a, "l")
        at = lat.number(local, "at")
        if "from" in local:
            ref = local["from"].lower()
            at += positions.get(ref, 0.0)
        positions[name] = at
        s = at - length / 2 if refer in ("centre", "center") else at if refer == "entry" else at - length
        p = _placed(lat, name, a, s, length, options)
        if p is not None:
            placed.append(p)
    placed.sort(key=lambda p: p.s)
    return placed, lat.number(seq["attrs"], "l", default=(placed[-1].s + placed[-1].length) if placed else 0.0)


def _from_line(lat: _Lattice, line_name: str, options: Options) -> tuple[list[Placed], float]:
    pos, placed = 0.0, []
    for name in expand_line(line_name, lat.lines):
        a = lat.merged(name)
        if name not in lat.defs:
            raise ConversionError(f"the line {line_name} uses {name}, which is not defined")
        length = lat.number(a, "l")
        p = _placed(lat, name, a, pos, length, options)
        if p is not None:
            placed.append(p)
        pos += length
    return placed, pos


def _beam(lat: _Lattice) -> dict:
    b = lat.beam
    particle = (b.get("particle") or "").strip("\"'").lower()
    out: dict = {}
    if particle:
        out["species"] = particle
        charge, mass = PARTICLES.get(particle, (None, None))
        out["charge"] = lat.ev.eval(b["charge"]) if "charge" in b else charge
        mass_gev = lat.ev.eval(b["mass"]) if "mass" in b else mass
        out["rest_mass"] = mass_gev * 1000 if mass_gev else None            # MeV/c², as the catalogue keeps it
    if "energy" in b:
        out["reference_energy"] = lat.ev.eval(b["energy"])
    if "pc" in b:
        out["reference_momentum"] = lat.ev.eval(b["pc"])
    return {k: v for k, v in out.items() if v is not None}


def convert_madx(text: str, filename: str, options: Options) -> dict:
    lat = parse(text)
    choice = (options.beamline or lat.use or "").lower()
    if choice and choice not in lat.sequences and choice not in lat.lines:
        raise ConversionError(f"{filename}: no sequence or line called {choice}")
    if not choice and len(lat.sequences) > 1:
        return _all_sequences(lat, filename, options)
    if not choice:
        candidates = list(lat.sequences) or list(lat.lines)
        if not candidates:
            raise ConversionError(f"{filename}: no SEQUENCE or LINE to read" +
                                  (f" (not executed: {lat.skipped[0]}…)" if lat.skipped else ""))
        choice = candidates[-1]
    placed, total = (_from_sequence if choice in lat.sequences else _from_line)(lat, choice, options)
    doc = build(placed, source="madx", filename=filename, options=options, line_name=choice, total_length=total,
                beam=_beam(lat))
    if lat.skipped:
        doc["conversion"]["not_executed"] = lat.skipped[:20]
    if len(lat.sequences) > 1:
        doc["conversion"]["sequences"] = list(lat.sequences)
        doc["conversion"]["chosen"] = choice
    return doc


def _all_sequences(lat: _Lattice, filename: str, options: Options) -> dict:
    """A file with several sequences and no USE saying which: all of them, a path each, in one model."""
    stem = PurePath(filename or "model").stem
    model_id = options.model_id or re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-").lower() or "model"
    shared = replace(options, model_id=model_id, system_id=options.system_id or model_id,
                     model_name=options.model_name or f"{stem} ({PurePath(filename).name})")
    parts, empty = [], []
    for name in lat.sequences:
        placed, total = _from_sequence(lat, name, shared)
        if not placed:
            empty.append(name)
            continue
        parts.append(build(placed, source="madx", filename=filename, options=shared, line_name=name,
                           total_length=total, beam=_beam(lat)))
    if not parts:
        raise ConversionError(f"{filename}: no elements on any of its sequences")
    doc = merge_paths(parts, filename=filename)
    doc["conversion"]["sequences"] = list(lat.sequences)
    if empty:
        doc["conversion"]["empty_sequences"] = empty
    if lat.skipped:
        doc["conversion"]["not_executed"] = lat.skipped[:20]
    return doc


# --------------------------------------------------------------------------- TFS

def parse_tfs(text: str) -> tuple[dict, list[str], list[list[str]]]:
    header, columns, rows = {}, [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("@"):
            parts = line[1:].split(None, 2)
            if len(parts) == 3:
                header[parts[0].upper()] = parts[2].strip().strip('"')
        elif line.startswith("*"):
            columns = [c.upper() for c in line[1:].split()]
        elif line.startswith("$"):
            continue
        else:
            rows.append(re.findall(r'"[^"]*"|\S+', line))
    if not columns:
        raise ConversionError("not a TFS table: no column line (*)")
    return header, columns, rows


OPTICS = {"BETX": "beta_x", "BETY": "beta_y", "ALFX": "alpha_x", "ALFY": "alpha_y", "DX": "dx", "DPX": "dpx",
          "DY": "dy", "DPY": "dpy", "MUX": "mux", "MUY": "muy", "X": "x_orbit", "Y": "y_orbit"}


def convert_tfs(text: str, filename: str, options: Options) -> dict:
    header, cols, rows = parse_tfs(text)
    need = {"NAME", "S"}
    if not need <= set(cols):
        raise ConversionError(f"{filename}: a TFS table needs the columns NAME and S (it has {cols[:8]}…)")
    placed: list[Placed] = []
    for r in rows:
        if len(r) < len(cols):
            continue
        rec = {c: v.strip('"') for c, v in zip(cols, r)}
        num = lambda k: float(rec[k]) if k in rec and re.match(r"^[-+0-9.eE]+$", rec[k]) else 0.0  # noqa: E731
        name = re.sub(r":\d+$", "", rec["NAME"]).lower()
        keyword = (rec.get("KEYWORD") or "marker").lower()
        kind = KINDS.get(keyword, "generic")
        if name.startswith("$") or (kind == "drift" and not options.keep_drifts) or \
                (kind == "marker" and not options.keep_markers):
            continue
        kind = hint(name, kind, options)
        length = num("L")
        physics: dict = {}
        if kind == "dipole":
            physics["angle"] = num("ANGLE")
        if "K1L" in rec and kind == "quadrupole":
            physics["k1"] = num("K1L") / length if length else num("K1L")
        if "K2L" in rec and kind == "sextupole":
            physics["k2"] = num("K2L") / length if length else num("K2L")
        optics = {OPTICS[c]: num(c) for c in OPTICS if c in rec}
        placed.append(Placed(name=name, kind=kind, s=num("S") - length, length=length, native_type=keyword.upper(),
                             native={c: rec[c] for c in cols if c not in OPTICS and c != "NAME"}, physics=physics,
                             optics=optics, capabilities=_capabilities(keyword, kind)))
    beam: dict = {}
    particle = header.get("PARTICLE", "").lower()
    if particle:
        beam["species"] = particle
        if particle in PARTICLES:
            beam["charge"], mass = PARTICLES[particle]
            beam["rest_mass"] = mass * 1000
    for key, out in (("ENERGY", "reference_energy"), ("PC", "reference_momentum")):
        try:
            beam[out] = float(header[key])
        except (KeyError, ValueError):
            pass
    line = (options.beamline or header.get("SEQUENCE") or "line").lower()
    total = float(header["LENGTH"]) if re.match(r"^[-+0-9.eE]+$", header.get("LENGTH", "")) else None
    doc = build(placed, source="madx", filename=filename, options=options, line_name=line, total_length=total,
                beam=beam, simulator_version=header.get("VERSION") or header.get("ORIGIN"))
    doc["conversion"]["tunes"] = {k: header[k] for k in ("Q1", "Q2") if k in header}
    return doc


register(Converter(name="madx", label="MAD-X sequence or line (.madx, .seq)", extensions=(".madx", ".seq", ".str", ".mad"),
                   detect=lambda t: bool(re.search(r"\bsequence\b|\bline\s*=|:\s*(quadrupole|sbend|rbend)\b", t, re.I))
                   and not t.lstrip().startswith("@"),
                   convert=convert_madx))
register(Converter(name="madx-tfs", label="MAD-X TFS table (twiss, .tfs)", extensions=(".tfs",),
                   detect=lambda t: t.lstrip().startswith("@") and "\n*" in t, convert=convert_tfs))
