"""Generic JSON config loader.

mabdt itself does not require any particular configuration schema. This
helper loads a JSON file and returns the resulting dict. Deployments are
responsible for validating their own required keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a JSON config file and return it as a dict.

    Args:
        path: Path to a JSON file.

    Returns:
        The parsed JSON object as a dict.

    Raises:
        FileNotFoundError: If `path` does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    if not isinstance(result, dict):
        raise ValueError(f"Config file {path} must contain a JSON object at the top level")
    return result
