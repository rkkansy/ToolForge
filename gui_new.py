import threading
import signal
import sys
import json
from pathlib import Path
tkimport tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pynput.keyboard import Key

from player import ActionPlayer
from recorder import ActionRecorder
from script_manager import ScriptManager
from actions import ActionType

DEFAULT_COLOR_AREA_WIDTH = 300
DEFAULT_COLOR_AREA_HEIGHT = 500


def to_key(key_str, default):
    """Convert a string to a pynput Key or fallback to literal."""
    if not key_str:
        return default
    key_str = key_str.lower()
    return getattr(Key, key_str, key_str)


class ProgressDisplay:
    """Real-time progress display for playback."""
    def __init__(self, parent, player, params, sequence):
        self.player = player
        self.sequence = sequence
        self.param_vars = {}

        self.window = tk.Toplevel(parent)
        self.window.title("Playback Progress")
        self.window.attributes('-topmost', True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        main = ttk.Frame(self.window, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Playback Status", font=(None, 14, 'bold')).pack(pady=(0,10))

        # Controls
        ctl = ttk.LabelFrame(main, text="Controls", padding=10)
        ctl.pack(fill=tk.X)
        self.param_vars['speed'] = tk.DoubleVar(value=params.get('speed',1.0))
        ttk.Label(ctl, text="Speed").grid(row=0, column=0)
        ttk.Entry(ctl, textvariable=self.param_vars['speed'], width=8).grid(row=0, column=1)

        self.param_vars['loop'] = tk.BooleanVar(value=params.get('loop',False))
        ttk.Checkbutton(ctl, text="Loop", variable=self.param_vars['loop']).grid(row=0, column=2)

        # Key bindings
        keys = ['pause_key','stop_key','skip_key']
        for i,key in enumerate(keys, start=1):
            ttk.Label(ctl, text=key.replace('_',' ').title()).grid(row=i, column=0)
            var = tk.StringVar(value=params.get(key, ''))
            ttk.Entry(ctl, textvariable=var, width=8).grid(row=i, column=1)
            self.param_vars[key] = var

        ttk.Button(ctl, text="Apply", command=self.apply).grid(row=4, column=0, columnspan=3, pady=5)

        # Status
        self.status = ttk.Label(main, text="Ready", font=(None,12,'bold'), foreground='green')
        self.status.pack(pady=10)
        self.countdown = ttk.Label(main, text="0.0s", font=(None,16,'bold'))
        self.countdown.pack(pady=5)

        self.listbox = tk.Listbox(main)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.update_list()

        self.countdown_job = None
        self.window.update()

    def apply(self):
        if self.player:
            self.player.speed = self.param_vars['speed'].get()
            self.player.loop_until_stopped = self.param_vars['loop'].get()
            self.player.update_keys(
                pause_key=to_key(self.param_vars['pause_key'].get(), Key.space),
                stop_key=self.param_vars['stop_key'].get(),
                skip_pause_key=self.param_vars['skip_key'].get()
            )

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
            self.window.after_cancel(self.countdown_job)
        def tick(rem):
            self.countdown.config(text=f"{rem:.1f}s")
            if rem>0:
                self.countdown_job = self.window.after(100, tick, rem-0.1)
        tick(delay)

    def close(self):
        if self.player:
            self.player.stop_playback()
        if self.countdown_job:
            self.window.after_cancel(self.countdown_job)
        self.window.destroy()


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
        for p in progs: lb.insert(tk.END,p)
        lb.pack(fill=tk.BOTH,expand=True)
        def start():
            sel=lb.curselection()
            if not sel: return
            prog=progs[sel[0]]
            seq=self.mgr.load_program(prog)
            self._execute(seq, prog)
        ttk.Button(self.content, text="Run", command=start).pack(pady=5)

    def _create_mode(self):
        ttk.Label(self.content, text="Create mode"")
        # simplified for brevity - similar to play but with add/remove

    def _edit_mode(self):
        ttk.Label(self.content, text="Edit mode")

    def _options_mode(self):
        opt=self.settings
        for k,v in opt.items():
            ttk.Label(self.content, text=f"{k}: {v}").pack(anchor='w')
        def change(key):
            val=simpledialog.askstring("Change",f"New {key}:",initialvalue=str(opt[key]))
            if val is not None:
                opt[key]=type(opt[key])(val)
                self._save_settings()
                self._switch('options')
        for k in opt:
            ttk.Button(self.content, text=f"Set {k}",command=lambda k=k:change(k)).pack(anchor='w')

    def _execute(self, sequence, name):
        # open progress window
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
        disp = ProgressDisplay(self.root, player, params, sequence)
        player.progress_callback = disp.update_progress
        th = threading.Thread(target=player.replay_program, args=(sequence,), daemon=True)
        th.start()

    def _exit(self, *args):
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()