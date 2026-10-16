import unittest

from wlandiag.engine import Engine, create_backend


def quiet(line, tag=""):
    pass


class TreeTests(unittest.TestCase):
    def make(self):
        probe, actions = create_backend(True, quiet)
        probe.s.delay = 0
        return probe, Engine(probe, actions, quiet)

    def test_analyse_changes_nothing(self):
        probe, eng = self.make()
        res = eng.analyse()
        self.assertEqual(res["radio"].status, "FAIL")
        self.assertEqual(res["ip"].status, "SKIP")      # hinter dem Funkfehler übersprungen
        self.assertEqual(probe.s.radio, "Off")

    def test_troubleshoot_repairs_demo_device(self):
        _, eng = self.make()
        res = eng.troubleshoot()
        for key in ("radio", "power", "ip", "dns", "http"):
            self.assertEqual(res[key].status, "OK", key)

    def test_fix_after_analyse_covers_skipped_checks(self):
        _, eng = self.make()
        eng.analyse()
        res = eng.fix()
        self.assertEqual(res["dns"].status, "OK")


if __name__ == "__main__":
    unittest.main()
