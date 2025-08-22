# ==========================[ actions.py ]=====================================
"""Data models and enums for input actions."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Tuple, Union


class ActionType(Enum):
    MOUSE = auto()
    KEYBOARD = auto()


@dataclass
class MouseAction:
    timestamp: float  # interval (seconds) to wait before this action
    button: str  # e.g. "Button.left"
    position: Tuple[int, int]
    color_toggle: bool = False
    color: Tuple[int, int, int] | None = None
    color_area: tuple[int, int, int, int] | None = None  # (x, y, w, h) screenshot area for color search
    color_tolerance: int = 1  # Tolerance for color matching (0-255)
    delay_randomization: bool = False  # Enable delay randomization
    delay_min_multiplier: float = 1.0  # Minimum multiplier for delay randomization
    delay_max_multiplier: float = 1.5  # Maximum multiplier for delay randomization

    @property
    def type(self) -> ActionType:
        return ActionType.MOUSE


@dataclass
class KeyboardAction:
    timestamp: float  # interval (seconds) to wait before this action
    key: str  # e.g. "Key.space" or "'a'"
    delay_randomization: bool = False  # Enable delay randomization
    delay_min_multiplier: float = 1.0  # Minimum multiplier for delay randomization
    delay_max_multiplier: float = 1.5  # Maximum multiplier for delay randomization

    @property
    def type(self) -> ActionType:
        return ActionType.KEYBOARD


Action = Union[MouseAction, KeyboardAction]