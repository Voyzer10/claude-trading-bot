"""Shared helpers for the V6 tests: repo path, the synthetic fixture, and a tiny check() runner that works both as a
plain script (python tests/scanner_v6/test_x.py, like the rest of tests/) and under pytest."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(name="synthetic_5m.json"):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    return False


def run_main(tests):
    """Run test functions as a script: print ok / FAIL per test, exit 1 on any failure."""
    fails = 0
    for t in tests:
        try:
            t()
            print("ok    %s" % t.__name__)
        except Exception as e:      # AssertionError or an unexpected error: both fail the test
            fails += 1
            print("FAIL  %s: %s: %s" % (t.__name__, type(e).__name__, e))
    print("\n%d failed" % fails if fails else "\nall passed")
    sys.exit(1 if fails else 0)
