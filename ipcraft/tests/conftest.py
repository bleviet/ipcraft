import os
import sys

import pytest

# Add the project root to sys.path so that ipcraft is importable
# This is needed because of the flat layout structure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
