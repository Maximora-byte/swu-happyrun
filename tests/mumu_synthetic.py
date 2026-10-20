"""Test-only adapters. Never packaged or selectable by product CLI/environment.

Callers replace transports or subprocess spawning before exercising these seams.
The product protocol cores require explicit injection and have no native default.
"""

from swu_happyrun.drivers.command import _run_bounded_bytes, run_readonly
from swu_happyrun.drivers.mumu.native_684 import _CommandProtocol684
from swu_happyrun.drivers.mumu.own_probe import _ObservationProtocol


class MuMuNative684(_CommandProtocol684):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            readonly_transport=lambda *a, **k: run_readonly(*a, **k),
            capture_transport=lambda *a, **k: _run_bounded_bytes(*a, **k),
            **kwargs,
        )


class OwnProbe(_ObservationProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, readonly_transport=lambda *a, **k: run_readonly(*a, **k), **kwargs)
