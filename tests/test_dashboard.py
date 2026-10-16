"""Every dashboard page renders without errors on the sample-data build (Streamlit AppTest)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["views/prices.py", "views/when.py", "views/where.py", "views/ban.py", "views/forecast.py",
         "views/shocks.py", "views/about.py"]

SCRIPT = """
import sys
from streamlit.testing.v1 import AppTest
failed = []
for page in sys.argv[1:]:
    for crop in ("Onion", "Tomato", "Potato"):
        at = AppTest.from_file("dashboard/app.py", default_timeout=60)
        at.session_state["f_crop"] = crop
        at.run()
        at.switch_page(page).run()
        if at.exception:
            failed.append(f"{page} [{crop}]: {at.exception[0].message}")
        if page in ("views/ban.py", "views/about.py"):
            break
print("\\n".join(failed))
sys.exit(1 if failed else 0)
"""


@pytest.mark.skipif(not __import__("importlib").util.find_spec("streamlit"), reason="streamlit not installed")
def test_all_pages_render(built):
    work = built.parents[1]
    env = {**os.environ, "MANDIPULSE_WORKDIR": str(work)}
    r = subprocess.run([sys.executable, "-c", SCRIPT, *PAGES], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
