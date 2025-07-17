"""Logic for listening & recording user input to a list[Action]."""
from __future__ import annotations

import time
from typing import List

import pynput
from pynput import mouse, keyboard
from pynput.keyboard import Key

from actions import KeyboardAction, MouseAction
from utils import save_json, SCRIPTS_DIR


class ActionRecorder:
    def __init__(self, color_toggle_key=Key.shift_l, stop_recording_key=Key.tab, color_area_width=300, color_area_height=500):
        self._actions: List[MouseAction | KeyboardAction] = []
        self._last_action_time = None  # Track the time of the last action
        self._color_toggle_key = color_toggle_key  # Key to toggle pixel color recording
        self._color_toggle_active = False  # Whether pixel color should be recorded for the next mouse click
        self._stop_recording_key = stop_recording_key  # Key to stop recording
        self._color_area_width = color_area_width
        self._color_area_height = color_area_height
        self._stop_recording = False  # Flag to stop recording
        self._mouse_listener = None
        self._keyboard_listener = None

    # ---------- mouse callbacks ----------
    def _on_click(self, x, y, button, pressed):
        if not pressed or self._stop_recording:
            return
        btn_str = str(button)
        color = None
        color_area = None
        if self._color_toggle_active:
            import pyautogui
            color = pyautogui.pixel(x, y)
            width = self._color_area_width
            height = self._color_area_height
            color_area = (x - width // 2, y - height // 2, width, height)
        now = time.time()
        interval = now - self._last_action_time if self._last_action_time else 0.1
        self._actions.append(
            MouseAction(interval, btn_str, (x, y), self._color_toggle_active, color, color_area)
        )
        self._last_action_time = now
        self._color_toggle_active = False  # Reset after use

    # ---------- keyboard callbacks ----------
    def _on_press(self, key):
        if key == self._stop_recording_key or self._stop_recording:
            self._stop_recording = True
            return False  # Stop the listener
        if key == self._color_toggle_key:
            self._color_toggle_active = True
            return
        now = time.time()
        interval = now - self._last_action_time if self._last_action_time else 0
        self._actions.append(KeyboardAction(interval, str(key)))
        self._last_action_time = now

    def stop_recording(self):
        """Stop recording manually."""
        self._stop_recording = True
        # Stop listeners if they exist
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

    def cleanup(self):
        """Clean up all listeners and resources."""
        self.stop_recording()

    # ---------- public API ----------
    def record(self):
        try:
            self._mouse_listener = mouse.Listener(on_click=self._on_click)
            self._keyboard_listener = keyboard.Listener(on_press=self._on_press)
            
            self._mouse_listener.start()
            self._keyboard_listener.start()
            
            # Wait for keyboard listener to stop (when stop key is pressed)
            self._keyboard_listener.join()
            
        except Exception as e:
            print(f"Error during recording: {e}")
        finally:
            # Ensure listeners are stopped
            self.cleanup()
        
        return self._actions

    def save(self, name: str):
        if not name.endswith(".json"):
            name += ".json"
        out = SCRIPTS_DIR / name
        save_json([a.__dict__ for a in self._actions], out)
        return out