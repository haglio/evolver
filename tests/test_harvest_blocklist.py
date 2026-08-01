"""Tests for the blocklist harvester.

Every name here is invented. The harvester's whole job is to read real library
values, so a test that reached for one to look realistic would be writing the
exact thing this tool exists to keep out of the tree.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.harvest_blocklist import (
    EXCLUDED,
    already_in_code,
    candidates_from,
    harvest,
    merge,
    normalize,
    read_roots,
    siblings_of,
)


class TestNormalize(unittest.TestCase):
    def test_lowercases_and_single_spaces_any_separator(self):
        for raw in ("Petra Vance", "Petra-Vance", "Petra_Vance", "Petra.Vance",
                    "  Petra   Vance  ", "PETRA-vance"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize(raw), "petra vance")


class TestCandidatesFrom(unittest.TestCase):
    """What a filename or folder name is worth remembering."""

    def test_takes_the_credit_from_a_performer_dash_title_filename(self):
        """The shape the library actually uses. Only the credit is wanted -- the
        title trailing it is not a name, and blocking a whole sentence would fail
        innocent commits everywhere.
        """
        got = candidates_from(
            "Petra Vance - Some Long Title 3 (2011) Enhanced",
            whole_name_counts=False,
        )
        self.assertEqual(got, {"petra vance"})

    def test_finds_a_name_however_the_filename_joins_it(self):
        for stem in ("Petra-Vance-scene-a-1080p", "Petra_Vance_540-abcd1234",
                     "Petra.Vance.scene.b"):
            with self.subTest(stem=stem):
                self.assertIn(
                    "petra vance", candidates_from(stem, whole_name_counts=False))

    def test_a_folder_name_counts_whole(self):
        """A bucket folder is named after one person and nothing else. This is
        the case that leaked: a single lowercase word, no capitals to spot.
        """
        self.assertEqual(
            candidates_from("hargrove", whole_name_counts=True), {"hargrove"})

    def test_a_folder_name_is_not_taken_from_a_filename(self):
        self.assertEqual(candidates_from("hargrove", whole_name_counts=False), set())

    def test_skips_the_librarys_own_structure(self):
        for name in ("other", "2 done", "0 unsorted", "3_good_to_go",
                     "1 clips to upscale", "metadata", "videos"):
            with self.subTest(name=name):
                self.assertEqual(candidates_from(name, whole_name_counts=True), set())

    def test_skips_pipeline_and_encoder_vocabulary(self):
        for stem in ("clip_apo8_iris2", "Vol6", "something_1080p_hevc"):
            with self.subTest(stem=stem):
                self.assertEqual(candidates_from(stem, whole_name_counts=False), set())

    def test_skips_the_placeholders_the_fixtures_use(self):
        """Blocking one of these would turn every repo's fixtures red at once."""
        for stem in ("Jane Doe - Scene One", "Ada-Roe-1", "Example Studio"):
            with self.subTest(stem=stem):
                self.assertEqual(candidates_from(stem, whole_name_counts=False), set())

    def test_a_lone_short_word_is_not_worth_blocking(self):
        """One short token matches far too much prose to pay for itself."""
        self.assertEqual(candidates_from("tess", whole_name_counts=True), set())


class TestHarvest(unittest.TestCase):
    def _library(self, root: Path) -> Path:
        lib = root / "videos" / "2D" / "non_AI"
        (lib / "hargrove" / "0 unsorted").mkdir(parents=True)
        (lib / "hargrove" / "0 unsorted" / "Petra Vance - A Long Title.mp4").touch()
        (lib / "hargrove" / "0 unsorted" / "notes.txt").write_text(
            "Marisol Quint should not be found here", encoding="utf-8")
        (lib / "other").mkdir()
        (lib / "other" / "Tallis-Brand-scene-a.mkv").touch()
        return root

    def test_finds_names_in_folder_names_and_media_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = harvest([self._library(Path(tmp))])
            self.assertLessEqual({"hargrove", "petra vance", "tallis brand"}, found)

    def test_ignores_non_media_files_entirely(self):
        """Only names *in the library's own naming* count. Reading arbitrary text
        files would harvest prose and block half the English language.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn("marisol quint", harvest([self._library(Path(tmp))]))

    def test_a_root_that_is_not_there_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(harvest([root / "gone", self._library(root)]))

    def test_stops_descending_past_the_depth_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp)
            for part in ("a", "b", "c", "d", "e", "f", "g"):
                deep = deep / part
            deep.mkdir(parents=True)
            (deep / "Petra Vance - Deep.mp4").touch()
            self.assertNotIn("petra vance", harvest([Path(tmp)], max_depth=3))

    def test_nothing_harvested_is_ever_an_excluded_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(harvest([self._library(Path(tmp))]) & EXCLUDED)


class TestAlreadyInCode(unittest.TestCase):
    """The filter that decides whether a harvested term is safe to enforce.

    Without it the harvest is unusable: a library folder named after an ordinary
    word fails thousands of innocent lines the moment it lands. Measured against
    the real library, sixteen candidates collided and they alone accounted for
    every one of 3609 false failures.
    """

    def _repo(self, root: Path, files: dict) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for args in (["init", "-b", "main"], ["config", "user.email", "h@e.test"],
                     ["config", "user.name", "H"], ["add", "."],
                     ["commit", "-m", "seed", "--no-verify"]):
            subprocess.run(["git", "-C", str(root), *args],
                           check=True, capture_output=True)
        return root

    def test_reports_a_candidate_that_ordinary_code_already_uses(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp) / "r",
                              {"a.py": "parser.add_argument('--output')\n"})
            self.assertEqual(
                already_in_code({"output", "petra vance"}, [repo]), {"output"})

    def test_a_candidate_no_code_uses_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp) / "r", {"a.py": "x = 1\n"})
            self.assertEqual(already_in_code({"petra vance"}, [repo]), set())

    def test_a_collision_in_any_checkout_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = self._repo(Path(tmp) / "clean", {"a.py": "x = 1\n"})
            other = self._repo(Path(tmp) / "other", {"b.py": "# frames per second\n"})
            self.assertEqual(already_in_code({"frames"}, [clean, other]), {"frames"})

    def test_untracked_files_do_not_count(self):
        """Only what is published can make a term unsafe to enforce."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp) / "r", {"a.py": "x = 1\n"})
            (repo / "scratch.py").write_text("output = 2\n", encoding="utf-8")
            self.assertEqual(already_in_code({"output"}, [repo]), set())

    def test_no_candidates_means_no_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(already_in_code(set(), [Path(tmp) / "nope"]), set())


class TestMerge(unittest.TestCase):
    def test_adds_only_what_is_new_and_keeps_the_rest(self):
        merged, added = merge(["zeta", "alpha"], {"alpha", "petra vance"})
        self.assertEqual(added, 1)
        self.assertEqual(merged, ["alpha", "petra vance", "zeta"])

    def test_an_existing_term_in_another_spelling_is_not_re_added(self):
        """The file may hold `Petra-Vance` from an earlier hand edit; harvesting
        `petra vance` must not produce a second entry for the same person.
        """
        merged, added = merge(["Petra-Vance"], {"petra vance"})
        self.assertEqual(added, 0)
        self.assertEqual(merged, ["Petra-Vance"])


class TestRoots(unittest.TestCase):
    def test_reads_paths_skipping_comments_and_blanks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sanitize").mkdir()
            (root / "sanitize" / "blocklist.local.txt").write_text(
                "x\n", encoding="utf-8")
            (root / "sanitize" / "library_roots.local.txt").write_text(
                "# where the library is\nC:/media/videos\n\nC:/media/archive\n",
                encoding="utf-8")
            self.assertEqual(
                read_roots(root),
                [Path("C:/media/videos"), Path("C:/media/archive")],
            )

    def test_no_roots_file_means_nothing_to_harvest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sanitize").mkdir()
            (root / "sanitize" / "blocklist.local.txt").write_text(
                "x\n", encoding="utf-8")
            self.assertEqual(read_roots(root), [])


class TestSiblings(unittest.TestCase):
    def test_finds_checkouts_that_keep_a_blocklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("here", "kin", "stranger"):
                (root / name).mkdir()
            for name in ("here", "kin"):
                (root / name / "sanitize").mkdir()
            self.assertEqual([p.name for p in siblings_of(root / "here")], ["kin"])


if __name__ == "__main__":
    unittest.main()
