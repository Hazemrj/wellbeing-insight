import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))   # so tests can import generate_data and db
sys.path.insert(0, str(ROOT))               # so tests can import the insight service package: service.guardrails ...
