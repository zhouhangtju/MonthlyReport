"""Integration platform source cleanup entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from metrics.cleanup.common import main

if __name__ == "__main__":
    main("integration")
