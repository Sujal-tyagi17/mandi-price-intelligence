"""
Run the pipeline end to end.

    python run_all.py        # ingest data/raw -> clean warehouse -> coverage tables -> quality report
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    ("Ingest raw files", "src/ingest.py"),
    ("Clean and build the warehouse", "src/build_warehouse.py"),
]

if __name__ == "__main__":
    for title, script in STEPS:
        print(f"\n=== {title} ===", flush=True)
        result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
        if result.returncode != 0:
            sys.exit(result.returncode)   # the step has already printed what went wrong
    print("\nDone. See reports/data_quality.md")
