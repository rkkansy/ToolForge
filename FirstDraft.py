import random
import time
import json
import os
import random as rdm
import threading

import pyautogui
from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.keyboard import KeyCode
import tkinter as tk
from tkinter import simpledialog, messagebox

button_mapping = {
    'Button.left': Button.left,
    'Button.right': Button.right,
    'Button.middle': Button.middle,
}

# Initialize controllers
mouse_controller = MouseController()
keyboard_controller = KeyboardController()

# List to store the sequence of actions
actions = []
shift_pressed = False
# Flags to control the replay loop
stop_replay = threading.Event()
pause_replay = threading.Event()
end_replay = threading.Event()
skip_pause = threading.Event()

# Callbacks for mouse and keyboard listeners
def on_click(x, y, button, pressed):
    global shift_pressed
    if pressed:
        # Convert the button object to its string representation
        button_str = str(button)
        pixel_color = (0, 0, 0)
        if shift_pressed:
            pixel_color = pyautogui.pixel(x, y)
        actions.append(('mouse', time.time(), button_str, x, y, shift_pressed, pixel_color))
        shift_pressed = False

def on_press_record(key):
    global shift_pressed
    # Convert the key object to a string representation
    if key == Key.tab:
        return False
    elif key == Key.shift_l:
        shift_pressed = True
    else:
        key_str = str(key)
        actions.append(('keyboard', time.time(), key_str, False, (0, 0, 0)))
        shift_pressed = False

def get_key_from_string(key_str):
    if key_str.startswith('Key.'):
        return getattr(Key, key_str.split('.')[1], None)
    else:
        # Assuming the key_str is something like "'a'" or "'1'"
        return KeyCode.from_char(key_str.strip("'"))

def screenshot_area(x, y, width, height, output_file="screenshot.png"):
    """
    Captures a screenshot of a specified area of the screen.

    Parameters:
        x (int): The x-coordinate of the top-left corner of the area.
        y (int): The y-coordinate of the top-left corner of the area.
        width (int): The width of the area.
        height (int): The height of the area.
        output_file (str): The file name to save the screenshot.

    Returns:
        None
    """
    region = (x, y, width, height)
    screenshot = pyautogui.screenshot(region=region)
    screenshot.save(output_file)

def find_color_in_image_mean_position(image_path, target_color, offset=(0, 0), exact_match=True, tolerance=10):
    """
    Searches for all pixels in the image that match (or are close to) the target color.
    Returns the mean (average) position (screen coordinates) of these matching pixels
    if found; otherwise None.

    :param image_path: Path to the screenshot image.
    :param target_color: A tuple (R, G, B) indicating the color to find.
    :param offset: A tuple (offset_x, offset_y) that indicates the top-left screen
                   coordinate corresponding to (0, 0) in the image.
    :param exact_match: If True, looks for an exact color match. Otherwise uses tolerance.
    :param tolerance: Maximum allowed difference per color channel if exact_match=False.
    :return: (mean_screen_x, mean_screen_y) if found, else None.
    """
    from PIL import Image
    with Image.open(image_path) as img:
        width, height = img.size
        pixels = img.load()

        matching_pixels = []

        for y in range(height):
            for x in range(width):
                current_color = pixels[x, y]

                if exact_match:
                    # Exact color match
                    if current_color == target_color:
                        matching_pixels.append((offset[0] + x, offset[1] + y))
                else:
                    # Color-match within a tolerance
                    # Each color channel difference must be <= tolerance
                    if (abs(current_color[0] - target_color[0]) <= tolerance and
                        abs(current_color[1] - target_color[1]) <= tolerance and
                        abs(current_color[2] - target_color[2]) <= tolerance):
                        matching_pixels.append((offset[0] + x, offset[1] + y))

        # If no pixels matched, return None
        if not matching_pixels:
            return None

        # Compute the mean (average) position
        mean_x = sum(pos[0] for pos in matching_pixels) / len(matching_pixels)
        mean_y = sum(pos[1] for pos in matching_pixels) / len(matching_pixels)

        # Return the mean as a tuple
        return mean_x, mean_y

# Adjust times relative to the first action
def adjust_time_sequence_relative(data):
    if not data:
        return []

    adjusted_data = []
    previous_time = data[0][1]  # Start with the time of the first action

    for entry in data:
        adjusted_entry = entry.copy()  # Copy the original entry to avoid modifying input
        adjusted_entry[1] = entry[1] - previous_time  # Calculate time difference from previous action
        previous_time = entry[1]  # Update the previous time to the current action's time
        adjusted_data.append(adjusted_entry)

    return adjusted_data

# Adjust times from the start of the script
def adjust_time_sequence_from_start(data):
    if not data:
        return []

    adjusted_data = []
    start_time = data[0][1]

    for entry in data:
        adjusted_entry = entry.copy()
        adjusted_entry[1] = entry[1] - start_time
        adjusted_data.append(adjusted_entry)

    return adjusted_data

def save_actions():
    script_name = simpledialog.askstring("Save Script", "Enter a name for this script:")
    if script_name:
        file_path = os.path.join('scripts', f'{script_name}.json')
        with open(file_path, 'w') as file:
            json.dump(actions, file)
        print(f"Script '{script_name}' saved.")
        return script_name  # Return the name of the saved script
    else:
        print("Script not saved.")
        return None

def save_script_sequence(sequence, program_name=None):
    if program_name is None:
        program_name = simpledialog.askstring("Save Program", "Enter a name for this program:")
    if program_name:
        program_name = program_name.split('.')[0]
        file_path = os.path.join('programs', f'{program_name}.json')
        with open(file_path, 'w') as file:
            json.dump(sequence, file, indent=4)
        print(f"Sequence saved to {file_path}.")
    else:
        print("Sequence not saved.")

def load_script_sequence(file_name='default_sequence.json'):
    file_path = os.path.join('programs', f'{file_name}')
    if not os.path.exists(file_path):
        print(f"No saved sequence found at {file_path}.")
        return None

    with open(file_path, 'r') as file:
        sequence = json.load(file)
    return sequence

def replay_actions_search(loaded_actions, start_index=0, short=False, script_info=None, speed=0.1):
    global stop_replay, pause_replay, end_replay, skip_pause

    for i, action in enumerate(loaded_actions[start_index:], start=start_index):
        if stop_replay.is_set() or end_replay.is_set():
            return 0

        while pause_replay.is_set():
            time.sleep(0.1)
            if stop_replay.is_set() or end_replay.is_set():
                return 0

        # Update actions_left
        if script_info is not None:
            script_info['actions_left'] = len(loaded_actions) - i

        t1 = time.time()

        action_type, pause_time, key_or_button, *pos, shift, color = action

        action_delay_time = 0.06
        rand_delay_time = 0.03 * rdm.uniform(0.5, 1.0)

        incremental_sleep_time = 0.03  # Choose an appropriate interval (e.g., 0.025 seconds)

        total_sleep_time = pause_time
        elapsed_sleep_time = 0
        sleep_steps = max((total_sleep_time / incremental_sleep_time), 1)
        total_sleep_time *= min(speed + (4.0 / sleep_steps), 1.0) if short is False else 0.1
# Update time until next action
        if script_info is not None:
            script_info['time_until_next_action'] = max(total_sleep_time - elapsed_sleep_time, 0.0)

        while elapsed_sleep_time < total_sleep_time:
            if stop_replay.is_set() or end_replay.is_set():
                return 0
            while pause_replay.is_set():
                time.sleep(0.3)
                elapsed_sleep_time = total_sleep_time
                if stop_replay.is_set() or end_replay.is_set():
                    return 0

            time.sleep(incremental_sleep_time)
            elapsed_sleep_time += incremental_sleep_time

            if script_info is not None:
                script_info['time_until_next_action'] = max(total_sleep_time - elapsed_sleep_time, 0.0)

            if skip_pause.is_set():
                elapsed_sleep_time = total_sleep_time
                skip_pause.clear()

        if script_info is not None:
            script_info['time_until_next_action'] = 0.0

        # Perform the action
        if action_type == 'mouse':
            x, y = pos
            if shift:
                screenshot_file = "area_screenshot.png"
                # Coordinates and size of the screenshot region
                screenshot_x = x - 200
                screenshot_y = y - 300
                screenshot_w = 300
                screenshot_h = 500
                screenshot_area(screenshot_x, screenshot_y, screenshot_w, screenshot_h, screenshot_file)

                found_screen_coords = find_color_in_image_mean_position(
                    screenshot_file,
                    (0, 0, 255),
                    offset=(screenshot_x, screenshot_y),
                    exact_match=False,
                    tolerance=5  # used only if exact_match=False
                )
                if found_screen_coords:

                    x_f, y_f = found_screen_coords

                    diff_x = abs(x - x_f)
                    diff_y = abs(y - y_f)
                    #if diff_x > 100 or diff_y > 100:
                    #    print(f"Detected color is off by: (x: {diff_x},y: {diff_y})")
                    #    return 0

                    with keyboard_controller.pressed(Key.shift_l):
                        time.sleep(0.06)
                        print(f"Detected color is off by: (x: {diff_x},y: {diff_y})")
                        mouse_controller.position = (x_f, y_f)
                        # Convert the string representation back to a Button object
                        button_obj = button_mapping.get(key_or_button, Button.left)
                        time.sleep(action_delay_time)
                        mouse_controller.click(button_obj)
                else:
                    print("No matching colors: ", color)
                    return -1
            else:
                mouse_controller.position = (x, y)
                # Convert the string representation back to a Button object
                button_obj = button_mapping.get(key_or_button, Button.left)  # Default to Button.left if not found
                time.sleep(action_delay_time)
                mouse_controller.click(button_obj)

        if action_type == 'keyboard':
            key_obj = get_key_from_string(key_or_button)
            if key_obj:
                time.sleep(action_delay_time)
                keyboard_controller.press(key_obj)
                time.sleep(action_delay_time)
                keyboard_controller.release(key_obj)

        print(action, min(speed + (4.0 / sleep_steps), 1.0))

    return 1

def replay_actions(loaded_actions, start_index=0, short=False, script_info=None, speed=0.1):
    global stop_replay, pause_replay, end_replay, skip_pause

    for i, action in enumerate(loaded_actions[start_index:], start=start_index):
        if stop_replay.is_set() or end_replay.is_set():
            return 0

        while pause_replay.is_set():
            time.sleep(0.1)
            if stop_replay.is_set() or end_replay.is_set():
                return 0

        # Update actions_left
        if script_info is not None:
            script_info['actions_left'] = len(loaded_actions) - i

        t1 = time.time()

        action_type, pause_time, key_or_button, *pos, shift, color = action

        action_delay_time = 0.06
        rand_delay_time = 0.05 * rdm.uniform(0.1, 1.0)

        incremental_sleep_time = 0.03  # Choose an appropriate interval (e.g., 0.025 seconds)

        total_sleep_time = pause_time
        elapsed_sleep_time = 0
        sleep_steps = max((total_sleep_time / incremental_sleep_time), 1)
        total_sleep_time *= min(speed + (4.0 / sleep_steps), 1.0) if short is False else 0.1
# Update time until next action
        if script_info is not None:
            script_info['time_until_next_action'] = max(total_sleep_time - elapsed_sleep_time, 0.0)

        while elapsed_sleep_time < total_sleep_time:
            if stop_replay.is_set() or end_replay.is_set():
                return 0
            while pause_replay.is_set():
                time.sleep(0.3)
                if stop_replay.is_set() or end_replay.is_set():
                    return 0

            time.sleep(incremental_sleep_time)
            elapsed_sleep_time += incremental_sleep_time

            if script_info is not None:
                script_info['time_until_next_action'] = max(total_sleep_time - elapsed_sleep_time, 0.0)

            if skip_pause.is_set():
                elapsed_sleep_time = total_sleep_time
                skip_pause.clear()

        if script_info is not None:
            script_info['time_until_next_action'] = 0.0

        # Perform the action
        if action_type == 'mouse':
            x, y = pos
            if shift:
                print("Shift click")
                pixel_color = list(pyautogui.pixel(x, y))
                diff = 0
                for j in range(3):
                    if abs(pixel_color[j] - color[j]) > 25:
                        diff += 40
                    diff += abs(pixel_color[j] - color[j])

                print(pixel_color, color, diff)
                if diff < 25:
                    with keyboard_controller.pressed(Key.shift_l):
                        time.sleep(0.05)
                        mouse_controller.position = (x, y)
                        # Convert the string representation back to a Button object
                        button_obj = button_mapping.get(key_or_button, Button.left)
                        time.sleep(action_delay_time)
                        mouse_controller.click(button_obj)
                else:
                    print("Non matching colors: ", color, pixel_color)

                    stop_replay.set()
            else:
                mouse_controller.position = (x, y)
                # Convert the string representation back to a Button object
                button_obj = button_mapping.get(key_or_button, Button.left)  # Default to Button.left if not found
                time.sleep(action_delay_time)
                mouse_controller.click(button_obj)

        if action_type == 'keyboard':
            key_obj = get_key_from_string(key_or_button)
            if key_obj:
                time.sleep(action_delay_time)
                keyboard_controller.press(key_obj)
                time.sleep(action_delay_time)
                keyboard_controller.release(key_obj)

    return 1

def start():
    global end_replay, stop_replay, pause_replay, skip_pause
    exit_prog = False

    # Create the main Tkinter window
    root = tk.Tk()
    root.title("Script Runner")

    # Define functions to handle button clicks
    def run_existing_program():
        # Create a new window to select existing programs
        program_window = tk.Toplevel(root)
        program_window.title("Select Program to Run")
        program_window.geometry("500x400")  # Increase the window size

        # List all available programs
        if not os.path.exists('programs'):
            tk.messagebox.showinfo("No Programs", "No programs available.")
            return

        programs = [f for f in os.listdir('programs') if f.endswith('.json')]
        if not programs:
            tk.messagebox.showinfo("No Programs", "No programs available.")
            return

        # Create a listbox to display programs
        program_listbox = tk.Listbox(program_window, width=50, height=20)  # Increase width and height
        for prog in programs:
            program_listbox.insert(tk.END, prog)
        program_listbox.pack(padx=10, pady=10)

        def select_program():
            selection = program_listbox.curselection()
            if selection:
                program_name = program_listbox.get(selection[0])
                sequence = load_script_sequence(program_name)
                if sequence:
                    # Close the program selection window
                    program_window.destroy()
                    # Run the program
                    run_script_sequence(sequence, root)
                else:
                    tk.messagebox.showinfo("Error", "Failed to load the program.")
            else:
                tk.messagebox.showinfo("No Selection", "Please select a program to run.")

        select_button = tk.Button(program_window, text="Run Program", command=select_program)
        select_button.pack()

    def create_new_program(editing=False, program_name=None):
        create_window = tk.Toplevel(root)
        create_window.title("Create New Program")
        create_window.geometry("800x600")  # Increased window size to accommodate new view

        # Left frame for available scripts and actions
        left_frame = tk.Frame(create_window)
        left_frame.pack(side=tk.LEFT, padx=20, pady=20)

        tk.Label(left_frame, text="Available Scripts").pack()

        # Set exportselection=0 to prevent losing selection when focus changes
        available_scripts_listbox = tk.Listbox(left_frame, width=30, height=15, exportselection=0)
        available_scripts_listbox.pack()

        # Load available scripts
        def load_available_scripts():
            available_scripts_listbox.delete(0, tk.END)
            if not os.path.exists('scripts'):
                return

            scripts = [f for f in os.listdir('scripts') if f.endswith('.json')]
            for script in scripts:
                available_scripts_listbox.insert(tk.END, script)

        load_available_scripts()

        # Add label and listbox for actions display
        tk.Label(left_frame, text="Actions in Selected Script").pack()

        # Set exportselection=0 and selectmode=tk.SINGLE
        actions_listbox = tk.Listbox(left_frame, width=50, height=15, selectmode=tk.SINGLE, exportselection=0)
        actions_listbox.pack()

        # Variables to store current actions and adjusted scripts
        current_actions = []
        adjusted_scripts = {}  # Store adjusted actions for scripts
        current_script_name = None  # Store the name of the currently selected script

        # Function to display actions of the selected script
        def display_script_actions(event):
            nonlocal current_actions, current_script_name  # Declare nonlocal variables
            selection = available_scripts_listbox.curselection()
            if selection:
                script_name = available_scripts_listbox.get(selection[0])
                # Only update if the selection has changed
                if script_name != current_script_name:
                    current_script_name = script_name
                    # Check if there are adjusted actions
                    if script_name in adjusted_scripts:
                        actions = adjusted_scripts[script_name]
                    else:
                        script_path = os.path.join('scripts', script_name)
                        if os.path.exists(script_path):
                            with open(script_path, 'r') as file:
                                actions = json.load(file)
                                # Adjust times relative to start
                                actions = adjust_time_sequence_from_start(actions)
                        else:
                            actions = []
                    # Store in current_actions
                    current_actions = actions
                    # Clear the actions_listbox
                    actions_listbox.delete(0, tk.END)
                    # Display actions
                    for idx, action in enumerate(actions):
                        if action[0] == 'mouse':
                            action_type, time_stamp, button_str, x, y, _, _ = action
                            action_text = f"{idx+1}: {action_type} {button_str} at ({x}, {y}) after {time_stamp:.2f}s"
                        elif action[0] == 'keyboard':
                            action_type, time_stamp, key_str, _, _ = action
                            action_text = f"{idx+1}: {action_type} {key_str} after {time_stamp:.2f}s"
                        else:
                            action_text = str(action)
                        actions_listbox.insert(tk.END, action_text)
            else:
                # Do not clear actions_listbox if no selection
                pass

        # Bind the function to the available_scripts_listbox selection
        available_scripts_listbox.bind('<<ListboxSelect>>', display_script_actions)

        # Function to edit action time
        def edit_action_time(event):
            nonlocal current_actions, adjusted_scripts  # Declare nonlocal variables
            selection = actions_listbox.curselection()
            if selection:
                idx = selection[0]
                action = current_actions[idx]
                current_time = action[1]
                # Prompt user for new time
                new_time = simpledialog.askfloat(
                    "Edit Time",
                    f"Current time is {current_time:.2f}s.\nEnter new time in seconds:",
                    initialvalue=current_time
                )
                if new_time is not None:
                    delta_time = new_time - current_time
                    # Update time for the selected action
                    current_actions[idx][1] = new_time
                    # Adjust times for subsequent actions
                    for i in range(idx + 1, len(current_actions)):
                        current_actions[i][1] += delta_time
                    # Update the display
                    actions_listbox.delete(0, tk.END)
                    for idx, action in enumerate(current_actions):
                        if action[0] == 'mouse':
                            action_type, time_stamp, button_str, x, y = action
                            action_text = f"{idx+1}: {action_type} {button_str} at ({x}, {y}) after {time_stamp:.2f}s"
                        elif action[0] == 'keyboard':
                            action_type, time_stamp, key_str = action
                            action_text = f"{idx+1}: {action_type} {key_str} after {time_stamp:.2f}s"
                        else:
                            action_text = str(action)
                        actions_listbox.insert(tk.END, action_text)
                    # Save the adjusted actions
                    script_name = current_script_name
                    if script_name:
                        adjusted_scripts[script_name] = current_actions.copy()
                else:
                    # If new_time is None (cancelled), do nothing
                    pass
            else:
                # If no selection, do nothing
                pass

        # Bind the function to actions_listbox item double-click
        actions_listbox.bind('<Double-Button-1>', edit_action_time)

        # Middle frame for buttons
        button_frame = tk.Frame(create_window)
        button_frame.pack(side=tk.LEFT, padx=10, pady=10)

        def add_script():
            selection = available_scripts_listbox.curselection()
            if selection:
                script_name = available_scripts_listbox.get(selection[0])
                # Default iterations to 1
                selected_scripts.append({'name': script_name, 'iterations': 1})
                selected_scripts_listbox.insert(tk.END, f"{script_name} (1)")
            else:
                tk.messagebox.showinfo("No Selection", "Please select a script to add.")

        def remove_script():
            selection = selected_scripts_listbox.curselection()
            if selection:
                selected_scripts_listbox.delete(selection[0])
                selected_scripts.pop(selection[0])
            else:
                tk.messagebox.showinfo("No Selection", "Please select a script to remove.")

        def move_script_up():
            selection = selected_scripts_listbox.curselection()
            if selection and selection[0] > 0:
                index = selection[0]
                # Swap in the list
                selected_scripts[index], selected_scripts[index - 1] = selected_scripts[index - 1], selected_scripts[index]
                # Swap in the listbox
                script_text = selected_scripts_listbox.get(index)
                selected_scripts_listbox.delete(index)
                selected_scripts_listbox.insert(index - 1, script_text)
                selected_scripts_listbox.select_set(index - 1)
            else:
                tk.messagebox.showinfo("Cannot Move", "Cannot move the script up.")

        def move_script_down():
            selection = selected_scripts_listbox.curselection()
            if selection and selection[0] < selected_scripts_listbox.size() - 1:
                index = selection[0]
                # Swap in the list
                selected_scripts[index], selected_scripts[index + 1] = selected_scripts[index + 1], selected_scripts[index]
                # Swap in the listbox
                script_text = selected_scripts_listbox.get(index)
                selected_scripts_listbox.delete(index)
                selected_scripts_listbox.insert(index + 1, script_text)
                selected_scripts_listbox.select_set(index + 1)
            else:
                tk.messagebox.showinfo("Cannot Move", "Cannot move the script down.")

        def record_new_script():
            global actions
            actions = []
            # Close the create window temporarily
            create_window.withdraw()
            messagebox.showinfo("Recording", "Recording will start after you click OK.\nPress 'Tab' to stop recording.")
            # Record actions
            with mouse.Listener(on_click=on_click) as listener1, keyboard.Listener(on_press=on_press_record) as listener2:
                listener2.join()
            # Save actions
            new_script_name = save_actions()
            if new_script_name:
                # Refresh the available scripts listbox
                load_available_scripts()
                # Automatically select and add the new script
                idx = available_scripts_listbox.get(0, tk.END).index(new_script_name + '.json')
                available_scripts_listbox.selection_set(idx)
                add_script()
            # Show the create window again
            create_window.deiconify()

        add_button = tk.Button(button_frame, text="Add >", command=add_script)
        remove_button = tk.Button(button_frame, text="< Remove", command=remove_script)
        up_button = tk.Button(button_frame, text="Move Up", command=move_script_up)
        down_button = tk.Button(button_frame, text="Move Down", command=move_script_down)
        record_button = tk.Button(button_frame, text="Record New Script", command=record_new_script)

        add_button.pack(pady=5)
        remove_button.pack(pady=5)
        up_button.pack(pady=5)
        down_button.pack(pady=5)
        record_button.pack(pady=20)

        # Right frame for selected scripts
        right_frame = tk.Frame(create_window)
        right_frame.pack(side=tk.LEFT, padx=10, pady=10)

        tk.Label(right_frame, text="Selected Scripts").pack()

        selected_scripts_listbox = tk.Listbox(right_frame)
        selected_scripts_listbox.pack()

        selected_scripts = []  # List of dictionaries {'name': script_name, 'iterations': N}

        def set_iterations():
            selection = selected_scripts_listbox.curselection()
            if selection:
                index = selection[0]
                script_info = selected_scripts[index]
                iterations = simpledialog.askinteger("Iterations", f"How many times should '{script_info['name']}' be run?", initialvalue=script_info['iterations'])
                if iterations is not None:
                    script_info['iterations'] = iterations
                    # Update the listbox display
                    selected_scripts_listbox.delete(index)
                    selected_scripts_listbox.insert(index, f"{script_info['name']} ({iterations})")
                    selected_scripts_listbox.select_set(index)
                else:
                    # If iterations is None (cancelled), do nothing
                    pass
            else:
                tk.messagebox.showinfo("No Selection", "Please select a script to set iterations.")

        set_iterations_button = tk.Button(right_frame, text="Set Iterations", command=set_iterations)
        set_iterations_button.pack(pady=5)

        def save_program():
            if not selected_scripts:
                tk.messagebox.showinfo("No Scripts", "No scripts selected to save.")
                return

            # Prepare the sequence to save
            sequence = []
            for script_info in selected_scripts:
                script_name = script_info['name']
                # Use adjusted actions if available
                if script_name in adjusted_scripts:
                    actions = adjusted_scripts[script_name]
                    # Ensure times are relative for saving
                    actions = adjust_time_sequence_relative(actions)
                else:
                    # Load the actions for each script
                    script_path = os.path.join('scripts', script_name)
                    with open(script_path, 'r') as file:
                        actions = json.load(file)
                        actions = adjust_time_sequence_relative(actions)
                sequence.append(({'name': script_name, 'actions': actions}, script_info['iterations']))

            # Save the sequence
            if editing and program_name:
                # Delete the original program
                os.remove(os.path.join('programs', program_name))
                # Save the new program under the same name
                save_script_sequence(sequence, program_name=program_name)
            else:
                save_script_sequence(sequence)
            create_window.destroy()

        save_button = tk.Button(create_window, text="Save Program", command=save_program)
        save_button.pack(pady=10)

        # If editing, load the existing program
        if editing and program_name:
            existing_sequence = load_script_sequence(program_name)
            if existing_sequence:
                for script_info_item, iterations in existing_sequence:
                    script_name = script_info_item['name']
                    selected_scripts.append({'name': script_name, 'iterations': iterations})
                    selected_scripts_listbox.insert(tk.END, f"{script_name} ({iterations})")
            else:
                tk.messagebox.showinfo("Error", "Failed to load the program for editing.")

    def edit_existing_program():
        # Create a new window to select existing programs
        program_window = tk.Toplevel(root)
        program_window.title("Select Program to Edit")

        # List all available programs
        if not os.path.exists('programs'):
            tk.messagebox.showinfo("No Programs", "No programs available.")
            return

        programs = [f for f in os.listdir('programs') if f.endswith('.json')]
        if not programs:
            tk.messagebox.showinfo("No Programs", "No programs available.")
            return

        # Create a listbox to display programs
        program_listbox = tk.Listbox(program_window)
        for prog in programs:
            program_listbox.insert(tk.END, prog)
        program_listbox.pack()

        def select_program_to_edit():
            selection = program_listbox.curselection()
            if selection:
                program_name = program_listbox.get(selection[0])
                program_window.destroy()
                create_new_program(editing=True, program_name=program_name)
            else:
                tk.messagebox.showinfo("No Selection", "Please select a program to edit.")

        select_button = tk.Button(program_window, text="Edit Program", command=select_program_to_edit)
        select_button.pack()

    def exit_program():
        root.destroy()
        # Set exit_prog to True to exit the program
        nonlocal exit_prog
        exit_prog = True

    # Create buttons
    run_button = tk.Button(root, text="Run existing program", command=run_existing_program)
    create_button = tk.Button(root, text="Create new program", command=create_new_program)
    edit_button = tk.Button(root, text="Edit existing program", command=edit_existing_program)
    exit_button = tk.Button(root, text="Exit", command=exit_program)

    # Arrange buttons
    run_button.pack(pady=10)
    create_button.pack(pady=10)
    edit_button.pack(pady=10)
    exit_button.pack(pady=10)
    root.geometry("300x200")
    # Start the Tkinter event loop
    root.mainloop()

    return 1

def run_script_sequence(sequence, root_window):
    """
    Opens a Script Control Panel with:
      - Checkboxes for short_var and pause
      - Entry for speed_var
      - Buttons for Pause, Resume, Stop
    After configuring the options, the user clicks 'Run Script' to start executing.
    """
    global stop_replay, pause_replay, end_replay, skip_pause

    # Hide the root window while the control panel is open
    root_window.withdraw()

    # Reset control flags
    stop_replay.clear()
    pause_replay.clear()
    end_replay.clear()
    skip_pause.clear()

    # Create option panel
    option_panel = tk.Toplevel()
    option_panel.title("Script Control Panel")

    # --- Variables to store script info (shown on the panel) ---
    current_script_name = tk.StringVar(value="Script: ")
    time_until_next_action = tk.StringVar(value="Time until next action: ")
    actions_left = tk.StringVar(value="Actions left: ")

    # Labels for the script info
    tk.Label(option_panel, textvariable=current_script_name).pack()
    tk.Label(option_panel, textvariable=time_until_next_action).pack()
    tk.Label(option_panel, textvariable=actions_left).pack()

    # --- Create Tkinter variables for short_var, pause, speed_var ---
    short_var_var = tk.BooleanVar(value=False)  # Default False
    pause_var_var = tk.BooleanVar(value=False)  # Default False
    speed_var_var = tk.StringVar(value="1.0")  # Default "0.80"

    # Checkboxes
    short_check = tk.Checkbutton(option_panel, text="Short Var", variable=short_var_var)
    short_check.pack(pady=5)

    pause_check = tk.Checkbutton(option_panel, text="Pause (initial)", variable=pause_var_var)
    pause_check.pack(pady=5)

    # Speed entry
    speed_label = tk.Label(option_panel, text="Speed Var:")
    speed_label.pack()
    speed_entry = tk.Entry(option_panel, textvariable=speed_var_var)
    speed_entry.pack()

    # --- Create Pause/Resume/Stop buttons as before ---
    def pause_script():
        pause_replay.set()
        print("Script paused.")

    def resume_script():
        pause_replay.clear()
        print("Script resumed.")

    def stop_script():
        stop_replay.set()
        print("Script stopped.")

    pause_button = tk.Button(option_panel, text="Pause (Space)", command=pause_script)
    resume_button = tk.Button(option_panel, text="Resume (Space)", command=resume_script)
    stop_button = tk.Button(option_panel, text="Stop (0)", command=stop_script)

    pause_button.pack(pady=5)
    resume_button.pack(pady=5)
    stop_button.pack(pady=5)

    # --- Dictionary for updating labels in real time ---
    script_info_dict = {
        'name': '',
        'time_until_next_action': 0.0,
        'actions_left': 0,
    }

    # Continuously update the labels for script info
    def update_labels():
        current_script_name.set(f"Script: {script_info_dict['name']}")
        time_until_next_action.set(
            f"Time until next action: {script_info_dict['time_until_next_action']:.2f} sec"
        )
        actions_left.set(f"Actions left: {script_info_dict['actions_left']}")
        option_panel.after(100, update_labels)

    update_labels()

    # --- Actual script-execution logic in a separate thread ---
    def run_sequence(sequence, short_var, pause_initial, speed_val):
        """
        This inner function is invoked in a separate thread after the user
        clicks 'Run Script'. It reads the short_var, pause, speed, etc.,
        then executes the sequence.
        """
        global stop_replay, pause_replay, end_replay, skip_pause

        # Start a keyboard listener to allow space/s stop
        def on_press(key):
            try:
                if key == Key.space:
                    # Toggle pause
                    if pause_replay.is_set():
                        pause_replay.clear()
                        print("Script resumed via keyboard.")
                    else:
                        pause_replay.set()
                        print("Script paused via keyboard.")
                elif key.char and key.char.lower() == 's':
                    stop_replay.set()
                    print("Script stopped via keyboard.")
            except AttributeError:
                pass

        listener = keyboard.Listener(on_press=on_press)
        print("Starting bot.")
        set_sleep = 0.05 if short_var else 0.5
        listener.start()
        setup_scripts = load_script_sequence("setupscripts.json")

        logout_script = setup_scripts[0]
        login_script = setup_scripts[1]

        logout_actions = logout_script[0]["actions"]
        login_actions = login_script[0]["actions"]

        log = True

        def do_farmrun(logged_in=False, bank_prep=False):

            time.sleep(0.5)
            if not logged_in:
                replay_actions(
                    login_actions,
                    script_info=script_info_dict,
                    short=short_var,
                    speed=float(speed_val)
                )
                time.sleep(3)

            farmrun_scripts = load_script_sequence("farmrun.json")

            for script_info_item1, iterations1 in farmrun_scripts:
                if stop_replay.is_set():
                    break

                script_name1 = script_info_item1['name']
                script_actions1 = script_info_item1['actions']
                print(f"Running {script_name1} for {iterations1} iterations.")
                # Update script name on the panel
                script_info_dict['name'] = script_name1
                if not bank_prep:
                    if script_name1 == "farmrun_bankprep.json":
                        continue
                # Replay each script the requested number of times
                for _ in range(iterations1):
                    if stop_replay.is_set():
                        break
                    script_info_dict['actions_left'] = len(script_actions1)

                    # Replay with the chosen speed
                    replay_actions_search(
                        script_actions1,
                        script_info=script_info_dict,
                        short=short_var,
                        speed=float(speed_val)
                    )

                    if stop_replay.is_set() or end_replay.is_set():
                        print("Script execution finished.")
                        break
                    time.sleep(1.0 + (set_sleep * rdm.uniform(0.5, 1.5)))

            time.sleep(0.5)
            replay_actions(
                logout_actions,
                script_info=script_info_dict,
                short=short_var,
                speed=float(speed_val)
            )
        do_farmrun(bank_prep=True, logged_in=True)
        for i in range(10):
            for j in range(50):
                time.sleep(96 + random.randint(0, 5))
                print(f"Iteration: {i} Slept for: ({j * 96})")
            do_farmrun(logged_in=False, bank_prep=False)

        reset_script_info = None

        #return 0
        for i, (script_info_item, iterations) in enumerate(sequence):
            if "reset" in script_info_item['name'].lower():
                reset_script_info = script_info_item
                # Remove the reset script from the sequence
                del sequence[i]
                break

        counter = 0
        while not stop_replay.is_set():

            # Small break between runs
            time.sleep(set_sleep + (set_sleep * rdm.uniform(1.0, 1.5)))

            if counter == 10000:
                stop_replay.set()

            # Go through each script in the sequence
            for script_info_item, iterations in sequence:
                if stop_replay.is_set():
                    break

                script_name = script_info_item['name']
                script_actions = script_info_item['actions']

                print(f"Running {script_name} for {iterations} iterations.")

                # Update script name on the panel
                script_info_dict['name'] = script_name

                # Replay each script the requested number of times
                for _ in range(iterations):
                    if stop_replay.is_set():
                        break
                    script_info_dict['actions_left'] = len(script_actions)

                    # Replay with the chosen speed
                    ret = replay_actions_search(
                        script_actions,
                        script_info=script_info_dict,
                        short=short_var,
                        speed=float(speed_val)
                    )

                    if stop_replay.is_set() or end_replay.is_set():
                        print("Script execution finished.")
                        break

                    # --- IF ret == 0, TRY RESET ---
                    if ret == 0 or ret == -1:
                        print("Script returned 0. Checking for reset script...")
                        # If we found a reset script, replay it once (or as many times as you want)
                        if reset_script_info is not None:
                            print(f"Running reset script: {reset_script_info['name']}")
                            reset_ret = replay_actions_search(
                                reset_script_info['actions'],
                                script_info=script_info_dict,
                                short=short_var,
                                speed=float(speed_val)
                            )
                            # Decide if you want to continue or break based on reset_ret
                            # For example, if even reset script fails, you might want to stop:
                            if reset_ret == 0:
                                print("Reset script also failed. Stopping.")
                                stop_replay.set()
                                break
                        else:
                            # No reset script found. End everything.
                            print("No reset script found. Stopping replay loop.")
                            stop_replay.set()
                            break

                    # Additional sleep between repeated iterations of the same script
                    time.sleep(set_sleep + (set_sleep * rdm.uniform(0.5, 1.5)))

            counter += 1

        listener.stop()
        option_panel.destroy()
        root_window.deiconify()

    # --- Button to start the script after user sets checkboxes/entry ---
    def start_script():
        short_val = short_var_var.get()
        pause_val = pause_var_var.get()
        speed_val = speed_var_var.get()

        try:
            float(speed_val)  # Validate speed can be converted to float
        except ValueError:
            tk.messagebox.showerror("Invalid Speed", "Please enter a valid floating-point number for speed.")
            return

        script_thread = threading.Thread(
            target=run_sequence,
            args=(sequence, short_val, pause_val, speed_val),
            daemon=True
        )
        script_thread.start()

    # Add the "Run Script" button at the bottom
    run_script_btn = tk.Button(option_panel, text="Run Script", command=start_script)
    run_script_btn.pack(pady=10)

def main():
    # Ensure the 'scripts' directory exists
    if not os.path.exists('scripts'):
        os.makedirs('scripts')

    if not os.path.exists('programs'):
        os.makedirs('programs')

    ret = start()

if __name__ == "__main__":
    main()
