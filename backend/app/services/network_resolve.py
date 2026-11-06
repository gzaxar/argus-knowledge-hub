"""Turning an address in a config file into the thing at that address.

A control configuration names hardware the way a network does — a
hostname, an IP, sometimes a MAC — while the inventory names it the way
purchasing does. Both describe the same Moxa, and until they are the same
record nothing can say which pumps go dark when it dies.

The matching is deliberately dumb and checkable. An address either appears
on exactly one piece of equipment in the inventory or it does not, and
where it does not, this says so instead of choosing. A wrong edge in a
knowledge graph is worse than a missing one: a missing edge is a gap
somebody fills, a wrong one is a conclusion somebody draws.

Two kinds of record carry an address. "DHCP Nodes" and "Registered Nodes"
are the address itself — a lease, a reservation — while a Converter, a
Server or a Camera is the thing holding the socket. When both answer to an
address, the equipment wins: it is what a fault is about.
"""
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset

IPV4 = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
MAC = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")

# The site's own domain: the configuration writes fully-qualified names,
# the inventory writes short ones, and they mean the same host.
LOCAL_DOMAINS = (".lnf.infn.it", ".infn.it")

# Object types that record an address rather than own one.
ADDRESS_RECORD_TYPES = {
    "dhcp nodes",
    "registered nodes",
    "ethernet configuration",
    "dns",
    "ip",
}

# Attribute names worth reading an address out of. Anything else holding
# something IP-shaped is likelier to be a gateway, a netmask or a boot
# server than the address of this object — `router` and `next_server` on a
# DHCP lease both look exactly like an address and belong to someone else.
IP_ATTRIBUTES = {"ip", "ip_address", "ipaddress", "indirizzo_ip", "local_ip"}
HOSTNAME_ATTRIBUTES = {"hostname", "host", "fqdn", "dns_name"}
MAC_ATTRIBUTES = {"mac", "mac_address", "hw", "hwaddr"}


def short_host(value: str) -> str:
    """`scsparcsipmxa001.lnf.infn.it` -> `scsparcsipmxa001`."""
    name = (value or "").strip().lower().rstrip(".")
    for domain in LOCAL_DOMAINS:
        if name.endswith(domain):
            return name[: -len(domain)]
    return name


def normalise_mac(value: str) -> str:
    return (value or "").strip().lower().replace("-", ":")


def _values(attributes: dict, names: set) -> Iterable[str]:
    for key, value in (attributes or {}).items():
        if key.strip().lower() not in names:
            continue
        for item in value if isinstance(value, list) else [value]:
            text = str(item).strip()
            if text:
                yield text


@dataclass
class Match:
    """What an address resolved to, and on what evidence."""

    asset: Optional[Asset] = None
    # "hostname" | "ip" | "mac" | None
    matched_on: Optional[str] = None
    # Set when nothing could be chosen, and why — for the import's report.
    ambiguous: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.asset is not None


class NetworkIndex:
    """Every address the inventory already knows, built once per import.

    Once, because doing it per lookup turned an import of a few hundred
    IOCs into a few hundred scans of several thousand objects.
    """

    def __init__(self, db: Session, workspace_id: str):
        self.by_host: dict[str, list[Asset]] = {}
        self.by_ip: dict[str, list[Asset]] = {}
        self.by_mac: dict[str, list[Asset]] = {}

        for asset in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None))):
            attributes = asset.attributes or {}

            names = {short_host(asset.name or "")}
            names.update(short_host(v) for v in _values(attributes, HOSTNAME_ATTRIBUTES))
            # A DHCP lease is named `dante051-00:20:38:00:A0:8D`: the host
            # is the part before the MAC, and it is the only name it has.
            raw_name = (asset.name or "").strip()
            if "-" in raw_name and MAC.match(raw_name.split("-", 1)[1].replace("-", ":")):
                names.add(short_host(raw_name.split("-", 1)[0]))
            for name in names:
                if name and not IPV4.match(name):
                    self.by_host.setdefault(name, []).append(asset)

            for value in _values(attributes, IP_ATTRIBUTES):
                if IPV4.match(value):
                    self.by_ip.setdefault(value, []).append(asset)
            # A name that is simply an address happens, and is still the
            # best evidence there is about what lives there.
            if IPV4.match(raw_name):
                self.by_ip.setdefault(raw_name, []).append(asset)

            for value in _values(attributes, MAC_ATTRIBUTES):
                if MAC.match(value):
                    self.by_mac.setdefault(normalise_mac(value), []).append(asset)

    def _candidates(self, address: str) -> tuple[list[Asset], Optional[str]]:
        text = (address or "").strip()
        if not text:
            return [], None
        if IPV4.match(text):
            return list(self.by_ip.get(text, ())), "ip"
        if MAC.match(text):
            return list(self.by_mac.get(normalise_mac(text), ())), "mac"
        return list(self.by_host.get(short_host(text), ())), "hostname"

    def resolve(self, address: str) -> Match:
        """The one piece of equipment at this address, if there is exactly one.

        Equipment is preferred over the record of its address, because a
        fault is about the Moxa, not about its DHCP lease. Where neither is
        unambiguous the address is reported unresolved rather than guessed.
        """
        candidates, kind = self._candidates(address)
        if not candidates:
            return Match()

        # De-duplicate: one object can match on more than one attribute.
        unique: dict[str, Asset] = {a.uid: a for a in candidates}
        equipment = [
            a for a in unique.values()
            if (a.type or "").strip().lower() not in ADDRESS_RECORD_TYPES
        ]
        records = [
            a for a in unique.values()
            if (a.type or "").strip().lower() in ADDRESS_RECORD_TYPES
        ]

        if len(equipment) == 1:
            return Match(asset=equipment[0], matched_on=kind)
        if len(equipment) > 1:
            return Match(ambiguous=[f"{a.key} ({a.type})" for a in sorted(
                equipment, key=lambda a: a.key or "")])
        if len(records) == 1:
            return Match(asset=records[0], matched_on=kind)
        if len(records) > 1:
            return Match(ambiguous=[f"{a.key} ({a.type})" for a in sorted(
                records, key=lambda a: a.key or "")])
        return Match()

    def add(self, asset: Asset, address: str) -> None:
        """Index something the import just created, so the next IOC naming
        the same host links to it instead of creating a second one."""
        text = (address or "").strip()
        if not text:
            return
        if IPV4.match(text):
            self.by_ip.setdefault(text, []).append(asset)
        elif MAC.match(text):
            self.by_mac.setdefault(normalise_mac(text), []).append(asset)
        else:
            self.by_host.setdefault(short_host(text), []).append(asset)
