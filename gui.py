import threading
import signal
import sys
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pynput.keyboard import Key, KeyCode

from player import ActionPlayer
from recorder import ActionRecorder
from script_manager import ScriptManager
from actions import ActionType, MouseAction, KeyboardAction
from utils import SCRIPTS_DIR, PROGRAMS_DIR

DEFAULT_COLOR_AREA_WIDTH = 300
DEFAULT_COLOR_AREA_HEIGHT = 500


def to_key(key_str, default):
    """Convert a string to a pynput Key or KeyCode, or fallback to default."""
    if not key_str:
        return default
    key_str = key_str.lower()
    # Try named key
    if hasattr(Key, key_str):
        return getattr(Key, key_str)
    # Otherwise, treat as single character
    if len(key_str) == 1:
        return KeyCode.from_char(key_str)
    return default


class ProgressDisplay(ttk.Frame):
    """Real-time progress display for playback, now as a Frame."""
    def __init__(self, parent, player, params, sequence, on_close=None):
        super().__init__(parent)
        self.player = player
        self.sequence = sequence
        self.param_vars = {}
        self.on_close = on_close

        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Playback Status", font=(None, 14, 'bold')).pack(pady=(0,10))

        # Controls
        ctl = ttk.LabelFrame(main, text="Controls", padding=10)
        ctl.pack(fill=tk.X)
        self.param_vars['speed'] = tk.DoubleVar(value=params.get('speed',1.0))
        ttk.Label(ctl, text="Speed").grid(row=0, column=0)
        ttk.Entry(ctl, textvariable=self.param_vars['speed'], width=8).grid(row=0, column=1)

        # Key bindings with 'Set' buttons
        keys = ['pause_key','stop_key','skip_key']
        self._key_setters = {}
        for i,key in enumerate(keys, start=1):
            ttk.Label(ctl, text=key.replace('_',' ').title()).grid(row=i, column=0)
            var = tk.StringVar(value=params.get(key, ''))
            entry = ttk.Entry(ctl, textvariable=var, width=8)
            entry.grid(row=i, column=1)
            self.param_vars[key] = var
            set_btn = ttk.Button(ctl, text="Set", width=5)
            set_btn.grid(row=i, column=2, padx=(2,0))
            def make_setter(k=key, v=var, e=entry, b=set_btn):
                def on_set():
                    b.config(text="Press key...", state=tk.DISABLED)
                    e.config(state=tk.DISABLED)
                    def on_key(event):
                        # Use event.keysym for readable name
                        v.set(event.keysym)
                        b.config(text="Set", state=tk.NORMAL)
                        e.config(state=tk.NORMAL)
                        b.master.unbind_all('<Key>')
                        return "break"  # Prevent further handling of this key event
                    b.master.bind_all('<Key>', on_key)
                return on_set
            set_btn.config(command=make_setter())
            self._key_setters[key] = set_btn

        # Loop option (moved below key bindings)
        self.param_vars['loop'] = tk.BooleanVar(value=params.get('loop',False))
        ttk.Checkbutton(ctl, text="Loop", variable=self.param_vars['loop']).grid(row=4, column=0, columnspan=2, pady=(8,0), sticky="w")

        apply_btn = ttk.Button(ctl, text="Apply", command=self.apply)
        apply_btn.grid(row=5, column=0, columnspan=3, pady=5)

        # Status
        self.status = ttk.Label(main, text="Ready", font=(None,12,'bold'), foreground='green')
        self.status.pack(pady=10)
        self.countdown = ttk.Label(main, text="0.0s", font=(None,16,'bold'))
        self.countdown.pack(pady=5)

        self.listbox = tk.Listbox(main)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.update_list()

        self.countdown_job = None
        self.update()

        # Add a Close button to return to main UI
        ttk.Button(main, text="Close", command=self._close).pack(pady=10)

    def apply(self):
        if self.player:
            self.player.speed = self.param_vars['speed'].get()
            self.player.loop_until_stopped = self.param_vars['loop'].get()
            self.player.update_keys(
                pause_key=to_key(self.param_vars['pause_key'].get(), Key.space),
                stop_key=self.param_vars['stop_key'].get(),
                skip_pause_key=self.param_vars['skip_key'].get()
            )
        # Remove focus from the Apply button and window
        self.focus_set()

    def update_list(self):
        self.listbox.delete(0,tk.END)
        current = getattr(self.player,'current_script_name','')
        for name, iters in self.sequence:
            label = f"{name} ({iters})"
            if name==current:
                label = f"▶ {label}"
            self.listbox.insert(tk.END,label)

    def start_countdown(self, delay):
        if self.countdown_job:
            self.after_cancel(self.countdown_job)
        def tick(rem):
            self.countdown.config(text=f"{rem:.1f}s")
            if rem>0:
                self.countdown_job = self.after(100, tick, rem-0.1)
        tick(delay)

    def update_progress(self, progress_info):
        # Update the display with new progress information
        # Status
        is_paused = progress_info.get('is_paused', False)
        is_stopped = progress_info.get('is_stopped', False)
        if is_stopped:
            self.status.config(text="Stopped", foreground="red")
        elif is_paused:
            self.status.config(text="Paused", foreground="orange")
        else:
            self.status.config(text="Running", foreground="blue")
        # Countdown
        action_delay = progress_info.get('action_delay', 0.0)
        if action_delay > 0:
            self.start_countdown(action_delay)
        else:
            self.countdown.config(text="0.0s")
        # Update listbox highlight
        self.update_list()
        # Force update
        self.update_idletasks()

    def _close(self):
        if self.player:
            self.player.stop_playback()
        if self.countdown_job:
            self.after_cancel(self.countdown_job)
        if self.on_close:
            self.on_close()
        self.destroy()


class ScriptRunnerGUI:
    """Main application GUI for recording and playback."""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ToolForge Runner")
        self.mgr = ScriptManager()
        self._load_settings()
        self._setup_signals()
        self._build_main()

    def _load_settings(self):
        path = Path(__file__).parent / 'settings.json'
        defaults = dict(
            color_area_width=DEFAULT_COLOR_AREA_WIDTH,
            color_area_height=DEFAULT_COLOR_AREA_HEIGHT,
            color_toggle_key='shift', stop_key='tab',
            replay_speed=1.0, pause_key='space', replay_stop_key='s', skip_pause_key='n',
            loop_until_stopped=False
        )
        if path.exists():
            try:
                defaults.update(json.loads(path.read_text()))
            except json.JSONDecodeError:
                pass
        self.settings = defaults

    def _save_settings(self):
        path = Path(__file__).parent / 'settings.json'
        path.write_text(json.dumps(self.settings, indent=4))

    def _setup_signals(self):
        signal.signal(signal.SIGINT, self._exit)
        signal.signal(signal.SIGTERM, self._exit)

    def _build_main(self):
        for w in self.root.winfo_children(): w.destroy()
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        btns = dict(play=self._run_mode, create=self._create_mode,
                    edit=self._edit_mode, options=self._options_mode)
        self.mode = 'play'
        bar = ttk.Frame(frm)
        bar.pack(fill=tk.X)
        for name, cmd in btns.items():
            ttk.Button(bar, text=name.title(), command=lambda m=name: self._switch(m)).pack(side=tk.LEFT)
        self.content = ttk.Frame(frm, padding=10)
        self.content.pack(fill=tk.BOTH, expand=True)
        self._draw()

    def _switch(self, mode):
        # If a ProgressDisplay is active, stop playback and clean up
        for w in self.content.winfo_children():
            if isinstance(w, ProgressDisplay):
                if hasattr(w, 'player') and w.player:
                    w.player.stop_playback()
                w.destroy()
        self.mode=mode
        self._draw()

    def _draw(self):
        for w in self.content.winfo_children(): w.destroy()
        getattr(self, f"_{self.mode}_mode")()

    def _play_mode(self):
        progs = self.mgr.list_programs()
        if not progs:
            ttk.Label(self.content, text="No programs").pack()
            return
        lb = tk.Listbox(self.content)
        for p in progs:
            lb.insert(tk.END, p[:-5] if p.endswith('.json') else p)
        lb.pack(fill=tk.BOTH,expand=True)
        def start():
            sel=lb.curselection()
            if not sel: return
            prog=progs[sel[0]]
            seq=self.mgr.load_program(prog)
            self._execute(seq, prog)
        def delete_program():
            sel=lb.curselection()
            if not sel: return
            prog=progs[sel[0]]
            display_name = prog[:-5] if prog.endswith('.json') else prog
            if messagebox.askyesno("Delete Program", f"Delete program '{display_name}'?"):
                import os
                try:
                    os.remove(str(PROGRAMS_DIR / prog))
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to delete: {e}")
                # Refresh list and update progs
                lb.delete(0, tk.END)
                progs[:] = self.mgr.list_programs()
                for p in progs:
                    lb.insert(tk.END, p[:-5] if p.endswith('.json') else p)
        btn_frame = ttk.Frame(self.content)
        btn_frame.pack()
        ttk.Button(btn_frame, text="Run", command=start).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(btn_frame, text="Delete", command=delete_program).pack(side=tk.LEFT, padx=5, pady=5)

    def _create_mode(self):
        # Clear content
        for w in self.content.winfo_children(): w.destroy()
        # Main container
        main_container = ttk.Frame(self.content)
        main_container.pack(expand=True, fill=tk.BOTH)

        # --- Left: Available scripts and record ---
        left = ttk.Frame(main_container)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        ttk.Label(left, text="Available Scripts", font=("Arial", 12, "bold")).pack()
        available_lb = tk.Listbox(left, width=40, height=15, exportselection=0)
        available_lb.pack(pady=5)
        scripts = self.mgr.list_scripts()
        for s in scripts:
            available_lb.insert(tk.END, s[:-5] if s.endswith('.json') else s)
        # Script name entry
        ttk.Label(left, text="New Script Name:").pack(pady=(10,0))
        script_name_var = tk.StringVar(value="test")
        script_name_entry = ttk.Entry(left, textvariable=script_name_var, width=20)
        script_name_entry.pack(pady=(0,10))
        # Toast label (hidden by default)
        toast = ttk.Label(left, text="", background="#222", foreground="white", font=("Arial", 11, "bold"))
        toast.pack_forget()
        def show_toast(msg):
            toast.config(text=msg)
            toast.pack(after=record_btn, pady=(0,10))
            toast.lift()
            toast.after(2000, lambda: toast.pack_forget())
        def record_script():
            self._record_with_name(script_name_var.get(), show_toast)
            available_lb.delete(0, tk.END)
            scripts[:] = self.mgr.list_scripts()
            for s in scripts:
                available_lb.insert(tk.END, s[:-5] if s.endswith('.json') else s)
        record_btn = ttk.Button(left, text="Record Script", command=record_script)
        record_btn.pack(pady=10)

        # --- Middle: Add/Remove buttons ---
        mid = ttk.Frame(main_container)
        mid.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        selected_scripts = []
        def add_script():
            sel = available_lb.curselection()
            if sel:
                idx = sel[0]
                name = scripts[idx]  # always use real filename
                selected_scripts.append({'name': name, 'iterations': 1})
                selected_lb.insert(tk.END, f"{name[:-5] if name.endswith('.json') else name} (1)")
        def remove_script():
            sel = selected_lb.curselection()
            if sel:
                selected_lb.delete(sel[0])
                selected_scripts.pop(sel[0])
        # Add extra space above the buttons to lower them
        
        ttk.Button(mid, text=">", command=add_script, width=4).pack(pady=(70,5))
        ttk.Button(mid, text="<", command=remove_script, width=4).pack(pady=5)

        # --- Right: Selected scripts ---
        right = ttk.Frame(main_container)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0))
        ttk.Label(right, text="Selected Scripts", font=("Arial", 12, "bold")).pack()
        selected_lb = tk.Listbox(right, width=40, height=15)
        selected_lb.pack(pady=5)
        def move_up():
            sel = selected_lb.curselection()
            if sel and sel[0] > 0:
                idx = sel[0]
                selected_scripts[idx], selected_scripts[idx-1] = selected_scripts[idx-1], selected_scripts[idx]
                txt = selected_lb.get(idx)
                selected_lb.delete(idx)
                selected_lb.insert(idx-1, txt)
                selected_lb.select_set(idx-1)
        def move_down():
            sel = selected_lb.curselection()
            if sel and sel[0] < selected_lb.size()-1:
                idx = sel[0]
                selected_scripts[idx], selected_scripts[idx+1] = selected_scripts[idx+1], selected_scripts[idx]
                txt = selected_lb.get(idx)
                selected_lb.delete(idx)
                selected_lb.insert(idx+1, txt)
                selected_lb.select_set(idx+1)
        def set_iterations():
            sel = selected_lb.curselection()
            if sel:
                idx = sel[0]
                info = selected_scripts[idx]
                val = simpledialog.askinteger("Iterations", f"How many times should '{info['name']}' be run?", initialvalue=info['iterations'])
                if val is not None:
                    info['iterations'] = val
                    selected_lb.delete(idx)
                    selected_lb.insert(idx, f"{info['name']} ({val})")
                    selected_lb.select_set(idx)
        ttk.Button(right, text="Move Up", command=move_up, width=15).pack(pady=5)
        ttk.Button(right, text="Move Down", command=move_down, width=15).pack(pady=5)
        ttk.Button(right, text="Set Iterations", command=set_iterations, width=15).pack(pady=20)
        # --- Program name entry and toast under selected scripts ---
        program_name_var = tk.StringVar(value="my_program")
        ttk.Label(right, text="Program Name:").pack(pady=(10,0))
        program_name_entry = ttk.Entry(right, textvariable=program_name_var, width=20)
        program_name_entry.pack(pady=(0,10))
        program_toast = ttk.Label(right, text="", background="#222", foreground="white", font=("Arial", 11, "bold"))
        program_toast.pack_forget()
        def show_program_toast(msg):
            program_toast.config(text=msg)
            program_toast.pack(after=program_name_entry, pady=(0,10))
            program_toast.lift()
            program_toast.after(2000, lambda: program_toast.pack_forget())
        def save_program():
            if not selected_scripts:
                messagebox.showinfo("No Scripts", "No scripts selected to save.")
                return
            sequence = [(info['name'], info['iterations']) for info in selected_scripts]
            out_name = program_name_var.get().strip()
            if not out_name:
                messagebox.showinfo("No Name", "Please enter a program name.")
                return
            if not out_name.endswith(".json"):
                out_name += ".json"
            self.mgr.save_program(sequence, out_name)
            show_program_toast(f"Program saved as '{out_name}'")
            self._switch('play')
        ttk.Button(right, text="Save Program", command=save_program, width=15).pack(pady=10)

    def _record_with_name(self, script_name, toast_callback=None):
        # Use current settings
        color_key_str = self.settings['color_toggle_key']
        stop_key_str = self.settings['stop_key']
        width = self.settings['color_area_width']
        height = self.settings['color_area_height']
        from pynput.keyboard import Key
        def to_key(key_str, default):
            if not key_str:
                return default
            key_str = key_str.lower()
            try:
                return getattr(Key, key_str)
            except AttributeError:
                return key_str
        color_key = to_key(color_key_str, Key.shift_l)
        stop_key = to_key(stop_key_str, Key.tab)
        # --- Custom Recording Info Window ---
        info_win = tk.Toplevel(self.root)
        info_win.title("Recording Started")
        info_win.transient(self.root)
        info_win.grab_set()
        info_win.resizable(False, False)
        recording_started = {'value': False}
        frame = ttk.Frame(info_win, padding=30)
        frame.pack()
        ttk.Label(frame, text="Recording Started", font=("Arial", 16, "bold")).pack(pady=(0, 15))
        ttk.Label(frame, text=f"Press ").pack(anchor="w")
        ttk.Label(frame, text=f"  {stop_key}  ", font=("Arial", 12, "bold"), foreground="red").pack(anchor="w")
        ttk.Label(frame, text="to stop recording.").pack(anchor="w")
        ttk.Label(frame, text=f"Press ").pack(anchor="w", pady=(10,0))
        ttk.Label(frame, text=f"  {color_key}  ", font=("Arial", 12, "bold"), foreground="blue").pack(anchor="w")
        ttk.Label(frame, text="before a mouse click to record pixel color.").pack(anchor="w")
        def start_recording():
            recording_started['value'] = True
            info_win.destroy()
            self.root.lower()
        ttk.Button(frame, text="Start Recording", command=start_recording).pack(pady=(20,0))
        def on_info_close():
            recording_started['value'] = False
            info_win.destroy()
        info_win.protocol("WM_DELETE_WINDOW", on_info_close)
        info_win.wait_window()
        if not recording_started['value']:
            return
        try:
            rec = ActionRecorder(
                color_toggle_key=color_key,
                stop_recording_key=stop_key,
                color_area_width=width,
                color_area_height=height
            )
            self.current_recorder = rec
            rec.record()
        except Exception as e:
            messagebox.showerror("Recording Error", f"An error occurred during recording: {e}")
        finally:
            self.current_recorder = None
        # Save script with the provided name
        if hasattr(rec, '_actions') and rec._actions:
            try:
                rec.save(script_name)
                if toast_callback:
                    toast_callback(f'Script saved as "{script_name}"')
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save script: {e}")
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))

    def _edit_mode(self):
        # Clear content
        for w in self.content.winfo_children(): w.destroy()
        main = ttk.Frame(self.content, padding=10)
        main.pack(expand=True, fill=tk.BOTH)
        # Left: script list
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        ttk.Label(left, text="Available Scripts", font=("Arial", 12, "bold")).pack()
        scripts_lb = tk.Listbox(left, width=40, height=15, exportselection=0)
        scripts_lb.pack(pady=5)
        scripts = self.mgr.list_scripts()
        for s in scripts:
            scripts_lb.insert(tk.END, s[:-5] if s.endswith('.json') else s)
        # Ensure these are defined before the functions that use nonlocal
        current_actions = []
        current_script_name = None
        # --- Define actions_lb Listbox for actions display ---
        actions_lb = tk.Listbox(left, width=60, height=15, selectmode=tk.SINGLE, exportselection=0)
        actions_lb.pack(pady=5, fill=tk.BOTH, expand=True)
        
        # Action management buttons
        action_buttons_frame = ttk.Frame(left)
        action_buttons_frame.pack(pady=5)
        
        def add_action():
            # Create a simple dialog to choose action type
            add_win = tk.Toplevel(self.root)
            add_win.title("Add")
            add_win.transient(self.root)
            add_win.grab_set()
            
            frame = ttk.Frame(add_win, padding=20)
            frame.pack()
            
            ttk.Label(frame, text="Select Action Type:", font=("Arial", 12, "bold")).pack(pady=(0, 10))
            
            def create_mouse_action():
                add_win.destroy()
                # Show instructions for mouse click
                mouse_win = tk.Toplevel(self.root)
                mouse_win.title("Record Mouse Click")
                mouse_win.transient(self.root)
                mouse_win.grab_set()
                
                mouse_frame = ttk.Frame(mouse_win, padding=20)
                mouse_frame.pack()
                
                ttk.Label(mouse_frame, text="Click where you want to add the mouse action", font=("Arial", 12, "bold")).pack(pady=(0, 10))
                ttk.Label(mouse_frame, text="The window will close automatically after your click").pack(pady=(0, 20))
                
                mouse_pos = {'x': None, 'y': None}
                
                def on_mouse_click(event):
                    # Get global screen coordinates
                    mouse_pos['x'] = mouse_win.winfo_pointerx()
                    mouse_pos['y'] = mouse_win.winfo_pointery()
                    mouse_win.destroy()
                    
                    # Create the mouse action with recorded position
                    new_action = MouseAction(
                        timestamp=1.0,
                        button="Button.left",
                        position=(mouse_pos['x'], mouse_pos['y']),
                        color_toggle=False,
                        color=None,
                        color_area=None,
                        color_tolerance=1,
                        delay_randomization=False,
                        delay_min_multiplier=1.0,
                        delay_max_multiplier=1.5
                    )
                    current_actions.append(new_action)
                    refresh_actions_display()
                
                mouse_win.bind('<Button-1>', on_mouse_click)
                mouse_win.focus_set()
                
                # Make window stay on top and wait for click
                mouse_win.attributes('-topmost', True)
                mouse_win.wait_window()
            
            def create_keyboard_action():
                add_win.destroy()
                # Show instructions for keyboard input
                key_win = tk.Toplevel(self.root)
                key_win.title("Record Keyboard Press")
                key_win.transient(self.root)
                key_win.grab_set()
                
                key_frame = ttk.Frame(key_win, padding=20)
                key_frame.pack()
                
                ttk.Label(key_frame, text="Press the key you want to add", font=("Arial", 12, "bold")).pack(pady=(0, 10))
                ttk.Label(key_frame, text="The window will close automatically after your key press").pack(pady=(0, 20))
                
                recorded_key = {'key': None}
                
                def on_key_press(event):
                    # Convert the key event to a string representation
                    if event.keysym in ['space', 'tab', 'enter', 'escape', 'backspace', 'delete']:
                        key_str = f"Key.{event.keysym}"
                    elif len(event.char) == 1:
                        key_str = f"'{event.char}'"
                    else:
                        key_str = f"Key.{event.keysym.lower()}"
                    
                    recorded_key['key'] = key_str
                    key_win.destroy()
                    
                    # Create the keyboard action with recorded key
                    new_action = KeyboardAction(
                        timestamp=1.0,
                        key=recorded_key['key'],
                        delay_randomization=False,
                        delay_min_multiplier=1.0,
                        delay_max_multiplier=1.5
                    )
                    current_actions.append(new_action)
                    refresh_actions_display()
                
                key_win.bind('<Key>', on_key_press)
                key_win.focus_set()
                
                # Make window stay on top and wait for key press
                key_win.attributes('-topmost', True)
                key_win.wait_window()
            
            ttk.Button(frame, text="Mouse Click", command=create_mouse_action, width=20).pack(pady=5)
            ttk.Button(frame, text="Keyboard Press", command=create_keyboard_action, width=20).pack(pady=5)
            ttk.Button(frame, text="Cancel", command=add_win.destroy, width=20).pack(pady=5)
        
        def delete_action():
            sel = actions_lb.curselection()
            if sel:
                idx = sel[0]
                if messagebox.askyesno("Action", "Delete this action?"):
                    current_actions.pop(idx)
                    refresh_actions_display()
        
        def move_action_up():
            sel = actions_lb.curselection()
            if sel and sel[0] > 0:
                idx = sel[0]
                current_actions[idx], current_actions[idx-1] = current_actions[idx-1], current_actions[idx]
                refresh_actions_display()
                actions_lb.select_set(idx-1)
        
        def move_action_down():
            sel = actions_lb.curselection()
            if sel and sel[0] < len(current_actions) - 1:
                idx = sel[0]
                current_actions[idx], current_actions[idx+1] = current_actions[idx+1], current_actions[idx]
                refresh_actions_display()
                actions_lb.select_set(idx+1)
        
        ttk.Button(action_buttons_frame, text="Add", command=add_action, width=15).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_buttons_frame, text="Delete", command=delete_action, width=15).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_buttons_frame, text="^", command=move_action_up, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_buttons_frame, text="v", command=move_action_down, width=10).pack(side=tk.LEFT, padx=2)
        
        def save_script():
            if current_script_name and current_actions:
                try:
                    from utils import save_json
                    script_path = Path(__file__).parent / "scripts" / current_script_name
                    actions_data = [a.__dict__ for a in current_actions]
                    save_json(actions_data, script_path)
                    messagebox.showinfo("Success", f"Script '{current_script_name}' saved successfully!")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save script: {e}")
            else:
                messagebox.showwarning("Warning", "No script loaded or no actions to save.")
        
        ttk.Button(action_buttons_frame, text="Save Script", command=save_script, width=15).pack(side=tk.LEFT, padx=2)
        
        def refresh_scripts_list():
            scripts_lb.delete(0, tk.END)
            scripts[:] = self.mgr.list_scripts()
            for s in scripts:
                scripts_lb.insert(tk.END, s[:-5] if s.endswith('.json') else s)

        def refresh_actions_display():
            """Refresh the actions listbox with current actions in memory"""
            actions_lb.delete(0, tk.END)
            for action in current_actions:
                if action.type == ActionType.MOUSE:
                    button_short = action.button.replace("Button.", "").title()
                    base_text = f"Mouse {button_short} ({action.position[0]},{action.position[1]}) | Delay: {action.timestamp:.2f}s"
                    if action.color_toggle:
                        area_info = f" | Detect {action.color}"
                        tolerance_info = f" (tol:{action.color_tolerance})"
                        base_text += area_info + tolerance_info
                    if action.delay_randomization:
                        random_info = f" | Random: {action.delay_min_multiplier:.1f}-{action.delay_max_multiplier:.1f}x"
                        base_text += random_info
                    actions_lb.insert(tk.END, base_text)
                else:
                    base_text = f"Keyboard {action.key} | Delay: {action.timestamp:.2f}s"
                    if action.delay_randomization:
                        random_info = f" | Random: {action.delay_min_multiplier:.1f}-{action.delay_max_multiplier:.1f}x"
                        base_text += random_info
                    actions_lb.insert(tk.END, base_text)

        def display_script_actions(event=None):
            nonlocal current_actions, current_script_name
            sel = scripts_lb.curselection()
            if sel:
                idx = sel[0]
                script_name = scripts[idx]  # Always use real filename
                current_script_name = script_name
                try:
                    actions = self.mgr.load_script(script_name)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to load script {script_name}: {e}")
                    actions = []
                current_actions = actions
                refresh_actions_display()
        scripts_lb.bind('<<ListboxSelect>>', display_script_actions)
        def edit_action(event=None):
            sel = actions_lb.curselection()
            if not sel:
                return
            idx = sel[0]
            action = current_actions[idx]
            current_time = action.timestamp
            edit_win = tk.Toplevel(self.root)
            edit_win.title("Edit Action")
            frame = ttk.Frame(edit_win, padding=20)
            frame.pack(expand=True, fill=tk.BOTH)
            ttk.Label(frame, text="Time (seconds):").pack(pady=5)
            time_var = tk.StringVar(value=str(current_time))
            ttk.Entry(frame, textvariable=time_var).pack(pady=5)
            
            # Delay randomization controls
            ttk.Label(frame, text="Delay Randomization:", font=("Arial", 10, "bold")).pack(pady=(15,5))
            delay_randomization_var = tk.BooleanVar(value=getattr(action, 'delay_randomization', False))
            ttk.Checkbutton(frame, text="Enable delay randomization", variable=delay_randomization_var).pack()
            
            # Min/max multiplier inputs (always visible)
            random_frame = ttk.Frame(frame)
            ttk.Label(random_frame, text="Min multiplier:").pack(side=tk.LEFT)
            min_mult_var = tk.StringVar(value=str(getattr(action, 'delay_min_multiplier', 1.0)))
            ttk.Entry(random_frame, textvariable=min_mult_var, width=8).pack(side=tk.LEFT, padx=5)
            ttk.Label(random_frame, text="Max multiplier:").pack(side=tk.LEFT, padx=(10,0))
            max_mult_var = tk.StringVar(value=str(getattr(action, 'delay_max_multiplier', 1.5)))
            ttk.Entry(random_frame, textvariable=max_mult_var, width=8).pack(side=tk.LEFT, padx=5)
            random_frame.pack(pady=5)
            
            if action.type == ActionType.MOUSE:
                ttk.Label(frame, text="Mouse Action Properties", font=("Arial", 10, "bold")).pack(pady=(15,5))
                color_toggle_var = tk.BooleanVar(value=action.color_toggle)
                ttk.Checkbutton(frame, text="Record pixel color", variable=color_toggle_var).pack()
                color_area_frame = ttk.Frame(frame)
                ttk.Label(color_area_frame, text="Color Search Area:").pack()
                area_width_var = tk.StringVar(value=str(action.color_area[2] if action.color_area else 300))
                area_height_var = tk.StringVar(value=str(action.color_area[3] if action.color_area else 500))
                width_frame = ttk.Frame(color_area_frame)
                ttk.Label(width_frame, text="Width:").pack(side=tk.LEFT)
                ttk.Entry(width_frame, textvariable=area_width_var, width=10).pack(side=tk.LEFT, padx=5)
                width_frame.pack()
                height_frame = ttk.Frame(color_area_frame)
                ttk.Label(height_frame, text="Height:").pack(side=tk.LEFT)
                ttk.Entry(height_frame, textvariable=area_height_var, width=10).pack(side=tk.LEFT, padx=5)
                height_frame.pack()
                ttk.Label(color_area_frame, text="Edit Color (RGB):").pack(pady=5)
                color_frame = ttk.Frame(color_area_frame)
                r_var = tk.StringVar(value=str(action.color[0] if action.color else 0))
                g_var = tk.StringVar(value=str(action.color[1] if action.color else 0))
                b_var = tk.StringVar(value=str(action.color[2] if action.color else 0))
                ttk.Label(color_frame, text="R:").pack(side=tk.LEFT)
                ttk.Entry(color_frame, textvariable=r_var, width=5).pack(side=tk.LEFT, padx=2)
                ttk.Label(color_frame, text="G:").pack(side=tk.LEFT)
                ttk.Entry(color_frame, textvariable=g_var, width=5).pack(side=tk.LEFT, padx=2)
                ttk.Label(color_frame, text="B:").pack(side=tk.LEFT)
                ttk.Entry(color_frame, textvariable=b_var, width=5).pack(side=tk.LEFT, padx=2)
                color_frame.pack()
                
                # Color tolerance setting
                tolerance_frame = ttk.Frame(color_area_frame)
                ttk.Label(tolerance_frame, text="Color tolerance:").pack(side=tk.LEFT)
                tolerance_var = tk.StringVar(value=str(getattr(action, 'color_tolerance', 1)))
                ttk.Entry(tolerance_frame, textvariable=tolerance_var, width=5).pack(side=tk.LEFT, padx=5)
                ttk.Label(tolerance_frame, text="(0-255, higher = more flexible)").pack(side=tk.LEFT, padx=5)
                tolerance_frame.pack(pady=5)
                
                # Clustering parameters
                # --- Color preview rectangle ---
                preview_canvas = tk.Canvas(color_area_frame, width=30, height=20, bg="white", highlightthickness=1, highlightbackground="#888")
                preview_canvas.pack(pady=5)
                def update_color_preview(*args):
                    try:
                        r = int(r_var.get())
                        g = int(g_var.get())
                        b = int(b_var.get())
                        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                            color = f'#{r:02x}{g:02x}{b:02x}'
                            preview_canvas.delete("all")
                            preview_canvas.create_rectangle(0, 0, 30, 20, fill=color, outline="black")
                        else:
                            preview_canvas.delete("all")
                    except Exception:
                        preview_canvas.delete("all")
                r_var.trace_add('write', update_color_preview)
                g_var.trace_add('write', update_color_preview)
                b_var.trace_add('write', update_color_preview)
                update_color_preview()
                color_area_frame.pack(pady=5)
            def save_changes():
                try:
                    new_time = float(time_var.get())
                    delta_time = new_time - current_time
                    action.timestamp = new_time
                    # Handle delay randomization
                    action.delay_randomization = delay_randomization_var.get()
                    if delay_randomization_var.get():
                        min_mult = float(min_mult_var.get())
                        max_mult = float(max_mult_var.get())
                        if min_mult > max_mult:
                            messagebox.showerror("Error", "Min multiplier must be less than or equal to max multiplier")
                            return
                        action.delay_min_multiplier = min_mult
                        action.delay_max_multiplier = max_mult
                    
                    if action.type == ActionType.MOUSE:
                        action.color_toggle = color_toggle_var.get()
                        if action.color_toggle:
                            width = int(area_width_var.get())
                            height = int(area_height_var.get())
                            x, y = action.position
                            action.color_area = (x - width // 2, y - height // 2, width, height)
                            r = int(r_var.get())
                            g = int(g_var.get())
                            b = int(b_var.get())
                            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                                action.color = (r, g, b)
                            else:
                                messagebox.showerror("Error", "Color values must be between 0 and 255")
                                return
                        
                        # Save color tolerance (only for mouse actions)
                        try:
                            action.color_tolerance = int(tolerance_var.get())
                            if not 0 <= action.color_tolerance <= 255:
                                messagebox.showerror("Error", "Color tolerance must be between 0 and 255")
                                return
                        except ValueError:
                            messagebox.showerror("Error", "Color tolerance must be an integer")
                            return
                    # Save to disk
                    if current_script_name:
                        try:
                            from utils import save_json
                            script_path = Path(__file__).parent / "scripts" / current_script_name
                            actions_data = [a.__dict__ for a in current_actions]
                            save_json(actions_data, script_path)
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to save script {current_script_name}: {e}")
                    # --- Reload from disk and update UI ---
                    if current_script_name:
                        try:
                            actions = self.mgr.load_script(current_script_name)
                            current_actions.clear()
                            current_actions.extend(actions)
                            refresh_actions_display()
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to reload script: {e}")
                    edit_win.destroy()
                except ValueError:
                    messagebox.showerror("Error", "Invalid time value")
            ttk.Button(frame, text="Save Changes", command=save_changes).pack(pady=10)
            ttk.Button(frame, text="Cancel", command=edit_win.destroy).pack(pady=5)
            edit_win.update_idletasks()
            edit_win.resizable(True, True)
        actions_lb.bind('<Double-Button-1>', edit_action)

        def delete_script():
            sel = scripts_lb.curselection()
            if not sel: return
            idx = sel[0]
            script = scripts[idx]
            display_name = script[:-5] if script.endswith('.json') else script
            if messagebox.askyesno("Delete Script", f"Delete script '{display_name}'?"):
                import os
                try:
                    os.remove(str(SCRIPTS_DIR / script))
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to delete: {e}")
                refresh_scripts_list()
        ttk.Button(left, text="Delete Script", command=delete_script).pack(pady=2)

    def _options_mode(self):
        # Refactored options panel: grouped into Recording and Replay settings side by side
        for w in self.content.winfo_children(): w.destroy()
        container = ttk.Frame(self.content)
        container.pack(fill=tk.BOTH, expand=True, pady=10)

        # --- Horizontal layout for settings ---
        settings_row = ttk.Frame(container)
        settings_row.pack(fill=tk.BOTH, expand=True)

        # --- Recording Settings ---
        rec_frame = ttk.LabelFrame(settings_row, text="Recording Settings", padding=15)
        rec_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=0)
        # Color Area
        ttk.Label(rec_frame, text="Color Area Dimensions:", font=("Arial", 10, "bold")).pack(pady=(0, 5))
        ttk.Label(rec_frame, text=f"Width: {self.settings['color_area_width']}").pack(anchor="w")
        ttk.Label(rec_frame, text=f"Height: {self.settings['color_area_height']}").pack(anchor="w")
        ttk.Button(rec_frame, text="Change Color Area Size", command=self._change_color_area_size).pack(pady=5)
        # Key Bindings (Recording)
        ttk.Label(rec_frame, text="Key Bindings:", font=("Arial", 10, "bold")).pack(pady=(10, 5))
        ttk.Label(rec_frame, text=f"Color Toggle Key: {self.settings['color_toggle_key']}").pack(anchor="w")
        ttk.Button(rec_frame, text="Change Color Toggle Key", command=self._change_color_toggle_key).pack(pady=5)
        ttk.Label(rec_frame, text=f"Stop Recording Key: {self.settings['stop_key']}").pack(anchor="w")
        ttk.Button(rec_frame, text="Change Stop Recording Key", command=self._change_stop_key).pack(pady=5)

        # --- Replay Settings ---
        rep_frame = ttk.LabelFrame(settings_row, text="Replay Settings", padding=15)
        rep_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=0)
        # Key Bindings (Replay)
        ttk.Label(rep_frame, text="Key Bindings:", font=("Arial", 10, "bold")).pack(pady=(0, 5))
        ttk.Label(rep_frame, text=f"Pause/Resume Key: {self.settings['pause_key']}").pack(anchor="w")
        ttk.Button(rep_frame, text="Change Pause/Resume Key", command=self._change_pause_key).pack(pady=5)
        ttk.Label(rep_frame, text=f"Stop Replay Key: {self.settings['replay_stop_key']}").pack(anchor="w")
        ttk.Button(rep_frame, text="Change Stop Replay Key", command=self._change_replay_stop_key).pack(pady=5)
        ttk.Label(rep_frame, text=f"Skip Pause Key: {self.settings['skip_pause_key']}").pack(anchor="w")
        ttk.Button(rep_frame, text="Change Skip Pause Key", command=self._change_skip_pause_key).pack(pady=5)
        # Replay Speed
        ttk.Label(rep_frame, text="Replay Speed:", font=("Arial", 10, "bold")).pack(pady=(10, 5))
        ttk.Label(rep_frame, text=f"Current Speed: {self.settings['replay_speed']}").pack(anchor="w")
        speed_var = tk.StringVar(value=str(self.settings['replay_speed']))
        ttk.Entry(rep_frame, textvariable=speed_var, width=10).pack(pady=5)
        def set_speed():
            try:
                val = float(speed_var.get())
                self.settings['replay_speed'] = val
                self._save_settings()
                messagebox.showinfo("Settings Saved", f"Replay speed changed to {val}")
                self._options_mode()
            except Exception:
                messagebox.showerror("Error", "Invalid speed value")
        ttk.Button(rep_frame, text="Change Replay Speed", command=set_speed).pack(pady=5)
        # Loop
        ttk.Label(rep_frame, text="Loop Until Stopped:", font=("Arial", 10, "bold")).pack(pady=(10, 5))
        loop_var = tk.BooleanVar(value=self.settings['loop_until_stopped'])
        ttk.Checkbutton(rep_frame, text="Loop Scripts Until Stopped", variable=loop_var).pack(pady=5)
        def set_loop():
            self.settings['loop_until_stopped'] = loop_var.get()
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Loop Until Stopped set to {loop_var.get()}")
            self._options_mode()
        ttk.Button(rep_frame, text="Set Loop", command=set_loop).pack(pady=5)

        ttk.Button(container, text="Back to Main", command=lambda: self._switch('play')).pack(pady=10)

    def _execute(self, sequence, name):
        # open progress window as embedded frame
        import os
        # Ensure all script names in sequence have .json extension
        fixed_sequence = []
        for script_name, iters in sequence:
            if not script_name.endswith('.json'):
                script_name = script_name + '.json'
            fixed_sequence.append((script_name, iters))
        missing = []
        for script_name, _ in fixed_sequence:
            script_path = SCRIPTS_DIR / script_name
            if not script_path.exists():
                missing.append(script_name)
        if missing:
            messagebox.showerror("Missing Scripts", f"The following scripts are missing and playback cannot start:\n" + "\n".join(missing))
            return
        params = dict(
            speed=self.settings['replay_speed'],
            loop=self.settings['loop_until_stopped'],
            pause_key=self.settings['pause_key'],
            stop_key=self.settings['replay_stop_key'],
            skip_key=self.settings['skip_pause_key']
        )
        player = ActionPlayer(
            speed=params['speed'], pause_key=to_key(params['pause_key'],Key.space),
            stop_key=params['stop_key'], skip_pause_key=params['skip_key'],
            loop_until_stopped=params['loop']
        )
        # Clear content and show ProgressDisplay frame
        for w in self.content.winfo_children(): w.destroy()
        def restore_main():
            self._draw()
        disp = ProgressDisplay(self.content, player, params, fixed_sequence, on_close=restore_main)
        disp.pack(fill=tk.BOTH, expand=True)
        player.progress_callback = disp.update_progress
        th = threading.Thread(target=player.replay_program, args=(fixed_sequence,), daemon=True)
        th.start()

    def _exit(self, *args):
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()

    # --- Toolbar mode handlers for toolbar dict ---
    def _run_mode(self):
        self._play_mode()

    def _change_color_area_size(self):
        new_width = simpledialog.askinteger("Color Area Size", "Enter new width:", initialvalue=self.settings['color_area_width'])
        new_height = simpledialog.askinteger("Color Area Size", "Enter new height:", initialvalue=self.settings['color_area_height'])
        if new_width is not None and new_height is not None:
            self.settings['color_area_width'] = new_width
            self.settings['color_area_height'] = new_height
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Color area size changed to {new_width}x{new_height}")
            self._options_mode()

    def _change_color_toggle_key(self):
        new_key = simpledialog.askstring("Key Binding", "Enter new Color Toggle Key:", initialvalue=self.settings['color_toggle_key'])
        if new_key:
            self.settings['color_toggle_key'] = new_key
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Color Toggle Key changed to {new_key}")
            self._options_mode()

    def _change_stop_key(self):
        new_key = simpledialog.askstring("Key Binding", "Enter new Stop Replay Key:", initialvalue=self.settings['stop_key'])
        if new_key:
            self.settings['stop_key'] = new_key
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Stop Replay Key changed to {new_key}")
            self._options_mode()

    def _change_pause_key(self):
        new_key = simpledialog.askstring("Key Binding", "Enter new Pause/Resume Key:", initialvalue=self.settings['pause_key'])
        if new_key:
            self.settings['pause_key'] = new_key
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Pause/Resume Key changed to {new_key}")
            self._options_mode()

    def _change_replay_stop_key(self):
        new_key = simpledialog.askstring("Key Binding", "Enter new Stop Replay Key:", initialvalue=self.settings['replay_stop_key'])
        if new_key:
            self.settings['replay_stop_key'] = new_key
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Stop Replay Key changed to {new_key}")
            self._options_mode()

    def _change_skip_pause_key(self):
        new_key = simpledialog.askstring("Key Binding", "Enter new Skip Pause Key:", initialvalue=self.settings['skip_pause_key'])
        if new_key:
            self.settings['skip_pause_key'] = new_key
            self._save_settings()
            messagebox.showinfo("Settings Saved", f"Skip Pause Key changed to {new_key}")
            self._options_mode()