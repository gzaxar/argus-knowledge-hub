"""Navigation rules independent of the application/database."""
import unittest
from app.services.document_navigation_graph import assert_parent_move, navigation_nodes


def document(uid, workspace="eli"):
    return {"uid": uid, "title": uid, "workspace_id": workspace}


def parents(folders=(), docs=(), placements=(), links=()):
    nodes, warnings = navigation_nodes(list(folders), list(docs), list(placements), list(links), "eli")
    return {n["id"]: n["parent_id"] for n in nodes}, warnings


class NavigationGraphTests(unittest.TestCase):
    def test_folder_can_be_a_child_of_a_document(self):
        result, warnings = parents(
            folders=[{"uid": "epik8s", "name": "EPIK8s", "parent_document_uid": "wp04"}],
            docs=[document("wp04"), document("manual")],
            placements=[{"document_uid": "manual", "folder_uid": "epik8s"}],
        )
        self.assertEqual(result["f:epik8s"], "d:wp04")
        self.assertEqual(result["d:manual"], "f:epik8s")
        self.assertFalse(warnings)

    def test_alternating_folder_document_cycle_is_refused(self):
        with self.assertRaises(ValueError):
            assert_parent_move({"d:manual": "f:epik8s", "f:epik8s": "d:wp04"}, "f:epik8s", "d:manual")
        with self.assertRaises(ValueError):
            assert_parent_move({"d:manual": "f:epik8s", "f:epik8s": "d:wp04"}, "d:wp04", "d:manual")

    def test_mixed_cycle_recovery_preserves_all_nodes(self):
        result, warnings = parents(
            folders=[{"uid": "f", "name": "Folder", "parent_document_uid": "d"}],
            docs=[document("d")], placements=[{"document_uid": "d", "folder_uid": "f"}],
        )
        self.assertIsNone(result["f:f"])
        self.assertEqual(result["d:d"], "group:unfiled")
        self.assertTrue(warnings)

    def test_folder_does_not_expose_an_unavailable_document_parent(self):
        nodes, warnings = navigation_nodes(
            [{"uid": "f", "name": "Workspace folder", "parent_document_uid": "private-sensitive-id"}],
            [document("visible")], [], [], "eli",
        )
        self.assertNotIn("private-sensitive-id", repr(nodes) + repr(warnings))
        self.assertIsNone(next(n for n in nodes if n["id"] == "f:f")["parent_id"])
        self.assertTrue(warnings)

    def test_foreign_shared_document_cannot_be_a_folder_parent(self):
        result, warnings = parents(
            folders=[{"uid": "f", "name": "Folder", "parent_document_uid": "shared"}],
            docs=[document("shared", "other")],
        )
        self.assertIsNone(result["f:f"])
        self.assertEqual(result["d:shared"], "group:shared")
        self.assertTrue(warnings)

    def test_nested_folder_tracks_its_document_ancestor(self):
        result, warnings = parents(
            folders=[{"uid": "first", "name": "First", "parent_document_uid": "parent"},
                     {"uid": "second", "name": "Second", "parent_uid": "first"}],
            docs=[document("parent"), document("child")],
            placements=[{"document_uid": "child", "folder_uid": "second"}],
        )
        self.assertEqual(result["f:first"], "d:parent")
        self.assertEqual(result["f:second"], "f:first")
        self.assertEqual(result["d:child"], "f:second")
        self.assertFalse(warnings)

    def test_imported_parent_is_used(self):
        result, _ = parents(docs=[document("wp02"), document("howto")], links=[{"from_document_uid": "howto", "to_uid": "wp02"}])
        self.assertEqual(result["d:howto"], "d:wp02")

    def test_folder_placement_keeps_children_under_the_same_document(self):
        result, _ = parents(folders=[{"uid": "subsystems", "name": "Subsystems", "parent_uid": None}], docs=[document("wp02"), document("howto")], placements=[{"document_uid": "wp02", "folder_uid": "subsystems"}], links=[{"from_document_uid": "howto", "to_uid": "wp02"}])
        self.assertEqual(result["d:wp02"], "f:subsystems")
        self.assertEqual(result["d:howto"], "d:wp02")

    def test_manual_document_parent_overrides_source_navigation(self):
        result, _ = parents(docs=[document("a"), document("b"), document("c")], placements=[{"document_uid": "b", "parent_document_uid": "c"}], links=[{"from_document_uid": "b", "to_uid": "a"}])
        self.assertEqual(result["d:b"], "d:c")

    def test_explicit_root_overrides_imported_parent(self):
        result, _ = parents(docs=[document("a"), document("b")], placements=[{"document_uid": "b"}], links=[{"from_document_uid": "b", "to_uid": "a"}])
        self.assertEqual(result["d:b"], "group:unfiled")

    def test_multiple_source_parents_are_not_chosen_arbitrarily(self):
        result, warnings = parents(docs=[document("a"), document("b"), document("c")], links=[{"from_document_uid": "b", "to_uid": p} for p in ("a", "c")])
        self.assertEqual(result["d:b"], "group:unfiled")
        self.assertTrue(warnings)

    def test_repeated_identical_source_links_are_not_ambiguous(self):
        result, warnings = parents(docs=[document("a"), document("b")], links=[{"from_document_uid": "b", "to_uid": "a"}] * 2)
        self.assertEqual(result["d:b"], "d:a")
        self.assertFalse(warnings)

    def test_document_cycles_keep_every_document_visible(self):
        result, warnings = parents(docs=[document("a"), document("b")], links=[{"from_document_uid": "a", "to_uid": "b"}, {"from_document_uid": "b", "to_uid": "a"}])
        self.assertEqual(result["d:a"], "group:unfiled")
        self.assertEqual(result["d:b"], "group:unfiled")
        self.assertTrue(warnings)

    def test_folder_cycles_are_shown_at_root(self):
        result, warnings = parents(folders=[{"uid": "a", "name": "A", "parent_uid": "b"}, {"uid": "b", "name": "B", "parent_uid": "a"}])
        self.assertIsNone(result["f:a"])
        self.assertIsNone(result["f:b"])
        self.assertTrue(warnings)

    def test_missing_or_hidden_parent_does_not_leak_its_identifier(self):
        nodes, warnings = navigation_nodes([], [document("visible")], [], [{"from_document_uid": "visible", "to_uid": "hidden-sensitive-id"}], "eli")
        self.assertNotIn("hidden-sensitive-id", repr(nodes) + repr(warnings))

    def test_foreign_shared_documents_get_a_read_only_navigation_group(self):
        result, _ = parents(docs=[document("shared", "other")])
        self.assertEqual(result["d:shared"], "group:shared")

    def test_shared_source_parent_is_not_a_local_placement(self):
        result, _ = parents(docs=[document("shared", "other"), document("own")], links=[{"from_document_uid": "own", "to_uid": "shared"}])
        self.assertEqual(result["d:own"], "group:unfiled")

    def test_a_record_is_never_duplicated_between_groups(self):
        nodes, _ = navigation_nodes([], [document("a"), document("b")], [], [{"from_document_uid": "b", "to_uid": "a"}], "eli")
        self.assertEqual(len([n for n in nodes if n["kind"] == "document"]), 2)

    def test_self_parent_move_is_refused(self):
        with self.assertRaises(ValueError): assert_parent_move({}, "a", "a")

    def test_move_into_descendant_is_refused(self):
        with self.assertRaises(ValueError): assert_parent_move({"child": "parent"}, "parent", "child")

    def test_unrelated_existing_cycle_is_refused_as_parent(self):
        with self.assertRaises(ValueError): assert_parent_move({"a": "b", "b": "a"}, "new", "a")

    def test_valid_parent_move_is_allowed(self):
        assert_parent_move({"parent": "root"}, "new", "parent")

    def test_move_validation_checks_source_cycles_before_display_recovery(self):
        nodes, _ = navigation_nodes([], [document("a"), document("b")], [],
                                    [{"from_document_uid": "a", "to_uid": "b"}, {"from_document_uid": "b", "to_uid": "a"}],
                                    "eli", recover_cycles=False)
        with self.assertRaises(ValueError):
            assert_parent_move({n["id"]: n["parent_id"] for n in nodes}, "d:a", "d:b")


if __name__ == "__main__": unittest.main()
