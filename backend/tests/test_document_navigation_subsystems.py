"""Subsystem root display; run without application/database dependencies."""
import unittest
from app.services.document_navigation_graph import navigation_nodes


def doc(uid, title=None, workspace='eli'):
    return {'uid': uid, 'title': title or uid, 'workspace_id': workspace}


def graph(docs, placements=(), links=(), folders=()):
    nodes, warnings = navigation_nodes(list(folders), docs, list(placements), list(links), 'eli')
    return {n['id']: n['parent_id'] for n in nodes}, warnings


class SubsystemRootsTests(unittest.TestCase):
    def test_wp_title_variants_and_leaf_pages(self):
        for title in ['WP01 - Magnets', 'WP02 - RF', 'WP-01_Project_Management', 'WP_03: Engineering', 'wp 04 — Controls', 'WP05']:
            with self.subTest(title=title):
                nodes, _ = graph([doc('wp', title)])
                self.assertIsNone(nodes['d:wp'])
                self.assertNotIn('group:unfiled', nodes)

    def test_children_stay_under_wp_and_other_documents_are_unfiled(self):
        nodes, _ = graph([doc('wp', 'WP02 - RF'), doc('howto'), doc('procedure')], links=[{'from_document_uid':'howto', 'to_uid':'wp'}])
        self.assertIsNone(nodes['d:wp'])
        self.assertEqual(nodes['d:howto'], 'd:wp')
        self.assertEqual(nodes['d:procedure'], 'group:unfiled')

    def test_real_parent_and_manual_placement_are_preserved(self):
        for manual in [False, True]:
            with self.subTest(manual=manual):
                placements = [{'document_uid':'wp', 'parent_document_uid':'parent'}] if manual else []
                links = [] if manual else [{'from_document_uid':'wp', 'to_uid':'parent'}]
                nodes, _ = graph([doc('wp', 'WP02 - RF'), doc('parent')], placements=placements, links=links)
                self.assertEqual(nodes['d:wp'], 'd:parent')

    def test_explicit_root_wp_placement_is_a_subsystem_root(self):
        nodes, _ = graph([doc('wp', 'WP02 - RF'), doc('parent')], placements=[{'document_uid':'wp'}], links=[{'from_document_uid':'wp','to_uid':'parent'}])
        self.assertIsNone(nodes['d:wp'])

    def test_shared_wp_stays_in_shared_group(self):
        nodes, _ = graph([doc('wp', 'WP02 - RF', 'foreign')])
        self.assertEqual(nodes['d:wp'], 'group:shared')

    def test_ambiguous_wp_is_not_promoted(self):
        nodes, warnings = graph([doc('wp', 'WP02 - RF'), doc('a'), doc('b')], links=[{'from_document_uid':'wp','to_uid':p} for p in ['a','b']])
        self.assertEqual(nodes['d:wp'], 'group:unfiled')
        self.assertTrue(warnings)

    def test_wp_cycle_is_not_promoted(self):
        nodes, warnings = graph([doc('a','WP01'), doc('b','WP02')], links=[{'from_document_uid':'a','to_uid':'b'}, {'from_document_uid':'b','to_uid':'a'}])
        self.assertEqual(nodes['d:a'], 'group:unfiled')
        self.assertEqual(nodes['d:b'], 'group:unfiled')
        self.assertTrue(warnings)

    def test_hidden_source_parent_does_not_promote_wp(self):
        nodes, _ = graph([doc('wp','WP02')], links=[{'from_document_uid':'wp','to_uid':'hidden'}])
        self.assertEqual(nodes['d:wp'], 'group:unfiled')
        self.assertNotIn('hidden', repr(nodes))

    def test_similar_words_are_not_wp_titles(self):
        for title in ['WP', 'WP02x', 'Notes about WP02', 'WPA01']:
            with self.subTest(title=title):
                nodes, _ = graph([doc('a',title)])
                self.assertEqual(nodes['d:a'], 'group:unfiled')

    def test_empty_folder_is_preserved_for_user_management(self):
        nodes, _ = graph([doc('wp','WP02')], folders=[{'uid':'subsystems','name':'Subsystems'}])
        self.assertIn('f:subsystems',nodes)
        self.assertIsNone(nodes['d:wp'])


if __name__ == '__main__':
    unittest.main()
