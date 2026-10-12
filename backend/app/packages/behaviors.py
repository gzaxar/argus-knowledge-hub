"""The behaviours ARGUS's code gives particular types, by id.

A package marks a type with the behaviour it carries; the validator refuses an id ARGUS does not implement.
In this release the code still finds these types by name, so a behaviour is bound to the name below: a
package that put it on a type of another name would be accepted by nothing that reads it, and is refused.
"""
BEHAVIORS: dict[str, tuple[str, str]] = {
    "root": ("Item", "the root every object type descends from; carries the keys shared with tickets and documents"),
    "functional": ("Functional Element", "what the machine is: positions that survive hardware swaps"),
    "equipment": ("Asset", "a serialised physical unit: installed at positions, swapped, sent for repair"),
    "control": ("Control Item", "how the machine is driven: configurations, IOCs, devices"),
    "other_equipment": ("Other Equipment", "equipment no type describes yet, governed by equipment classes"),
    "product_model": ("Product Model", "a vendor's product; units are instances of it"),
    "vendor": ("Vendor", "the company that supplies products"),
    "equipment_port": ("Equipment Port", "one physical port of a unit, matched to control endpoints"),
    "bus_segment": ("Bus Segment", "the medium behind a control endpoint: a serial line, a bus"),
}


def describe() -> list[dict]:
    return [{"id": k, "type": name, "meaning": meaning} for k, (name, meaning) in BEHAVIORS.items()]
