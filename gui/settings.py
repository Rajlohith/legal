"""Tiny JSON-backed settings store so the Settings panel remembers
the user's last tesseract path / headless choice between runs."""

import json
import os

from config import SETTINGS_FILE, DEFAULT_TESSERACT_PATH

DEFAULTS = {
    "tesseract_path": DEFAULT_TESSERACT_PATH,
    "headless": False,
    "last_output_dir": os.path.expanduser("~"),
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = DEFAULTS.copy()
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULTS.copy()


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass
