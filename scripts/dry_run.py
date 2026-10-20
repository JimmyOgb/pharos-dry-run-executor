#!/usr/bin/env python3
"""
CLI entry point for Pharos Dry-Run Executor.
"""
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from executor.cli import main

if __name__ == "__main__":
    sys.exit(main())
