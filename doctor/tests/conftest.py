import os
import sys
import tempfile

DOCTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(DOCTOR_DIR)
sys.path.insert(0, DOCTOR_DIR)
sys.path.insert(0, REPO_ROOT)

# The tests never read a developer's .env and never write the real data dir.
os.environ["DOCTOR_ENV_FILE"] = os.devnull
os.environ["DOCTOR_DATA_DIR"] = tempfile.mkdtemp(prefix="doctor_tests_")
os.environ.setdefault("DOCTOR_REPO", REPO_ROOT)
for var in ("DOCTOR_PROVIDER", "DOCTOR_FALLBACK_PROVIDER", "DOCTOR_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"):
    os.environ.pop(var, None)
