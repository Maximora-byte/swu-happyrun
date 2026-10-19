"""Support python -m swu_happyrun without optional runtime imports at module load."""

from swu_happyrun.cli import main

raise SystemExit(main())
