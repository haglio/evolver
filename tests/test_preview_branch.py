from __future__ import annotations

import unittest
from unittest.mock import patch

import preview_branch


class TestSignInDeferral(unittest.TestCase):
    def test_an_expired_topaz_sign_in_is_the_reason_a_start_would_wait(self):
        with patch("util.processes.count_running", return_value=0), \
             patch("util.topaz.sign_in_expired", return_value=True):
            self.assertEqual(preview_branch.sign_in_deferral(), "topaz_sign_in_expired")

    def test_no_sign_in_check_runs_beside_a_topaz_encode_already_running(self):
        with patch("util.processes.count_running", return_value=1), \
             patch("util.topaz.sign_in_expired", return_value=True) as sign_in_expired:
            self.assertEqual(preview_branch.sign_in_deferral(), "")

        sign_in_expired.assert_not_called()


if __name__ == "__main__":
    unittest.main()
