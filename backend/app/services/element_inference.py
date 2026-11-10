"""What a control configuration refers to without saying so.

A values.yaml lists control channels: a `GUNSIP01` on a terminal server, a
`QUATB002` on a power-supply unit, an `AC101` on a camera address. It never
lists the ion pump, the quadrupole or the camera, and yet each of those is what
the channel is for, and each is what fails, gets replaced and appears in a
report. This reads the channels back into the things they drive.

Two things carry the information, and both are used:

  metadata   `devgroup` (vac, mag, cam, bpm, rf, modulator), `devfunc` (ion, turbo,
             scroll, pig), `devtype` and the IOC's `template`. These are chosen
             by whoever wrote the file to say what the hardware is, so they say
             the asset type: a `mag` channel is a power supply, a `vac` channel
             whose function is `turbo` is a turbomolecular pump.
  the name   LNF device names are a code. `GUNQUA01` is a quadrupole, `AC1HCR01`
             a horizontal corrector, `W1KSIP01` an ion pump. The name says what a
             *magnet* is, which the metadata does not: every magnet supply is `mag`.

Where neither says, nothing is inferred. A quadrupole that is really a corrector
is worse in an inventory than an unlabelled channel, so a name that matches no
code gets no element, and a channel no rule covers is counted and reported, not
guessed at.

Everything here is a function of the configuration alone: no database, no
network, so it can be checked against the real files.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

# A lattice name as the catalogue's Beam Element expects it (asset_types.py).
LATTICE_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,15}$")

# The physical thing a channel drives, by catalogue type name.
ION_PUMP, TURBO_PUMP, PRIMARY_PUMP, NEG = "Ion Pump", "Turbo Pump", "Primary Pump", "NEG Cartridge"
GAUGE, PSU, CAMERA = "Vacuum Gauge", "Power Supply", "Camera"
DIGITIZER, LLRF, MODULATOR = "Digitizer", "Low-Level RF Unit", "Modulator"
MOTOR_AXIS, ACTUATOR = "Motor Axis", "Actuator"
CHILLER, TIMING = "Chiller", "Timing Module"

# The lattice element a magnet supply or a BPM is, where the name says which.
QUAD, DIPOLE, CORRECTOR = "Quadrupole", "Dipole", "Corrector"
SOLENOID, SEXTUPOLE, BPM = "Solenoid", "Sextupole", "Beam Position Monitor"
SCREEN, MIRROR = "Screen Station", "Mirror"
RF_GUN, STRUCTURE, DEFLECTOR = "RF Gun", "Accelerating Structure", "RF Deflector"

ASSET_TYPES = (ION_PUMP, TURBO_PUMP, PRIMARY_PUMP, NEG, GAUGE, PSU, CAMERA, DIGITIZER, LLRF, MODULATOR,
               MOTOR_AXIS, ACTUATOR, CHILLER, TIMING)
ELEMENT_TYPES = (QUAD, DIPOLE, CORRECTOR, SOLENOID, SEXTUPOLE, BPM, SCREEN, MIRROR,
                 RF_GUN, STRUCTURE, DEFLECTOR)

# What a devgroup means, in the words tickets and documents use for `argus_system`.
SYSTEM_BY_GROUP = {
    "mag": "Magnets", "vac": "Vacuum", "cam": "Cameras", "bpm": "Diagnostics",
    "rf": "RF", "modulator": "RF", "mot": "Motion", "cool": "Cooling", "timing": "Timing",
}

# Product a unit *is*, by devtype or template. Only where the channel is the product
# itself: an IPCMini is the controller of an ion pump, not the pump, so it names
# nothing here. Vendors and models are those the ibek template tree spells.
PRODUCTS: dict = {
    "histar": ("CAEN ELS", "Hi-Star"), "easydriver": ("CAEN ELS", "EASY-DRIVER"),
    "fastps": ("CAEN ELS", "FAST-PS"), "sys8x00": ("Danfysik", "System 8x00"),
    "e642": ("OCEM", "E642"), "modbusps": ("OCEM", "Modbus PS"),
    "modbusps4chan": ("OCEM", "Modbus PS 4-channel"), "tti": ("Aim-TTi", None),
    "haz-ser": ("Hazemeyer", None), "twistorr305": ("Agilent", "TwisTorr 305"),
    "pfeiffer-hiscroll6": ("Pfeiffer", "HiScroll 6"), "libera-spp": ("Instrumentation Technologies", "Libera Single Pass"),
    "libera-sppp": ("Instrumentation Technologies", "Libera Single Pass"),
    "libera-spe": ("Instrumentation Technologies", "Libera Spectra"),
    "libera-llrf": ("Instrumentation Technologies", "Libera LLRF"),
    "libera-llrf2": ("Instrumentation Technologies", "Libera LLRF"),
    "ppt": ("PPT", None), "scandinova-mod-k400": ("ScandiNova", "K400"),
}

# (code in the name, type, plane). Dipoles are read from the start of the name only:
# `DH` inside a longer word is not a dipole.
MAGNET_CODES = (
    ("QUA", QUAD, None), ("QSK", QUAD, None), ("SEX", SEXTUPOLE, None), ("SOL", SOLENOID, None),
    ("HCOR", CORRECTOR, "H"), ("VCOR", CORRECTOR, "V"), ("CHH", CORRECTOR, "H"),
    ("CVV", CORRECTOR, "V"), ("HCR", CORRECTOR, "H"), ("VCR", CORRECTOR, "V"),
    ("DPL", DIPOLE, None), ("DIP", DIPOLE, None),       # ELI's DIP01: "Dipole A" in its utility matrix
)
DIPOLE_PREFIXES = ("DHP", "DHS", "DHR", "DHY", "DVR")

# A flag is a screen: LNF names it `<section>FLG<nn>` (GUNFLG01, AC1FLG01, FELFLG03A, TESTFLG), and
# the channel lists the positions it can be driven to (`poi`: YAG, calibration, OUT).
FLAG = re.compile(r"FLG")
# EuAPS moves its mirrors with motors named for them, and its Utility Matrix (docs/EuAPS Utility
# Matrix.xlsx) says what the names are: the third field of its own codes is the object the motor
# belongs to, `MMIR` the main-laser mirror, `PMIR` the probe-laser mirror and `PAR` the parabolic
# mirror, and the fourth `HMOT`/`VMOT`/`RMOT` its horizontal, vertical and rotation motor. The
# control configuration abbreviates them: `FI4-HMN-01` is `FI4-C-MMIR-HMOT-001`, `FI1-VPB-01` is
# `FI1-C-PMIR-VMOT-001`, `FI8-PRH-01` is `FI8-C-PAR-HMOT-001`, `FI3-MMR-001` is
# `FI3-C-MMIR-RMOT-001`. The mirror is named as the matrix names it (`FI4-MMIR-001`), so a
# later import of the matrix reaches the same object.
#   (pattern, father object, laser, kind of mirror). Any other code on the same controllers (MPB,
#   HEX, DIP, SLT, PBM) is a stage the file does not tie to a mirror: MPB is the probe delay line
#   or in/out stage in the matrix, and the rest it labels "slitte?".
_AREA = r"(?P<area>[A-Z]+\d+)"
MIRROR_AXES = (
    (re.compile(rf"^{_AREA}-(?P<axis>[HV])MN-(?P<n>\d+)$"), "MMIR", "main", None),
    (re.compile(rf"^{_AREA}-(?P<axis>[HV])PB-(?P<n>\d+)$"), "PMIR", "probe", None),
    (re.compile(rf"^{_AREA}-PR(?P<axis>[HV])-(?P<n>\d+)$"), "PAR", None, "Parabolic"),
    (re.compile(rf"^{_AREA}-MM(?P<axis>R)-(?P<n>\d+)$"), "MMIR", "main", None),
)
AXIS_WORDS = {"H": "horizontal", "V": "vertical", "R": "rotation"}
FATHER_WORDS = {"MMIR": "the main-laser mirror", "PMIR": "the probe-laser mirror",
                "PAR": "the parabolic mirror"}
# The camera a flag is read with is named after it: AC1FLG01 → AC101, FELFLG03A → FEL03.
SCREEN_NAME = re.compile(r"^(?P<section>[A-Z0-9]*?)FLG(?P<n>\d+)[A-Z]?$")
# ELI names a screen station's parts after it, EPICS-style: `SCN01:CAM01` is its camera, `SCN01:MOT01`
# the axis that drives the screen in. The station is what joins them, on two different IOCs.
STATION_PART = re.compile(r"^(?P<station>(?:SCN|SCR|YAG)\d+[A-Z]?):(?P<part>[A-Z0-9_-]+)$")
GAUGE_DEVTYPES = {"img", "tpg", "tpg300", "tpg366", "tpg500"}


@dataclass
class Inference:
    """What one channel or one IOC turns out to drive."""
    asset_type: Optional[str] = None
    asset_attrs: dict = field(default_factory=dict)
    element_type: Optional[str] = None
    element_name: Optional[str] = None
    element_attrs: dict = field(default_factory=dict)
    why: str = ""                       # said on the object, so somebody can check it
    # Set on a unit whose channels are each an element (a Libera Spectra: one box, four BPMs).
    channel_element: Optional[str] = None
    # How the element relates to the asset: a BPM is `realized by` its electronics, a screen
    # station or a mirror mount is `composed of` its actuator or axes.
    element_link: str = "realized by"
    # Set where the asset acts on the element instead: a supply `powers` its magnet, a chiller
    # `cools` its structure. The relation then runs asset → element.
    asset_to_element: bool = False
    # A chiller that cools every asset of a type in the beamline (ELI's modulator hall chiller).
    cools_type: Optional[str] = None
    # A timing unit: `generator` sends events, `receiver` gets them; a receiver may trigger a type.
    timing_role: Optional[str] = None
    triggers_type: Optional[str] = None


def _s(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _product(devtype: str, template: str) -> tuple:
    return PRODUCTS.get(devtype.lower()) or PRODUCTS.get(template.lower()) or (None, None)


def _ratings(ioc: dict, device: dict) -> dict:
    """A supply's limits from `ps:`, the device's own over its IOC's."""
    def block(entry):
        return entry.get("ps") if isinstance(entry.get("ps"), dict) else {}
    ioc_ps, dev_ps = block(ioc), block(device)

    def limit(kind: str):
        for source in (dev_ps, ioc_ps):
            value = (source.get(kind) or {}).get("max") if isinstance(source.get(kind), dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None
    polarity = ((dev_ps.get("polarity") or ioc_ps.get("polarity") or {}).get("mode")
                if isinstance(dev_ps.get("polarity") or ioc_ps.get("polarity"), dict) else None)
    out = {"current_max": limit("current"), "voltage_max": limit("voltage")}
    if polarity:
        out["bipolar"] = "bipolar" in str(polarity)
    return {k: v for k, v in out.items() if v is not None}


def _magnet_element(name: str) -> Optional[tuple]:
    """(type, plane) if the name is a magnet code, else None."""
    upper = name.upper()
    if upper.startswith(DIPOLE_PREFIXES):
        return DIPOLE, None
    for code, kind, plane in MAGNET_CODES:
        if code in upper:
            return kind, plane
    return None


def _vacuum_type(name: str, devtype: str, devfunc: str) -> Optional[str]:
    upper, dt, fn = name.upper(), devtype.lower(), devfunc.lower()
    # The name first: in SPARC a NEG pump is a channel of an ion-pump controller
    # whose function is `ion`, and the name is what tells them apart.
    if "NEG" in upper:
        return NEG
    if "SIP" in upper or "IONP" in upper:
        return ION_PUMP
    if "TRB" in upper:
        return TURBO_PUMP
    if "PRY" in upper:
        return PRIMARY_PUMP
    if any(c in upper for c in ("VGA", "VUG", "VGC")) or dt in GAUGE_DEVTYPES or fn == "pig":
        return GAUGE
    return {"ion": ION_PUMP, "turbo": TURBO_PUMP, "scroll": PRIMARY_PUMP}.get(fn)


def infer_ioc(ioc: dict) -> Optional[Inference]:
    """An IOC that *is* one unit, whatever channels it lists: a BPM's electronics, an LLRF
    chassis, a modulator. Its channels are that unit's, not more things."""
    group, template = _s(ioc.get("devgroup")).lower(), _s(ioc.get("template")).lower()
    devtype = _s(ioc.get("devtype"))
    name = _s(ioc.get("name"))
    manufacturer, model = _product(devtype, template)
    hint = {k: v for k, v in {"manufacturer": manufacturer, "model": model}.items() if v}

    listed = [d for d in (ioc.get("devices") or []) if isinstance(d, dict) and d.get("name")]
    if template.startswith(("libera-sppp", "libera-spe")) or group == "bpm" or (
            group == "diag" and devtype.lower() == "bpm"):
        why = f"IOC {name} is beam position monitor electronics (template {template or '-'}, group {group or '-'})"
        base = {**hint, "argus_system": SYSTEM_BY_GROUP["bpm"]}
        if listed:
            # One box, several monitors: each channel is a BPM and this is what realises them.
            return Inference(asset_type=DIGITIZER, asset_attrs=base, channel_element=BPM, why=why)
        # The BPM's name, not its PV prefix: a prefix changes between releases, and then the same
        # monitor would become a new element.
        element = _s(ioc.get("iocprefix")).strip(":").upper().rsplit(":", 1)[-1]
        if not LATTICE_NAME.match(element):
            element = name.upper()
        return Inference(
            asset_type=DIGITIZER, asset_attrs=base, element_type=BPM, element_name=element,
            element_attrs={"lattice_name": element} if LATTICE_NAME.match(element) else {}, why=why)
    if template.startswith("libera-llrf") or (group == "rf" and devtype.lower() == "llrf"):
        return Inference(
            asset_type=LLRF, asset_attrs={**hint, "argus_system": SYSTEM_BY_GROUP["rf"]},
            why=f"IOC {name} is a low-level RF unit (template {template or '-'})")
    # A modulator IOC that lists channels has one modulator per channel (ELI's four);
    # one that lists none is itself the unit (SPARC's).
    if (group == "modulator" or template in ("ppt", "scandinova-mod-k400")) and not listed:
        return Inference(
            asset_type=MODULATOR, asset_attrs={**hint, "argus_system": SYSTEM_BY_GROUP["modulator"]},
            why=f"IOC {name} is a modulator (template {template or '-'}, group {group or '-'})")
    return None


# --------------------------------------------------------------------------- controllers

# The box between a control line and what it runs, where the IOC talks to a controller rather than to the
# thing itself: an IPCMini runs ion pumps, a TPG 366 reads six gauges, a Pollux chain moves motor axes. Only
# products that are a separate box: a TwisTorr 305 is read as the turbo pump it is (PRODUCTS), so it has none.
VACUUM_CONTROLLER, MOTION_CONTROLLER = "Vacuum Controller", "Motion Controller"
CONTROLLERS = (  # (devtype or template contains, type, manufacturer, model)
    ("ipcmini", VACUUM_CONTROLLER, "Agilent", "IPCMini"),
    ("ipcmpc", VACUUM_CONTROLLER, "Agilent", "IPC Multi Pump Controller"),
    ("tpg366", VACUUM_CONTROLLER, "Pfeiffer", "TPG 366"),
    ("tpg300", VACUUM_CONTROLLER, "Pfeiffer", "TPG 300"),
    ("tpg500", VACUUM_CONTROLLER, "Pfeiffer", "TPG 500"),
    ("pollux", MOTION_CONTROLLER, "PI miCos", "Pollux"),
    ("pigcs2", MOTION_CONTROLLER, "Physik Instrumente", "GCS2 controller"),
    ("thorlabs", MOTION_CONTROLLER, "Thorlabs", None),
    ("smaract", MOTION_CONTROLLER, "SmarAct", None),
)
CONTROLLER_TYPES = (VACUUM_CONTROLLER, MOTION_CONTROLLER)


@dataclass
class ControllerInference:
    controller_type: str
    manufacturer: Optional[str]
    model: Optional[str]
    why: str


def infer_controller(ioc: dict) -> Optional[ControllerInference]:
    """The controller an IOC talks to, when its devtype or template names one; None otherwise."""
    devtype, template = _s(ioc.get("devtype")).lower(), _s(ioc.get("template")).lower()
    name = _s(ioc.get("name"))
    for code, type_name, manufacturer, model in CONTROLLERS:
        if code in devtype or code in template or code in name.lower():
            where = "devtype" if code in devtype else "template" if code in template else "IOC name"
            return ControllerInference(
                type_name, manufacturer, model,
                f"IOC {name} talks to a {model or manufacturer} controller ({where} says {code})")
    return None


def _station_part(name: str, where: str) -> Optional[dict]:
    """The screen station a `SCN01:CAM01`-style channel belongs to, as Inference fields; None otherwise."""
    found = STATION_PART.match(name.upper())
    if not found:
        return None
    station = found["station"]
    return {"element_type": SCREEN, "element_name": station, "element_link": "composed of",
            "element_attrs": {"argus_system": "Diagnostics",
                              **({"lattice_name": station} if LATTICE_NAME.match(station) else {})},
            "why": f"{where}); {name} names it a part of {station}, a screen station's code"}


def _motion(name: str, ioc: dict, device: dict, where: str) -> Inference:
    """An axis of a motor controller: always a motor axis, and sometimes what it moves.

    A flag is a screen (its actuator is composed into a screen station), and an H/V pair of
    axes on an EuAPS mount is one mirror. Any other axis is an axis and nothing more: what it
    moves is not in the file, and a slit called a mirror is worse than no element.
    """
    upper = name.upper()
    axis = _s(device.get("axid"))
    positions = [_s(p.get("name")) for p in (device.get("poi") or []) if isinstance(p, dict) and p.get("name")]
    base = {"argus_system": SYSTEM_BY_GROUP["mot"]}
    station = _station_part(name, where)
    if station:
        return Inference(asset_type=MOTOR_AXIS, asset_attrs={**base, "axis_id": axis},
                         **station)
    if FLAG.search(upper):
        return Inference(
            asset_type=ACTUATOR, asset_attrs={**base, "position_labels": positions},
            element_type=SCREEN, element_name=upper,
            element_attrs={**({"lattice_name": upper} if LATTICE_NAME.match(upper) else {}),
                           "argus_system": "Diagnostics", "insertion_positions": positions},
            element_link="composed of",
            why=f"{where}); FLG in the name is a flag, the LNF code for a screen that is driven in and out of the beam")
    for pattern, father, laser, kind in MIRROR_AXES:
        mirror = pattern.match(upper)
        if not mirror:
            continue
        element = f"{mirror['area']}-{father}-{int(mirror['n']):03d}"
        axis_word = AXIS_WORDS[mirror["axis"]]
        return Inference(
            asset_type=MOTOR_AXIS, asset_attrs={**base, "axis_id": axis},
            element_type=MIRROR, element_name=element,
            element_attrs={k: v for k, v in {"beam": laser, "mirror_kind": kind}.items() if v},
            element_link="composed of",
            why=(f"{where}); {name} reads as the {axis_word} axis of {FATHER_WORDS[father]} {element}, "
                 f"which is how the EuAPS Utility Matrix names its {father} motors"))
    return Inference(asset_type=MOTOR_AXIS, asset_attrs={**base, "axis_id": axis},
                     why=f"{where}); one axis of a motor controller")


# What a chiller channel cools. The name says: `CHLGUN01` cools the gun, `CHLAC101` the first
# accelerating section, ELI's `ACC02` a structure, its `MOD` the modulators. A code with no type
# behind it (`CHLBOC01`, a pulse compressor; `CHLSLS01`) makes a chiller and no element, because
# an element of a guessed type is worse than none.
COOLED = (
    (re.compile(r"^(?:CHL)?(?P<name>GUN)\d*$"), RF_GUN),
    (re.compile(r"^(?:CHL)?(?P<name>AC\d)\d\d$"), STRUCTURE),          # SPARC: CHLAC101 → AC1
    (re.compile(r"^(?:CHL)?(?P<name>ACC\d+)$"), STRUCTURE),              # ELI: ACC01
    (re.compile(r"^(?:CHL)?(?P<name>RFD)\d*$"), DEFLECTOR),
)
COOLS_ALL = {"MOD": MODULATOR}
# What a timing receiver triggers, where its name says: `EVR-LLRF`, `EVR-CAM`.
TRIGGERED = (("LLRF", LLRF), ("-CAM", CAMERA))


def _plant(name: str, device: dict, ioc: dict, group: str, template: str, base: dict, where: str):
    """Chillers and timing units: the plant a channel belongs to rather than the beam."""
    upper = name.upper()
    devtype = _s(device.get("devtype") or ioc.get("devtype")).lower()
    if group == "cool" or template in ("smc", "polyscience"):
        target = COOLS_ALL.get(upper.removeprefix("CHL"))
        for pattern, element in COOLED:
            found = pattern.match(upper)
            if found and target is None:
                element_name = found["name"]
                return Inference(
                    asset_type=CHILLER, asset_attrs={**base, "argus_system": SYSTEM_BY_GROUP["cool"]},
                    element_type=element, element_name=element_name,
                    element_attrs={"lattice_name": element_name} if LATTICE_NAME.match(element_name) else {},
                    element_link="cools", asset_to_element=True,
                    why=f"{where}); a chiller channel, and {name} names what it cools: the {element.lower()} {element_name}")
        return Inference(
            asset_type=CHILLER, asset_attrs={**base, "argus_system": SYSTEM_BY_GROUP["cool"]}, cools_type=target,
            why=f"{where}); a chiller channel" + (f", cooling every {target.lower()}" if target
                                                   else f"; {name} names no cooled object the rules know"))
    if group == "timing" or template.startswith("mrf"):
        role = "generator" if devtype.startswith("evg") else "receiver" if devtype.startswith("evr") else None
        if role is None:
            return None            # a charge monitor listed on a timing IOC is not a timing unit
        trigger = next((kind for token, kind in TRIGGERED if token in upper), None) if role == "receiver" else None
        return Inference(
            asset_type=TIMING, asset_attrs={**base, "argus_system": SYSTEM_BY_GROUP["timing"]},
            timing_role=role, triggers_type=trigger,
            why=f"{where}); an event {role} (devtype {devtype})" + (f" that triggers {trigger.lower()}s" if trigger else ""))
    return None


def infer_device(ioc: dict, device: dict) -> Optional[Inference]:
    """What one channel drives, or None where neither the metadata nor the name says.

    `ioc` is the IOC's entry with its template's defaults merged in, as the importer
    reads it; the channel's own values override.
    """
    name = _s(device.get("name"))
    group = _s(device.get("devgroup") or ioc.get("devgroup")).lower()
    template = _s(ioc.get("template")).lower()
    devtype = _s(device.get("devtype") or ioc.get("devtype"))
    devfunc = _s(device.get("devfunc") or ioc.get("devfunc"))
    if not name:
        return None
    manufacturer, model = _product(devtype, template)
    hint = {k: v for k, v in {"manufacturer": manufacturer, "model": model}.items() if v}
    system = SYSTEM_BY_GROUP.get(group)
    base = {"argus_system": system} if system else {}
    where = f"channel {name} of IOC {_s(ioc.get('name'))} (group {group or '-'}, template {template or '-'}"

    # The template is what the IOC is: a motor IOC's channels are axes whatever its group says.
    if template == "motor":
        return _motion(name, ioc, device, where)

    if group in ("cool", "timing") or template in ("smc", "polyscience") or template.startswith("mrf"):
        return _plant(name, device, ioc, group, template, hint, where)

    if group == "vac":
        kind = _vacuum_type(name, devtype, devfunc)
        if kind:
            return Inference(asset_type=kind, asset_attrs={**base, **(hint if kind in (TURBO_PUMP, PRIMARY_PUMP) else {})},
                             why=f"{where}, function {devfunc or '-'})")

    if group == "mag":
        attrs = {**base, **hint, **_ratings(ioc, device)}
        magnet = _magnet_element(name)
        element_attrs: dict = {}
        if magnet:
            if LATTICE_NAME.match(name.upper()):
                element_attrs["lattice_name"] = name.upper()
            if magnet[1]:
                element_attrs["plane"] = magnet[1]
        zones = device.get("zones") or ioc.get("zones")
        return Inference(
            asset_type=PSU, asset_attrs=attrs, element_link="powers", asset_to_element=True,
            element_type=magnet[0] if magnet else None,
            element_name=name.upper() if magnet else None,
            element_attrs=element_attrs if magnet else {},
            why=f"{where})" + (f"; the name reads as a {magnet[0].lower()}" if magnet else ""))

    if group == "modulator" or template.startswith(("ppt", "scandinova")):
        return Inference(asset_type=MODULATOR, asset_attrs={**hint, "argus_system": SYSTEM_BY_GROUP["modulator"]},
                         why=f"{where})")

    if group == "cam" and devtype.lower() != "camerasim" and "SIM" not in name.upper():
        attrs = dict(base)
        # `Basler-scA640-70gm` says who made it and which model.
        made = re.match(r"^([A-Za-z]+)-(.+)$", devtype)
        if made and devtype.lower() not in ("camera", "adcamera"):
            attrs.update({"manufacturer": made.group(1), "model": made.group(2)})
        station = _station_part(name, where)
        if station:
            return Inference(asset_type=CAMERA, asset_attrs=attrs, **station)
        return Inference(asset_type=CAMERA, asset_attrs=attrs, why=f"{where})")
    return None
