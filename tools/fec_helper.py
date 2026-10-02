#!/usr/bin/env python3
"""Reference FE-C helper contract.

This bundled helper intentionally does NOT claim control of a real trainer. It is a safe
capability probe/contract example for plugging in a tested ANT+ FE-C master implementation.
Configure BICYCLE_FEC_HELPER to a real helper executable only after validating it with the
Admin 0/1/2/Restore buttons.
"""
from __future__ import annotations
import json
import sys


def emit(obj, code=0):
    print(json.dumps(obj))
    raise SystemExit(code)


if len(sys.argv) < 2:
    emit({"ok": False, "reason": "expected status|grade|restore"}, 2)
cmd = sys.argv[1].lower()
if cmd == "status":
    emit({
        "found": False,
        "connected": False,
        "controllable": False,
        "grade": False,
        "device": "",
        "reason": "Bundled helper is a safe stub. Configure a validated ANT+ FE-C master helper via BICYCLE_FEC_HELPER."
    })
if cmd in {"grade", "restore"}:
    emit({"ok": False, "reason": "No real FE-C control backend configured."}, 3)
emit({"ok": False, "reason": f"unknown command: {cmd}"}, 2)
