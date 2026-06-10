"""Module entrypoint for the CMS KB inventory CLI."""

from .inventory import main


if __name__ == "__main__":
  raise SystemExit(main())
