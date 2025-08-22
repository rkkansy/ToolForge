"""Replaying recorded actions."""
from __future__ import annotations

import random
import time
import tkinter as tk
from typing import Iterable, List, Tuple, Callable, Optional

import pyautogui
from pynput.mouse import Button, Controller as MouseCtl
from pynput.keyboard import Controller as KeyCtl, Key, KeyCode, Listener as KeyListener

from actions import Action, ActionType, KeyboardAction, MouseAction
from utils import *

MOUSE = MouseCtl()
KEYS = KeyCtl()

player_pos = (1111,561)


_BUTTON_MAP = {"Button.left": Button.left, "Button.right": Button.right, "Button.middle": Button.middle}


def _to_key(k: str):
    if k.startswith("Key."):
        return getattr(Key, k.split(".")[1], None)
    return KeyCode.from_char(k.strip("'"))


class ActionPlayer:
    def __init__(self, speed: float = 1.0, granular_sleep: float = 0.03, 
                 pause_key=Key.space, stop_key='s', skip_pause_key='n', restart_key='r', loop_until_stopped=False,
                 progress_callback: Optional[Callable] = None):
        self.speed = speed
        self._g_sleep = granular_sleep
        self.stop_flag = False
        self.pause_flag = True
        self.skip_pause_flag = False
        self.pause_key = pause_key
        self.stop_key = stop_key
        self.skip_pause_key = skip_pause_key
        self.restart_key = restart_key
        self.loop_until_stopped = loop_until_stopped
        self.restart_flag = False
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
            try:
                self.progress_callback(progress_info)
            except (tk.TclError, RuntimeError):
                # GUI has been destroyed, stop trying to update it
                self.stop_flag = True
                pass

    def stop_playback(self):
        """Stop playback and clean up all listeners."""
        self.stop_flag = True
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

    def reset_state(self):
        """Reset player state for restarting."""
        self.stop_flag = False
        self.pause_flag = False
        self.skip_pause_flag = False
        self.current_script_name = ""
        self.current_script_iteration = 0
        self.current_script_total_iterations = 0
        self.current_action_index = 0
        self.current_action_total = 0
        self.current_action_delay = 0.0
        self.elapsed_time = 0.0
        self.total_program_duration = 0.0

    def update_keys(self, pause_key=None, stop_key=None, skip_pause_key=None, restart_key=None):
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
            while True:
                index = 0
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
                        
                        while self.pause_flag:
                            self._sleep(0.2)
                            if self.stop_flag:
                                break
                        
                        # Use while loop for actions to allow restarting
                        action_index = 0
                        reset_counter = 0
                        while action_index < len(actions):
                            if self.stop_flag:
                                break
                                
                            act = actions[action_index]
                            self.current_action_index = action_index + 1
                            self.current_action_delay = act.timestamp * self.speed
                            # Update progress before sleep
                            self._update_progress()
                            
                            # Check stop flag again before processing action
                            if self.stop_flag:
                                break
                            
                            # ----- handle interval sleep -----
                            delay = act.timestamp * self.speed
                            
                            # Apply delay randomization if enabled for this action
                            if act.delay_randomization:
                                delay *= random.uniform(act.delay_min_multiplier, act.delay_max_multiplier)
                            
                            if delay > 30:
                                print(f"Delay: {delay}")
                            self._sleep(delay)
                            
                            # Check stop flag after sleep
                            if self.stop_flag:
                                break
                            
                            # Update elapsed time
                            self.elapsed_time += delay
                            
                            # ----- perform action -----
                            if self.stop_flag:
                                break
                            if act.type == ActionType.MOUSE:
                                if self._do_mouse(act) == 0:
                                    # Reset to start of actions loop
                                    action_index = 0
                                    reset_counter += 1
                                    print(f"Reset counter: {reset_counter}")
                                    time.sleep(1)
                                    if reset_counter > 20:
                                        self.stop_flag = True
                                        break
                                    continue
                            else:
                                self._do_key(act)  # type: ignore[arg-type]
                            
                            # Move to next action
                            action_index += 1

                        # Check stop flag before moving to next iteration
                        if self.stop_flag:
                            break
                            
                        self._sleep(0.2)
                    if self.stop_flag:
                        break

                if self.stop_flag:
                    self._sleep(0.2)
                    break
                # If not looping, break after first iteration
                if not self.loop_until_stopped:
                    self.pause_flag = True

        finally:
            if self.keyboard_listener:
                self.keyboard_listener.stop()

    def replay_program_test(self, program_sequence: List[Tuple[str, int]]):
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
            while True:
                index = 0
                for script_name, iterations in program_sequence:
                    self.current_script_name = script_name
                    self.current_script_total_iterations = iterations
                    
                    print(f"index: {index}")
                    index += 1
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
                        
                        # Use while loop for actions to allow restarting
                        action_index = 0
                        while action_index < len(actions):
                            if self.stop_flag:
                                break
                                
                            act = actions[action_index]
                            self.current_action_index = action_index + 1
                            self.current_action_delay = act.timestamp * self.speed
                            
                            # Update progress before sleep
                            self._update_progress()
                            
                            # Check stop flag again before processing action
                            if self.stop_flag:
                                break
                            
                            # ----- handle interval sleep -----
                            delay = act.timestamp * self.speed
                            
                            # Apply delay randomization if enabled for this action
                            if act.delay_randomization:
                                delay *= random.uniform(act.delay_min_multiplier, act.delay_max_multiplier)
                            
                            if delay > 30:
                                print(f"Delay: {delay}")
                            self._sleep(delay)
                            
                            # Check stop flag after sleep
                            if self.stop_flag:
                                break
                            
                            # Update elapsed time
                            self.elapsed_time += delay
                            
                            # ----- perform action -----
                            if self.stop_flag:
                                break
                            if act.type == ActionType.MOUSE:
                                if self._do_mouse(act) == 0:
                                    # Reset to start of actions loop
                                    action_index = 0
                                    continue
                            else:
                                self._do_key(act)  # type: ignore[arg-type]
                            
                            # Move to next action
                            action_index += 1

                        # Check stop flag before moving to next iteration
                        if self.stop_flag:
                            break
                            
                        self._sleep(0.2)
                    if self.stop_flag:
                        break

                if self.stop_flag:
                    break
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
            # Check stop flag more frequently during long delays
            if elapsed > 1.0 and self.stop_flag:
                break

    def _do_mouse(self, act: MouseAction):
        x, y = act.position
        if act.color_toggle:
            shot = "_area.png"
            area_x, area_y, area_w, area_h = act.color_area
            screenshot_area(area_x, area_y, area_w, area_h, shot)
            #found = find_color_mean(shot, act.color, offset=(area_x, area_y), tolerance=0)
            #clusters = find_color_clusters(shot, act.color, offset=(area_x, area_y), tolerance=0)
            clusters = find_color_connected_clusters(shot, act.color, offset=(area_x, area_y), tolerance=act.color_tolerance)
            
            if clusters:
                # Find the cluster closest to the player position
                closest_cluster = find_closest_cluster(clusters, player_pos)
                if closest_cluster:
                    x, y = closest_cluster
                    print(f"Color found: {act.color} at {x}, {y} (closest to player)")
                else:
                    # Fallback to random cluster if something goes wrong
                    x, y = clusters[random.randint(0, len(clusters) - 1)]
                    print(f"Color found: {act.color} at {x}, {y} (random)")
            else:
                print(f"Color not found: {act.color}")
                return 0

        MOUSE.position = (x, y)
        time.sleep(0.06)
        MOUSE.click(_BUTTON_MAP.get(act.button, Button.left))
        return 1

    def _do_key(self, act: KeyboardAction):
        key_obj = _to_key(act.key)
        if not key_obj:
            return
        time.sleep(0.01)
        KEYS.press(key_obj)
        time.sleep(0.06)
        KEYS.release(key_obj)