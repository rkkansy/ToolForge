"""High‑level operations: save/load scripts, sequences, etc."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from actions import Action, KeyboardAction, MouseAction
from utils import load_json, save_json, PROGRAMS_DIR, SCRIPTS_DIR


class ScriptManager:
    """Handle *.json files and program sequences."""

    def list_scripts(self):
        return sorted(p.name for p in SCRIPTS_DIR.glob("*.json"))

    def list_programs(self):
        return sorted(p.name for p in PROGRAMS_DIR.glob("*.json"))

    def load_script(self, name: str) -> List[Action]:
        data = load_json(SCRIPTS_DIR / name)
        acts: list[Action] = []
        for entry in data:
            if "button" in entry:
                acts.append(MouseAction(**entry))
            else:
                acts.append(KeyboardAction(**entry))
        return acts

    # -------- programs (sequences of scripts with iterations) --------
    def save_program(self, seq: List[Tuple[str, int]], out_name: str):
        """seq = [(script_name, iterations), ...]"""
        save_json(seq, PROGRAMS_DIR / out_name)

    def load_program(self, name: str):
        return load_json(PROGRAMS_DIR / name)