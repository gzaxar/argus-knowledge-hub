"""A question put to search_objects in words: the same answer through Ask ARGUS and through MCP."""
import pytest

from app.db import SessionLocal
from app.models.asset import Asset
from app.routers.mcp import INSTRUCTIONS
from app.services.ask import SYSTEM
from app.services.mcp_tools import LOOKUP_GUIDE, catalogue
from tests.test_ask_types import beamline, tool  # noqa: F401


def test_ask_and_an_mcp_client_are_told_the_same_way_to_count():
    assert LOOKUP_GUIDE in SYSTEM and LOOKUP_GUIDE in INSTRUCTIONS
    described = next(t for t in catalogue() if t["name"] == "search_objects")["description"]
    assert "counting the records of that type" in described, "a client may ignore the instructions, not the tools"


@pytest.fixture()
def ring(beamline):  # noqa: F811
    ws = beamline["ws"]
    db = SessionLocal()
    for key, name, type_name, model in (("ring_pa/RDH11", "RDH11", "Dipole", "ring_pa"),
                                        ("ring_pa/RDH12", "RDH12", "Dipole", "ring_pa"),
                                        ("line/LDH01", "LDH01", "Dipole", "line"),
                                        ("ring_pa/RQU11", "RQU11", "Quadrupole", "ring_pa")):
        db.add(Asset(uid=f"{ws}-{name}", workspace_id=ws, schema_uid=f"{ws}:{type_name}", key=f"{ws}:{key}",
                     name=name, type=type_name, attributes={"model_name": model}))
    db.commit()
    db.close()
    return beamline


def search(world, **arguments):
    return tool(world["raw"], "search_objects", arguments)


@pytest.mark.parametrize("query", ["ring_pa dipole", "dipoles ring_pa", "dipoles in the ring_pa"])
def test_each_word_of_a_query_must_match(ring, query):
    found = search(ring, query=query)
    assert found["total"] == 2 and found["by_type"] == {"Dipole": 2}
    assert {o["name"] for o in found["objects"]} == {"RDH11", "RDH12"}
    assert all(o["model"] == "ring_pa" for o in found["objects"])
    assert "hint" not in found


def test_a_single_word_still_means_what_it_did(ring):
    assert search(ring, query="RDH11")["total"] == 1
    assert search(ring, query="ring_pa")["by_type"] == {"Dipole": 2, "Quadrupole": 1}


def test_words_that_match_nothing_together_find_nothing(ring):
    assert search(ring, query="line quadrupole")["total"] == 0
