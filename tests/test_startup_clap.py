import os
import unittest
from unittest.mock import patch

import main


class _FakeKeys:
    def __init__(self, pressed_keys=()):
        self.pressed_keys = set(pressed_keys)

    def __call__(self, key):
        return 0x8000 if key in self.pressed_keys else 0


class StartupActivationTests(unittest.TestCase):
    @patch("main.os.name", "nt")
    def test_period_unlocks_startup(self):
        self.assertTrue(main.wait_for_activation(timeout=1, key_state=_FakeKeys({0xBE}), sleep=lambda _: None))

    @patch("main.os.name", "nt")
    def test_other_keys_do_not_unlock_startup(self):
        self.assertFalse(main.wait_for_activation(timeout=0, key_state=_FakeKeys(), sleep=lambda _: None))



if __name__ == "__main__":
    unittest.main()