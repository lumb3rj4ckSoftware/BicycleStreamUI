#!/usr/bin/env python3
"""Compatibility helper: run the OpenANT scanner exactly as the legacy project did."""
import subprocess
import sys

if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-u", "-m", "openant", "scan", "--logging", "ERROR", "-a"]))
