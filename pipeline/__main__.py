"""Command-line entry point: ``python -m pipeline``."""

import sys

from pipeline.run import main

if __name__ == "__main__":
    sys.exit(main())
