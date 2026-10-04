"""Save a provider key interactively to the configured external credential store."""
import argparse
from getpass import getpass
from panel_keys import PROVIDERS, save_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=[p for p in PROVIDERS if p != "kilo"])
    args = parser.parse_args()
    save_key(args.provider, getpass("Provider key (hidden): "))
    print("Key saved to the external credential store.")


if __name__ == "__main__":
    main()
