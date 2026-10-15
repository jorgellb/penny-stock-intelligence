"""Allow `python -m app ...` (Makefile entrypoint)."""

from app.cli import main

if __name__ == "__main__":
    main()
