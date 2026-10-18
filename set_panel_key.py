"""Save a provider key interactively to the configured external credential store."""
import argparse
import sys
from getpass import getpass
from panel_keys import PROVIDERS, save_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=[p for p in PROVIDERS if p != "kilo"])
    args = parser.parse_args()
    try:
        save_key(args.provider, getpass("Provider key (hidden): "))
    except (OSError, ValueError, EOFError):
        # Exception text may contain credential material; never print it.
        print("Could not save key. Check the key format and credential store access.", file=sys.stderr)
        return 1
    print("Key saved to the external credential store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
