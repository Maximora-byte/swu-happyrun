"""Fixed synthetic preflight only; never consume or invoke either original group."""

from issue110_capture import main

if __name__ == "__main__":
    raise SystemExit(main(preflight_only=True))
