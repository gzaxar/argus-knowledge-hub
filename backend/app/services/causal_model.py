"""What a relation means for a failure.

The knowledge graph walks edges in both directions, which is right for "what is connected to this
magnet" and useless for "why did this magnet stop". A root-cause walk needs to know, for each kind
of edge, which way a failure travels and what it takes away with it, and that is a fact about the
relation's meaning, not about any one object.

Take `Control Device --provided by--> IOC`. It is stored from the device to the IOC, and a failure
travels the other way: when the IOC stops, the device loses its readout. `PS --powers--> Quadrupole`
is stored provider to dependent, and the failure travels the way the edge points. So each relation
type gets two facts:

  flows    which way a failure travels along the stored edge. `forward`: from the edge's source to its
           target. `reverse`: from the target to the source. `none`: the edge says what something *is*
           or where it came from (a configuration it was read from, a model it is an instance of),
           and no failure crosses it.
  carries  what the dependent loses.
             control       readout and command, but not its function. An IOC that stops does not stop
                           the ion pump it reads; it stops anyone seeing the pump.
             function      what the thing does. A chiller that stops cools nothing.
             permit        a condition that lets it run. Vacuum above a threshold does not break the RF,
                           it stops the RF being raised.
             degradation   part of something is lost. A screen station without its camera is not gone
                           but is no use.

`carries` matters as much as `flows`, because it decides where a failure can go next. A device that
has lost its IOC has lost *control*, and that is all it can pass on: to the asset it acts on, which
loses control too. It must not reach the lattice element the asset realises, because the pump is
still pumping. `follows()` says which losses may cross which edges.

Every relation type any importer writes must be classified here. A test enforces it, because an
unclassified relation is silently ignored by every walk, which is how a graph goes wrong quietly.
"""
from dataclasses import dataclass
from typing import Optional

CONTROL, FUNCTION, PERMIT, DEGRADATION = "control", "function", "permit", "degradation"
FORWARD, REVERSE, NONE = "forward", "reverse", "none"

# Layers are the axes an engineer thinks along. A cooling fault and a network fault are different
# investigations even when both end at the same magnet, so a walk can be limited to some of them.
LAYERS = {
    "control": "the control system: hosts, IOCs, devices, networks, storage",
    "power": "electrical supply",
    "cooling": "cooling water and chillers",
    "vacuum": "pumping, gauges and valves",
    "timing": "event generators, receivers and the triggers they send",
    "interlock": "permits and machine protection",
    "function": "what a functional element is realised by",
    "composition": "what an assembly is made of",
    "membership": "what a section or system contains",
    "beam": "the order of elements along the beam",
    "mechanical": "supports, girders and movers, and the components they carry",
    "environment": "rooms and racks",
    "provenance": "where a record came from; no failure crosses these",
    "safety": "fire, radiation and personnel protection: what detects, suppresses or shields what",
    "access": "doors, zones and the readers and interlocks that admit people",
    "monitoring": "measurement networks: which station or sensor watches what",
    "optics": "laser and optical paths, and the references they are aligned to",
    "gas": "process and cryogenic gas supply",
    "administrative": "contracts, orders and agreements; no failure crosses these",
}


@dataclass(frozen=True)
class RelationSemantics:
    layer: str
    flows: str
    carries: Optional[str]
    weak: bool = False          # a hop that degrades rather than removes: membership in a section
    note: str = ""


# (stored as: source --relation--> target)
SEMANTICS: dict = {
    # --- the control path -----------------------------------------------------------------------
    "provided by": RelationSemantics("control", REVERSE, CONTROL,
                                     note="device → IOC: the IOC stops, the device loses its readout"),
    "connects to": RelationSemantics("control", REVERSE, CONTROL,
                                     note="IOC → access point: the host or converter stops, the IOC is cut off"),
    "reached through": RelationSemantics("control", REVERSE, CONTROL,
                                         note="device → access point: the address it is read at"),
    "on network": RelationSemantics("control", REVERSE, CONTROL,
                                    note="IOC or access point → network"),
    "mounts": RelationSemantics("control", REVERSE, CONTROL,
                                note="IOC → storage: a storage server down takes its IOCs with it"),
    "implemented by": RelationSemantics("control", REVERSE, CONTROL,
                                        note="access point → the equipment behind the address"),
    "runs on": RelationSemantics("control", REVERSE, CONTROL, note="IOC → the host that runs it"),
    "on line": RelationSemantics("control", REVERSE, CONTROL, note="device → serial line"),
    "port of": RelationSemantics("control", REVERSE, CONTROL, note="serial line → access point"),
    "carried by": RelationSemantics("control", REVERSE, CONTROL,
                                    note="a logical line → each thing it passes through: cable, switch, "
                                         "converter. A series path: any of them stopping cuts the line"),
    # The connectivity model (§9) that replaces the three edges above.
    "uses path": RelationSemantics("control", REVERSE, CONTROL,
                                   note="device → communication path: the path is cut, the device is unreachable"),
    "enters at": RelationSemantics("control", REVERSE, CONTROL,
                                   note="path → the access point it ends at: the endpoint stops, the path is cut"),
    "continues on": RelationSemantics("control", REVERSE, CONTROL,
                                      note="path → the bus segment behind the endpoint: a broken segment cuts it"),
    "served by": RelationSemantics("control", FORWARD, CONTROL,
                                   note="segment → the path that serves it: stored the other way round from "
                                        "`continues on`, and failing the same way"),
    "acts on": RelationSemantics("control", FORWARD, CONTROL,
                                 note="device → what it drives: it loses control, not function"),
    "drives": RelationSemantics("control", FORWARD, CONTROL, note="IOC → the unit it is"),

    # --- physical supply ------------------------------------------------------------------------
    "powers": RelationSemantics("power", FORWARD, FUNCTION, note="supply → magnet"),
    "cools": RelationSemantics("cooling", FORWARD, FUNCTION, note="chiller → what it cools"),
    # Stored from the consumer's reference field (a breaker's `fed_from`): the other way round from `powers`
    # and `cools`, failing the same way — the supply fails, so does what it feeds.
    "fed from": RelationSemantics("power", REVERSE, FUNCTION, note="consumer → its electrical supply"),
    "cooled by": RelationSemantics("cooling", REVERSE, FUNCTION, note="consumer → the plant that cools it"),
    "triggers": RelationSemantics("timing", FORWARD, FUNCTION, note="timing receiver → what it triggers"),
    "timed by": RelationSemantics("timing", REVERSE, FUNCTION,
                                  note="receiver → the generator whose events it receives"),
    "interlocks": RelationSemantics("interlock", FORWARD, PERMIT, note="interlock → what it inhibits"),
    "enabled by": RelationSemantics("interlock", REVERSE, PERMIT,
                                    note="X → Y: X may run only while Y allows it (pressure, permit)"),

    # --- function and structure -------------------------------------------------------------------
    "realized by": RelationSemantics("function", REVERSE, FUNCTION,
                                     note="element → the equipment that realises it"),
    "composed of": RelationSemantics("composition", REVERSE, DEGRADATION,
                                     note="assembly → part: without the part it is degraded"),
    "part of": RelationSemantics("membership", FORWARD, DEGRADATION, weak=True,
                                 note="member → section: a member failing degrades the section"),
    "upstream of": RelationSemantics("beam", FORWARD, DEGRADATION,
                                     note="beam element → the next one downstream"),
    # The beam model's topology (docs/beam-model.md). `s` orders elements along one path; these say how
    # paths are actually joined, so a branch never has to be faked with a coordinate.
    "branches to": RelationSemantics("beam", FORWARD, DEGRADATION,
                                     note="branch point (a septum, a splitter) → the first element of a branch path"),
    "closes to": RelationSemantics("beam", FORWARD, DEGRADATION,
                                   note="last element of a closed path → its first: a ring has no end"),
    "merges into": RelationSemantics("beam", FORWARD, DEGRADATION,
                                     note="the end of an injected path → where it joins another (injection)"),
    "continues to": RelationSemantics("beam", FORWARD, DEGRADATION,
                                      note="the end of a path → the start of the next (an injector chain)"),
    # A support moving or failing misaligns what it carries; a chamber failing degrades what is inside it.
    "mounted on": RelationSemantics("mechanical", REVERSE, DEGRADATION,
                                    note="component → the girder, support or mover it sits on"),
    "contained in": RelationSemantics("mechanical", REVERSE, DEGRADATION, weak=True,
                                      note="component → the assembly or chamber it is part of"),
    # A sensor's signal reaches the electronics that read it: when the pickup fails, its reading is gone.
    "connected to": RelationSemantics("control", FORWARD, CONTROL,
                                      note="pickup or sensor → the electronics that read it"),
    "signal of": RelationSemantics("control", REVERSE, CONTROL,
                                   note="control signal → the control device (or IOC) that provides it"),
    "located in": RelationSemantics("environment", REVERSE, FUNCTION,
                                    note="asset → room or rack: the place fails, the asset with it"),

    # --- no failure crosses these -----------------------------------------------------------------
    "deployed on": RelationSemantics("provenance", NONE, None, note="IOC → the beamline it serves"),
    "declared in": RelationSemantics("provenance", NONE, None, note="record → the configuration it was read from"),
    "templated from": RelationSemantics("provenance", NONE, None, note="IOC → its template"),
    "configures": RelationSemantics("provenance", NONE, None),
    "instance of": RelationSemantics("provenance", NONE, None, note="asset → its product model"),
    "supplied by": RelationSemantics("provenance", NONE, None, note="product model → its vendor"),
    "described by": RelationSemantics("provenance", NONE, None),
    "measures": RelationSemantics("provenance", NONE, None,
                                  note="a measurement observes an element, it does not cause its faults"),
    # The beam model: what a model says and what a signal means. Knowing a diagnostic observes beam.position.x
    # does not make a fault travel; the hardware and control edges above carry that.
    "observes": RelationSemantics("provenance", NONE, None, note="diagnostic element → an observable it measures"),
    "signal for": RelationSemantics("provenance", NONE, None,
                                    note="control signal → the beam element or asset whose quantity it carries"),
    "starts at": RelationSemantics("provenance", NONE, None, note="beam path → its reference element (s = 0)"),
    "beam of": RelationSemantics("provenance", NONE, None, note="beam → the beam system that carries it"),
    "models": RelationSemantics("provenance", NONE, None, note="model dataset → the beam path it describes"),
    "placed on": RelationSemantics("provenance", NONE, None,
                                   note="component → each beam path it is placed on (it may be on several)"),
    "fiducial of": RelationSemantics("provenance", NONE, None,
                                     note="fiducial → the component or support whose alignment it defines"),
    "measured by": RelationSemantics("provenance", NONE, None,
                                     note="model location → the physical instrument that measures there"),
    "associated with": RelationSemantics("provenance", NONE, None, note="related, without a stronger claim"),
    "replaced": RelationSemantics("provenance", NONE, None),
    "spare for": RelationSemantics("provenance", NONE, None),
    "requires": RelationSemantics("provenance", NONE, None),
    "procured under": RelationSemantics("provenance", NONE, None),
    "assigned to": RelationSemantics("provenance", NONE, None),
}

# The relations the model itself defines; an extension may not redefine them.
BASE_SEMANTICS = dict(SEMANTICS)


def _with_extensions() -> None:
    """The relations declared by the installed template packages (`relation_types`), then by extensions that
    pass the gate (§13 S8); neither redefines a relation of the model itself."""
    from app import extensions
    from app.packages import relations
    SEMANTICS.update({k: v for k, v in relations.semantics().items() if k not in BASE_SEMANTICS})
    SEMANTICS.update(extensions.semantics())


# The losses that may keep travelling after a hop that brought `state`. What a device has lost is
# control, and control is nearly all it can hand on; what a chiller has lost is function, and that
# can go anywhere. A lost permit stops there: an inhibited process does not break what it drives.
_ONWARD = {
    FUNCTION: {CONTROL, FUNCTION, PERMIT, DEGRADATION},
    # A permit is computed from a readout: an RF process that will not raise power above a pressure
    # cannot check the pressure of a gauge it can no longer read, so lost readout can lose a permit.
    CONTROL: {CONTROL, PERMIT},
    DEGRADATION: {DEGRADATION},
    PERMIT: set(),
}


def classify(relation_type: str) -> Optional[RelationSemantics]:
    return SEMANTICS.get((relation_type or "").strip().lower())


def dependency(source_uid: str, target_uid: str, relation_type: str) -> Optional[tuple]:
    """The stored edge as (provider, dependent): the failure goes from the first to the second.
    None where the relation carries no failure or is not classified."""
    meaning = classify(relation_type)
    if meaning is None or meaning.flows == NONE:
        return None
    return (source_uid, target_uid) if meaning.flows == FORWARD else (target_uid, source_uid)


def follows(state: str, hop_carries: str) -> bool:
    """May a node that has suffered `state` pass a loss of `hop_carries` along this hop?"""
    return hop_carries in _ONWARD.get(state, set())


_with_extensions()
