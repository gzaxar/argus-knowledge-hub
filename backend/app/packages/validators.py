"""Validation a regular expression cannot say, referenced from packages by a stable id (`validator: <id>`).

A package stays declarative: it names the check; the check is code, here, tested. The record validator
(services/attribute_validation) runs it on save; the package validator refuses an id that is not here.
Each check takes the value and returns what is wrong with it, or None.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Callable, Optional

Check = Callable[[object], Optional[str]]


def _text(value) -> str:
    return str(value).strip()


def mac_address(value) -> Optional[str]:
    if not re.fullmatch(r"(?i)([0-9a-f]{2}[:-]){5}[0-9a-f]{2}|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}", _text(value)):
        return "is not a MAC address (aa:bb:cc:dd:ee:ff)"
    return None


def ipv4_address(value) -> Optional[str]:
    try:
        ipaddress.IPv4Address(_text(value))
    except ValueError:
        return "is not an IPv4 address"
    return None


def ip_network(value) -> Optional[str]:
    try:
        ipaddress.ip_network(_text(value), strict=True)
    except ValueError:
        return "is not a network in CIDR notation (192.168.1.0/24)"
    return None


def cig(value) -> Optional[str]:
    """Codice Identificativo Gara (ANAC): ten characters, letters and digits."""
    if not re.fullmatch(r"[0-9A-Z]{10}", _text(value).upper()):
        return "is not a CIG (10 letters and digits)"
    return None


def cup(value) -> Optional[str]:
    """Codice Unico di Progetto: fifteen characters, a letter first."""
    if not re.fullmatch(r"[A-Z][0-9A-Z]{14}", _text(value).upper()):
        return "is not a CUP (15 characters, a letter first)"
    return None


# Patent and application numbers as the offices print them: EP 1 234 567 (A1/B1), US 10,123,456 B2,
# IT 102020000012345, WO 2020/123456, EP 20123456.7, PCT/IB2020/012345.
_PATENT = re.compile(r"""^(
    (EP|US|IT|DE|FR|GB|JP|CN|KR|CA|AU|CH|ES|WO)\s?[0-9][0-9 ,./]{5,16}[0-9](\s?[A-Z][0-9]?)?
  | PCT/[A-Z]{2}[0-9]{4}/[0-9]{6}
)$""", re.X)


def patent_number(value) -> Optional[str]:
    if not _PATENT.match(_text(value).upper()):
        return "is not a patent or application number as an office prints it (EP 1234567 B1, PCT/IB2020/012345)"
    return None


def doi(value) -> Optional[str]:
    if not re.fullmatch(r"10\.\d{4,9}/\S+", _text(value).removeprefix("https://doi.org/")):
        return "is not a DOI (10.xxxx/…)"
    return None


def orcid(value) -> Optional[str]:
    """ORCID iD with its ISO 7064 11,2 check digit."""
    v = _text(value).removeprefix("https://orcid.org/")
    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", v):
        return "is not an ORCID iD (0000-0000-0000-0000)"
    digits = v.replace("-", "")
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    if digits[-1] != ("X" if check == 10 else str(check)):
        return "is not a valid ORCID iD (its check digit is wrong)"
    return None


def wavelength_nm(value) -> Optional[str]:
    try:
        nm = float(value)
    except (TypeError, ValueError):
        return "is not a wavelength in nanometres"
    if not 1 <= nm <= 1_000_000:
        return "is not a plausible wavelength (1 nm … 1 mm)"
    return None


def not_after_today(value) -> Optional[str]:
    from datetime import date
    try:
        d = date.fromisoformat(_text(value)[:10])
    except ValueError:
        return "is not a date"
    if d > date.today():
        return "is in the future"
    return None


VALIDATORS: dict[str, tuple[Check, str]] = {
    "it.mac_address": (mac_address, "a MAC address"),
    "it.ipv4_address": (ipv4_address, "an IPv4 address"),
    "it.ip_network": (ip_network, "a network in CIDR notation"),
    "admin.cig": (cig, "an Italian tender identifier (CIG)"),
    "admin.cup": (cup, "an Italian public project code (CUP)"),
    "tt.patent_number": (patent_number, "a patent or application number"),
    "tt.doi": (doi, "a DOI"),
    "tt.orcid": (orcid, "an ORCID iD, with its check digit"),
    "optics.wavelength_nm": (wavelength_nm, "a wavelength in nanometres"),
    "core.not_after_today": (not_after_today, "a date not in the future"),
}


def check(validator_id: str, value) -> Optional[str]:
    """What is wrong with the value under this validator (each item of a list), or None."""
    fn = VALIDATORS[validator_id][0]
    for item in value if isinstance(value, list) else [value]:
        if item in (None, ""):
            continue
        problem = fn(item)
        if problem:
            return f"{item!r} {problem}"
    return None


def describe() -> list[dict]:
    return [{"id": k, "checks": v[1]} for k, v in VALIDATORS.items()]
