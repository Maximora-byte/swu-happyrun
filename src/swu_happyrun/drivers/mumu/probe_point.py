"""Production point entry remains closed before any I/O or device construction."""


def run_probe_point_cli(args, *, point, clock, emit):
    from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment

    require_native_enrollment()
