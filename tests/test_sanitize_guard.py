"""The pre-publication content guard, and its enforcement over the tracked tree.

Every "banned" term used here is an invented placeholder — the real blocklist is
git-ignored, and these tests must themselves stay publishable.
"""
import subprocess
import unittest
from pathlib import Path

from tools.sanitize_guard import (
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
)

REPO = Path(__file__).resolve().parent.parent


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class TestFindViolations(unittest.TestCase):
    def test_flags_a_banned_single_word(self):
        found = find_violations("this has forbiddenterm in it", ["forbiddenterm"])
        self.assertEqual([(v.term, v.line) for v in found], [("forbiddenterm", 1)])

    def test_is_case_insensitive(self):
        self.assertTrue(find_violations("FORBIDDENTERM", ["forbiddenterm"]))

    def test_word_boundary_prevents_substring_false_positive(self):
        self.assertEqual(find_violations("a concatenated list", ["cat"]), [])

    def test_matches_a_multi_word_term_across_flexible_whitespace(self):
        self.assertTrue(find_violations("a two   word phrase", ["two word"]))

    def test_matches_a_term_a_line_wrap_has_split(self):
        """A per-line scan cannot see this. A real title hid behind a docstring's
        line break through every scan, and only surfaced when a history rewrite
        matched on the whole blob and put it back together.
        """
        found = find_violations("a title like *two\n    word* would match", ["two word"])
        self.assertEqual([v.line for v in found], [1])  # where the match starts

    def test_a_line_number_still_points_at_the_right_line(self):
        found = find_violations("clean\nclean\nhas badterm\nclean", ["badterm"])
        self.assertEqual([v.line for v in found], [3])

    def test_matches_a_multi_word_term_joined_the_way_a_filename_joins_it(self):
        """The list is written in prose; the leak arrives as a filename. Real
        names sat on a public `main` in exactly these shapes, unflagged, because
        the matcher allowed only whitespace between a term's words.
        """
        for slug in ("two-word", "two_word", "two.word", "twoword"):
            with self.subTest(slug=slug):
                self.assertTrue(
                    find_violations(f"clip-{slug}-scene-a.mp4", ["two word"])
                )

    def test_matches_an_inflected_form(self):
        """`badterm` on the list did not catch `badterms` in prose: the trailing
        word boundary refused the plural.
        """
        for form in ("badterms", "badterm's", "badtermed", "badterming"):
            with self.subTest(form=form):
                self.assertTrue(find_violations(f"the {form} here", ["badterm"]))

    def test_widening_still_refuses_an_unrelated_longer_word(self):
        """Separator and inflection slack must not decay into a substring match:
        `cat` may reach `cat-s`, never `concatenated`.
        """
        self.assertEqual(find_violations("a concatenated list", ["cat"]), [])
        self.assertEqual(find_violations("scatter the words", ["cat"]), [])
        self.assertEqual(find_violations("a category error", ["cat"]), [])

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


class TestBlocklistPath(unittest.TestCase):
    """The blocklist is git-ignored, so only its resolution keeps the guard alive."""

    def test_uses_this_checkout_when_the_blocklist_is_here(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sanitize").mkdir()
            here = root / "sanitize" / "blocklist.local.txt"
            here.write_text("alpha\n", encoding="utf-8")
            self.assertEqual(blocklist_path(root), here)

    def test_falls_back_to_the_primary_checkout_from_a_worktree(self):
        """The regression this whole helper exists for: a worktree never has the
        git-ignored overlay, so resolving it locally left the guard toothless
        wherever the work actually happens.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary"
            primary.mkdir()
            _git(primary, "init", "-b", "main")
            _git(primary, "config", "user.email", "guard@example.test")
            _git(primary, "config", "user.name", "Guard Test")
            (primary / "sanitize").mkdir()
            real = primary / "sanitize" / "blocklist.local.txt"
            real.write_text("alpha\n", encoding="utf-8")
            (primary / "README.md").write_text("hi\n", encoding="utf-8")
            _git(primary, "add", "README.md")
            _git(primary, "commit", "-m", "seed")

            tree = Path(tmp) / "tree"
            _git(primary, "worktree", "add", str(tree), "-b", "side")
            self.assertFalse((tree / "sanitize" / "blocklist.local.txt").exists())
            self.assertEqual(blocklist_path(tree), real.resolve())

    def test_returns_a_missing_path_when_no_checkout_has_one(self):
        """The public-clone case: no blocklist here, none in the primary either.
        Absence must read as "nothing to enforce" — a returned path that simply
        does not exist — never a crash. Same outcome when git is missing entirely,
        which the helper swallows for the benefit of a source tree with no repo.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / "clone"
            clone.mkdir()
            _git(clone, "init", "-b", "main")
            self.assertFalse(blocklist_path(clone).exists())


class TestHookEntryPoint(unittest.TestCase):
    """The CLI the git hooks call. Each case builds a throwaway repo and drives
    the real hooks through ``git commit``, because what matters is not that
    ``main()`` returns 1 -- it is that git refuses the commit.
    """

    # A nonce, because the fixture repo stages a copy of the guard's own source
    # and that source spells `badterm` in its docstrings -- using `badterm` here
    # would make every case turn on the guard file rather than on the fixture.
    TERM = "nonceterm"

    def _repo(self, tmp: str, terms=None) -> Path:
        repo = Path(tmp) / "repo"
        (repo / "sanitize").mkdir(parents=True)
        # Ignored here exactly as in the real repos. It matters to the fixture:
        # the blocklist necessarily contains every term, so a staged copy of it
        # trips the hook -- the right answer for a real repo, the wrong setup
        # for a test.
        (repo / ".gitignore").write_text(
            "sanitize/blocklist.local.txt\n", encoding="utf-8")
        if terms is not None:
            (repo / "sanitize" / "blocklist.local.txt").write_text(
                terms, encoding="utf-8")
        for rel in ("tools/__init__.py", "tools/sanitize_guard.py",
                    "tools/githooks/pre-commit", "tools/githooks/commit-msg"):
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((REPO / rel).read_bytes())
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "guard@example.test")
        _git(repo, "config", "user.name", "Guard Test")
        _git(repo, "config", "core.hooksPath", "tools/githooks")
        return repo

    def _commit(self, repo: Path, message: str = "seed"):
        return subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", message],
            capture_output=True, text=True,
        )

    def test_the_hook_refuses_a_staged_banned_term(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, f"{self.TERM}\n")
            (repo / "notes.md").write_text(
                f"this has {self.TERM} in it\n", encoding="utf-8")
            _git(repo, "add", ".")
            done = self._commit(repo)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("blocked term", done.stderr)
            self.assertNotIn(self.TERM, done.stderr)  # redacted, never echoed

    def test_the_hook_refuses_a_banned_term_in_the_message(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, f"{self.TERM}\n")
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", ".")
            done = self._commit(repo, f"drop the {self.TERM} fixture")
            self.assertNotEqual(done.returncode, 0)

    def test_it_judges_the_staged_half_not_the_working_copy(self):
        """A file staged clean and then dirtied must still commit: the index is
        what becomes the commit, so reading disk would block the wrong thing.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, f"{self.TERM}\n")
            f = repo / "notes.md"
            f.write_text("clean\n", encoding="utf-8")
            _git(repo, "add", ".")
            f.write_text(f"now with {self.TERM}\n", encoding="utf-8")
            self.assertEqual(self._commit(repo).returncode, 0)

    def test_a_clean_commit_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, f"{self.TERM}\n")
            (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
            _git(repo, "add", ".")
            self.assertEqual(self._commit(repo).returncode, 0)

    def test_no_blocklist_means_no_enforcement(self):
        """A public clone has no overlay. It must commit normally, not be told
        the guard cannot run.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, None)
            (repo / "notes.md").write_text(
                f"this has {self.TERM} in it\n", encoding="utf-8")
            _git(repo, "add", ".")
            self.assertEqual(self._commit(repo).returncode, 0)


class TestTrackedTree(unittest.TestCase):
    def test_no_blocklisted_terms_in_the_tracked_tree(self):
        """With the real (git-ignored) blocklist present, no tracked file may
        contain a banned term — reintroducing one fails the suite. A public
        checkout has no blocklist, so the check is a no-op rather than a skip.
        """
        blocklist = blocklist_path(REPO)
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
