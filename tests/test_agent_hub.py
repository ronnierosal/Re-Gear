"""Include the standalone hub regression suite in the repository's normal gate."""
import importlib.util
from pathlib import Path
import sys

HUB_DIR = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_hub'


def load_tests(loader, tests, pattern):
    sys.path.insert(0, str(HUB_DIR))
    try:
        spec = importlib.util.spec_from_file_location('regear_hub_tests', HUB_DIR / 'test_hub.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return loader.loadTestsFromModule(module)
    finally:
        sys.path.remove(str(HUB_DIR))
