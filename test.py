"""Small local diagnostic retained for compatibility with the original repository."""
from pathlib import Path
import json

p = Path(__file__).with_name("gc_live.json")
if not p.exists():
    print("gc_live.json fehlt. Starte bridge.py --mode test.")
else:
    print(json.dumps(json.loads(p.read_text(encoding="utf-8")), indent=2))
