"""STRIDE threat-model PoC suite for nexus-core.

This package holds one test module per STRIDE category:

* ``test_spoofing.py``      — S: identity forgery
* ``test_tampering.py``     — T: data/state modification
* ``test_repudiation.py``   — R: denying an action happened
* ``test_info_disclosure.py`` — I: leaking data
* ``test_dos.py``           — D: resource exhaustion
* ``test_elevation.py``     — E: gaining unauthorized authority

Every test documents the *attack* it demonstrates and is written to be
honest: it FAILS (or is marked as a demonstrated gap) when the code is
vulnerable, so the suite is a finding-detector, not a rubber stamp.
``helpers.py`` holds the shared fixtures/probes.

The tests prefer the pure stdlib layers (``src.security.access``,
``src.tools.executor``, ``src.council.builder``) so they run on the phone
gate without FastAPI. Where an HTTP-level assertion matters, the test is
skipped when FastAPI is absent (``importorskip``) — never faked.
"""
