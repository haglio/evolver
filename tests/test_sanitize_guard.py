"""The pre-publication content guard, and its enforcement over the tracked tree.

Every "banned" term used here is an invented placeholder — the real blocklist is
git-ignored, and these tests must themselves stay publishable.
"""
import subprocess
import unittest
from pathlib import Path

from tools.sanitize_guard import find_violations, load_blocklist, scan_files

REPO = Path(__file__).resolve().parent.parent


class TestFindViolations(unittest.TestCase):
    def test_flags_a_banned_single_word(self):
        found = find_violations("this has forbiddenterm in it", ["forbiddenterm"])
        self.assertEqual([(v.term, v.line) for v in found], [("forbiddenterm", 1)])

    def test_is_case_insensitive(self):
        self.assertTrue(find_violations("FORBIDDENTERM", ["forbiddenterm"]))

    def test_word_boundary_prevents_substring_false_positive(self):
        self.assertEqual(find_violations("a class of objects", ["redacted"]), [])

    def test_matches_a_multi_word_term_across_flexible_whitespace(self):
        self.assertTrue(find_violations("a two   word phrase", ["two word"]))

    def test_reports_the_line_number(self):
        found = find_violations("clean\nclean\nbadterm here", ["badterm"])
        self.assertEqual([v.line for v in found], [3])

    def test_excerpt_redacts_every_matched_term(self):
        found = find_violations("keep alpha drop beta", ["alpha", "beta"])
        self.assertTrue(all("alpha" not in v.excerpt for v in found))
        self.assertTrue(all("***" in v.excerpt for v in found))

    def test_clean_text_has_no_violations(self):
        self.assertEqual(find_violations("perfectly clean text", ["badterm"]), [])


class TestLoadBlocklist(unittest.TestCase):
    def test_reads_terms_skipping_blanks_and_comments(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bl.txt"
            f.write_text("# a comment\nalpha\n\n  beta gamma  \n", encoding="utf-8")
            self.assertEqual(load_blocklist(f), ["alpha", "beta gamma"])


class TestTrackedTree(unittest.TestCase):
    def test_no_blocklisted_terms_in_the_tracked_tree(self):
        """With the real (git-ignored) blocklist present, no tracked file may
        contain a banned term — reintroducing one fails the suite. A public
        checkout has no blocklist, so the check is a no-op rather than a skip.
        """
        blocklist = REPO / "sanitize" / "blocklist.local.txt"
        terms = load_blocklist(blocklist) if blocklist.exists() else []
        if not terms:
            return
        tracked = subprocess.run(
            ["git", "-C", str(REPO), "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        violations = scan_files((REPO / rel for rel in tracked), terms, root=REPO)
        # Report only the redacted excerpt, never the matched term itself.
        detail = "\n".join(f"  {v.path}:{v.line}  {v.excerpt}" for v in violations[:20])
        self.assertFalse(violations, f"blocklisted terms in tracked files:\n{detail}")


if __name__ == "__main__":
    unittest.main()
