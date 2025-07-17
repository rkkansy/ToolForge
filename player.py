"""Replaying recorded actions."""
from __future__ import annotations

import random
import time
from typing import Iterable, List, Tuple, Callable, Optional

import pyautogui
from pynput.mouse import Button, Controller as MouseCtl
from pynput.keyboard import Controller as KeyCtl, Key, KeyCode, Listener as KeyListener

from actions import Action, ActionType, KeyboardAction, MouseAction
from utils import find_color_mean

MOUSE = MouseCtl()
KEYS = KeyCtl()

_BUTTON_MAP = {"Button.left": Button.left, "Button.right": Button.right, "Button.middle": Button.middle}


def _to_key(k: str):
    if k.startswith("Key."):
        return getattr(Key, k.split(".")[1], None)
    return KeyCode.from_char(k.strip("'"))


class ActionPlayer:
    def __init__(self, speed: float = 1.0, granular_sleep: float = 0.03, 
                 pause_key=Key.space, stop_key='s', skip_pause_key='n', loop_until_stopped=False,
                 progress_callback: Optional[Callable] = None):
        self.speed = speed
        self._g_sleep = granular_sleep
        self.stop_flag = False
        self.pause_flag = True
        self.skip_pause_flag = False
        self.pause_key = pause_key
        self.stop_key = stop_key
        self.skip_pause_key = skip_pause_key
        self.loop_until_stopped = loop_until_stopped
        self.keyboard_listener = None
        self.progress_callback = progress_callback
        
        # Progress tracking
        self.current_script_name = ""
        self.current_script_iteration = 0
        self.current_script_total_iterations = 0
        self.current_action_index = 0
        self.current_action_total = 0
        self.current_action_delay = 0.0
        self.elapsed_time = 0.0
        self.total_program_duration = 0.0

    def _calculate_program_duration(self, program_sequence: List[Tuple[str, int]]) -> float:
        """Calculate total duration of the program including all iterations."""
        from script_manager import ScriptManager
        mgr = ScriptManager()
        total_duration = 0.0
        
        for script_name, iterations in program_sequence:
            try:
                actions = mgr.load_script(script_name)
                script_duration = sum(action.timestamp for action in actions)
                total_duration += script_duration * iterations
            except Exception:
                continue
                
        return total_duration * self.speed

    def _update_progress(self):
        """Update progress information and call callback if available."""
        if self.progress_callback:
            progress_info = {
                'script_name': self.current_script_name,
                'script_iteration': self.current_script_iteration,
                'script_total_iterations': self.current_script_total_iterations,
                'action_index': self.current_action_index,
                'action_total': self.current_action_total,
                'action_delay': self.current_action_delay,
                'elapsed_time': self.elapsed_time,
                'total_duration': self.total_program_duration,
                'is_paused': self.pause_flag,
                'is_stopped': self.stop_flag
            }
            self.progress_callback(progress_info)

    def stop_playback(self):
        """Stop playback and clean up all listeners."""
        self.stop_flag = True
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

    def update_keys(self, pause_key=None, stop_key=None, skip_pause_key=None):
        """Update keyboard keys and restart listener with new keys."""
        # Stop current listener
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        
        # Update keys
        if pause_key is not None:
            self.pause_key = pause_key
        if stop_key is not None:
            self.stop_key = stop_key
        if skip_pause_key is not None:
            self.skip_pause_key = skip_pause_key
        
        # Restart listener with new keys
        self.keyboard_listener = KeyListener(on_press=self._on_key_press)
        self.keyboard_listener.start()

    def replay_program(self, program_sequence: List[Tuple[str, int]]):
        """Replay a program sequence of scripts with iterations."""
        from script_manager import ScriptManager
        mgr = ScriptManager()
        
        # Calculate total program duration
        self.total_program_duration = self._calculate_program_duration(program_sequence)
        
        # Start keyboard listener for replay control
        self.keyboard_listener = KeyListener(on_press=self._on_key_press)
        self.keyboard_listener.start()
        print(f"Loop until stopped: {self.loop_until_stopped}")

        try:
            while not self.stop_flag:
                for script_name, iterations in program_sequence:
                    self.current_script_name = script_name
                    self.current_script_total_iterations = iterations
                    
                    # Load the script
                    try:
                        actions = mgr.load_script(script_name)
                        self.current_action_total = len(actions)
                    except Exception as e:
                        print(f"Failed to load script {script_name}: {e}")
                        continue
                    
                    # Run the script for the specified number of iterations
                    for iteration in range(iterations):
                        self.current_script_iteration = iteration + 1
                        print(f"Running {script_name} (iteration {iteration + 1}/{iterations})")
                        if self.stop_flag:
                            break
                        
                        for action_index, act in enumerate(actions):
                            if self.stop_flag:
                                break
                                
                            self.current_action_index = action_index + 1
                            self.current_action_delay = act.timestamp * self.speed
                            
                            # Update progress before sleep
                            self._update_progress()
                            
                            # ----- handle interval sleep -----
                            delay = act.timestamp * self.speed
                            self._sleep(delay)
                            
                            # Update elapsed time
                            self.elapsed_time += delay
                            
                            # ----- perform action -----
                            if self.stop_flag:
                                break
                            if act.type == ActionType.MOUSE:
                                self._do_mouse(act)  # type: ignore[arg-type]
                            else:
                                self._do_key(act)  # type: ignore[arg-type]

                        self._sleep(0.2)
                
                # If not looping, break after first iteration
                if not self.loop_until_stopped:
                    self.pause_flag = True
        finally:
            if self.keyboard_listener:
                self.keyboard_listener.stop()

    def _on_key_press(self, key):
        try:
            # Handle pause/resume
            if key == self.pause_key:
                self.pause_flag = not self.pause_flag
                print(f"Script {'paused' if self.pause_flag else 'resumed'} via keyboard.")
                self._update_progress()  # Update progress to show pause state
                return
            
            # Handle stop
            if hasattr(key, 'char') and key.char and key.char.lower() == self.stop_key.lower():
                self.stop_flag = True
                print("Script stopped via keyboard.")
                self._update_progress()  # Update progress to show stop state
                return
            
            # Handle skip pause
            if hasattr(key, 'char') and key.char and key.char.lower() == self.skip_pause_key.lower():
                self.skip_pause_flag = True
                print("Current pause skipped via keyboard.")
                return
                
        except AttributeError:
            pass

    # ---------------------------------------------------------------------
    def _sleep(self, total):
        elapsed = 0.0
        while elapsed < total and not self.stop_flag:
            if self.pause_flag:
                time.sleep(0.1)  # Check pause more frequently
                continue
            if self.skip_pause_flag:
                self.skip_pause_flag = False
                break
            time.sleep(self._g_sleep)
            elapsed += self._g_sleep

    def _do_mouse(self, act: MouseAction):
        x, y = act.position
        if act.color_toggle:
            shot = "_area.png"
            from utils import screenshot_area
            area_x, area_y, area_w, area_h = act.color_area
            screenshot_area(area_x, area_y, area_w, area_h, shot)
            found = find_color_mean(shot, act.color, offset=(area_x, area_y), tolerance=5)
            if found:
                x, y = found
                print(f"Color found: {act.color} at {x}, {y}")
            else:
                print(f"Color not found: {act.color}")
                return

        MOUSE.position = (x, y)
        time.sleep(0.06)
        MOUSE.click(_BUTTON_MAP.get(act.button, Button.left))

    def _do_key(self, act: KeyboardAction):
        key_obj = _to_key(act.key)
        if not key_obj:
            return
        time.sleep(0.01)
        KEYS.press(key_obj)
        time.sleep(0.06)
        KEYS.release(key_obj)