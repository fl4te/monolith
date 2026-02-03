import configparser
import ctypes
import datetime
import hashlib
import io
import json
import logging
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from tkinter import filedialog, ttk
import tkinter as tk

import customtkinter as ctk
import requests
from CTkMessagebox import CTkMessagebox
from PIL import Image, ImageTk

# Basic DPI Scaling
def get_dpi_scaling():
    scaling = 1.0
    try:
        if os.name == 'nt':
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            monitor = ctypes.windll.user32.MonitorFromPoint((0, 0), 2)
            dpi_x = ctypes.c_uint()
            ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), None)
            scaling = dpi_x.value / 96.0
        elif os.name == "darwin":
            from AppKit import NSScreen
            scaling = NSScreen.mainScreen().backingScaleFactor()
        else:
            scaling = float(os.environ.get("GDK_SCALE", 1.0))
    except Exception as e:
        logging.warning(f"Failed to get DPI scaling: {e}")
        scaling = 1.0
    return scaling


# Constants
APP_VERSION = "1.0.2"
UPDATE_VERSION_URL = "https://raw.githubusercontent.com/fl4te/jk2_mod_manager/refs/heads/main/version.txt"
DISABLED_DIR_NAME = "_disabled"
PROTECTED_MODS = {
    "assets0.pk3", "assets1.pk3", "assets2.pk3",
    "assets3.pk3", "assets5.pk3", "assetsmv.pk3",
    "assetsmv2.pk3"
}

# UI Colors
COLOR_PRIMARY = "#1f6aa5"
COLOR_SUCCESS = "#2cc985"
COLOR_DANGER = "#c0392b"
COLOR_WARNING = "#e67e22"
COLOR_TEXT_DIM = "#a0a0a0"
DARK_BG_COLOR = "#242424"
LIGHT_BG_COLOR = "#ffffff"
COLOR_SCROLL_TROUGH = "#1f1f1f"
COLOR_SCROLL_THUMB = "#404040"
COLOR_SCROLL_ARROW = "#cccccc"

# Config Directory
def get_config_dir(app_name: str = "JK2ModManager") -> Path:
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / app_name
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(appdata) / app_name
    else:
        return Path.home() / f".{app_name.lower()}"

CONFIG_DIR = get_config_dir("JK2ModManager")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
RCON_CONFIG_FILE = CONFIG_DIR / "servers.ini"

# Logging
logfile_path = CONFIG_DIR / "error.log"
logging.basicConfig(filename=logfile_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Utility Functions
def get_sha256_hash(filepath: Path) -> str:
    hash_obj = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(4096):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except Exception as e:
        logging.error(f"Failed to get SHA256 hash for {filepath}: {e}")
        return "ERROR"

def clean_rcon_response(response: str) -> str:
    cleaned_response = response
    for i in range(8):
        cleaned_response = cleaned_response.replace(f"^{i}", "")
    lines = cleaned_response.split('\n')
    return '\n'.join(line.strip() for line in lines if line.strip())

# UI Components
class CTkTextbox(ctk.CTkTextbox):
    def __init__(self, master, **kwargs):
        super().__init__(master, wrap="word", **kwargs)

class CTkSplash(ctk.CTkToplevel):
    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        width, height = 600, 320

        temp_root = tk.Tk()
        temp_root.withdraw()
        primary_screen_width = temp_root.winfo_screenwidth()
        primary_screen_height = temp_root.winfo_screenheight()
        temp_root.destroy()

        x = (primary_screen_width - width) // 2
        y = (primary_screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

        if os.name == 'nt':
            self.wm_attributes("-transparentcolor", "#333333")
        else:
            self.attributes("-alpha", 0.99)
        self.configure(fg_color="#333333")

        self.main_card = ctk.CTkFrame(
            self, corner_radius=25, fg_color="#1a1a1a",
            border_width=2, border_color="#2cc985"
        )
        self.main_card.pack(fill="both", expand=True)

        self.version = ctk.CTkLabel(
            self.main_card, text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#2cc985"
        )
        self.version.place(relx=0.95, rely=0.08, anchor="ne")

        self.title = ctk.CTkLabel(
            self.main_card, text="JK2 MOD MANAGER",
            font=ctk.CTkFont(family="Segoe UI", size=32, weight="bold"),
            text_color="#ffffff"
        )
        self.title.pack(pady=(60, 0))

        self.line = ctk.CTkFrame(self.main_card, height=2, width=100, fg_color="#2cc985")
        self.line.pack(pady=10)

        self.subtitle = ctk.CTkLabel(
            self.main_card, text="SYSTEM INITIALIZATION",
            font=ctk.CTkFont(size=12), text_color="#aaaaaa"
        )
        self.subtitle.pack(pady=(10, 0))

        self.sub_detail = ctk.CTkLabel(
            self.main_card, text="by flate8954",
            font=ctk.CTkFont(size=11), text_color="#555555"
        )
        self.sub_detail.pack(pady=(5, 20))

        self.pb = ctk.CTkProgressBar(
            self.main_card, width=400, height=4,
            fg_color="#2a2a2a", progress_color="#2cc985", determinate_speed=2.0
        )
        self.pb.pack(pady=(10, 30))
        self.pb.set(0)
        self.pb.start()

class CTkInputDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, prompt: str, initialvalue: str = ""):
        super().__init__(parent)
        self.title(title)
        self.prompt = prompt
        self.initialvalue = initialvalue
        self.user_input = None
        self.parent = parent
        self.transient(parent)
        width = 350
        height = 150
        x = parent.winfo_x() + (parent.winfo_width() - width) // 2
        y = parent.winfo_y() + (parent.winfo_height() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.update_idletasks()
        self.wait_visibility()
        self.grab_set()
        self.focus_set()
        self.grid_columnconfigure(0, weight=1)

        lbl = ctk.CTkLabel(self, text=prompt)
        lbl.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        self.entry = ctk.CTkEntry(self, width=300)
        self.entry.insert(0, initialvalue)
        self.entry.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.entry.focus_set()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="e")

        btn_ok = ctk.CTkButton(btn_frame, text="OK", width=70, command=self.on_ok)
        btn_ok.pack(side="left", padx=(10, 0))

        btn_cancel = ctk.CTkButton(btn_frame, text="Cancel", width=70, command=self.on_cancel)
        btn_cancel.pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.bind("<Return>", lambda event: self.on_ok())
        self.bind("<Escape>", lambda event: self.on_cancel())
        self.wait_window(self)

    def on_ok(self):
        self.user_input = self.entry.get()
        self.destroy()

    def on_cancel(self):
        self.user_input = None
        self.destroy()

    def destroy(self):
        if self.grab_status():
            self.grab_release()
        super().destroy()

def ctk_ask_string(parent, title: str, prompt: str, initialvalue: str = "") -> str | None:
    dialog = CTkInputDialog(parent, title, prompt, initialvalue)
    return dialog.user_input

# Main Application
class JK2ModManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.mod_folder: Path | None = None
        self.game_exe_path: Path | None = None
        self.game_process: subprocess.Popen | None = None
        self.search_var = ctk.StringVar()
        self.path_var = ctk.StringVar()
        self.status_var = ctk.StringVar(value="Ready")
        self.active_profile: str | None = None
        self.profiles: dict[str, dict] = {}
        self.mod_index: dict[str, Path] = {}

        self.rcon_config = configparser.ConfigParser()
        if not os.path.exists(RCON_CONFIG_FILE):
            with open(RCON_CONFIG_FILE, 'w') as f:
                self.rcon_config.write(f)
        self.rcon_config.read(RCON_CONFIG_FILE)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(5)

        self.title("JK2 Mod Manager")
        self.geometry("900x600")
        self.minsize(900, 600)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - 900) // 2
        y = (screen_h - 600) // 2
        self.geometry(f"900x600+{x}+{y}")

        config = self._load_config()
        self.profiles = config.get("profiles", {})
        self.active_profile = config.get("active_profile", None)

        appearance_mode = config.get("appearance_mode", "Dark")
        ctk.set_appearance_mode(appearance_mode)

        if self.active_profile and self.active_profile in self.profiles:
            p = self.profiles[self.active_profile]
            self.game_exe_path = Path(p.get("game_exe")) if p.get("game_exe") else None
        else:
            self.game_exe_path = None

        if "geometry" in config:
            self.geometry(config["geometry"])

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.create_sidebar()
        self.create_main_area()
        self.create_context_menu()
        self.refresh_profile_dropdown()
        self.load_profile_folder()
        self.update_status()
        self.update_treeview_style(ctk.get_appearance_mode())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # Core UI
    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(14, weight=1)

        lbl_title = ctk.CTkLabel(self.sidebar, text="Jedi Knight II", font=ctk.CTkFont(size=20, weight="bold"))
        lbl_title.grid(row=0, column=0, padx=20, pady=(20, 10))
        lbl_subtitle = ctk.CTkLabel(self.sidebar, text="MOD MANAGER", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT_DIM)
        lbl_subtitle.grid(row=1, column=0, padx=20, pady=(0, 20))

        lbl_params = ctk.CTkLabel(self.sidebar, text="Launch Parameters:", anchor="w")
        lbl_params.grid(row=2, column=0, padx=20, pady=(0, 0), sticky="w")

        self.devmode_var = ctk.BooleanVar(value=False)
        self.devmode_checkbox = ctk.CTkCheckBox(
            self.sidebar, text="Developer Mode", variable=self.devmode_var, onvalue=True, offvalue=False
        )
        self.devmode_checkbox.grid(row=3, column=0, padx=20, pady=(5, 0), sticky="w")

        self.logfile_var = ctk.BooleanVar(value=False)
        self.logfile_checkbox = ctk.CTkCheckBox(
            self.sidebar, text="Logfile", variable=self.logfile_var, onvalue=True, offvalue=False
        )
        self.logfile_checkbox.grid(row=4, column=0, padx=20, pady=(5, 0), sticky="w")

        self.custom_params_var = ctk.StringVar()
        self.custom_params_entry = ctk.CTkEntry(
            self.sidebar, textvariable=self.custom_params_var, placeholder_text="Custom parameters..."
        )
        self.custom_params_entry.grid(row=5, column=0, padx=20, pady=(5, 10), sticky="ew")

        self.btn_launch = ctk.CTkButton(
            self.sidebar, text="LAUNCH GAME", height=50, fg_color=COLOR_SUCCESS, hover_color="#25a06a",
            font=ctk.CTkFont(size=14, weight="bold"), command=self.start_game_threaded
        )
        self.btn_launch.grid(row=6, column=0, padx=20, pady=10)

        ctk.CTkLabel(self.sidebar, text="Profile:", anchor="w").grid(row=7, column=0, padx=20, pady=(20, 0), sticky="w")
        self.opt_profile = ctk.CTkOptionMenu(self.sidebar, dynamic_resizing=False, command=self.change_profile_event)
        self.opt_profile.grid(row=8, column=0, padx=20, pady=(5, 10))

        p_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        p_frame.grid(row=9, column=0, padx=20, pady=5)
        ctk.CTkButton(p_frame, text="+", width=40, command=self.create_profile, fg_color="#444").pack(side="left", padx=2)
        ctk.CTkButton(p_frame, text="✎", width=40, command=self.rename_profile, fg_color="#444").pack(side="left", padx=2)
        ctk.CTkButton(p_frame, text="🗑", width=40, command=self.delete_profile, fg_color=COLOR_DANGER).pack(side="left", padx=2)

        lbl_mode = ctk.CTkLabel(self.sidebar, text="Appearance:", anchor="w")
        lbl_mode.grid(row=10, column=0, padx=20, pady=(5, 0), sticky="w")
        self.opt_mode = ctk.CTkOptionMenu(self.sidebar, values=["Dark", "Light"], command=self.change_appearance_mode_event)
        self.opt_mode.grid(row=11, column=0, padx=20, pady=(0, 20))

        self.btn_check_updates = ctk.CTkButton(
            self.sidebar, text="Check for Updates", fg_color="#444", command=self.check_for_updates_threaded
        )
        self.btn_check_updates.grid(row=12, column=0, padx=20, pady=(0, 20), sticky="ew")

    def create_main_area(self):
        main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        main_frame.grid_rowconfigure(2, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        self.notebook = ctk.CTkTabview(main_frame)
        self.notebook.pack(fill="both", expand=True)

        self.mod_tab = self.notebook.add("Mod Manager")
        self.rcon_tab = self.notebook.add("RCON Console")

        self.create_mod_tab()
        self.create_rcon_tab()

    def create_mod_tab(self):
        top_bar = ctk.CTkFrame(self.mod_tab, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 10))
        top_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(top_bar, text="📁 Base Folder", width=100, command=self.browse_folder).pack(side="left", padx=(0, 10))
        self.entry_path = ctk.CTkEntry(top_bar, textvariable=self.path_var, placeholder_text="No base folder selected...", state="readonly")
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(top_bar, text="Open", width=60, fg_color="#444", command=self.open_in_explorer).pack(side="left")

        search_bar = ctk.CTkFrame(self.mod_tab, fg_color="transparent")
        search_bar.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(search_bar, text="Search Mods:").pack(side="left", padx=(0, 10))
        self.entry_search = ctk.CTkEntry(search_bar, textvariable=self.search_var)
        self.entry_search.pack(side="left", fill="x", expand=True)
        self.entry_search.bind("<KeyRelease>", lambda e: self.refresh_list())
        ctk.CTkButton(search_bar, text="Export List", width=80, fg_color="#444", command=self.export_json).pack(side="right", padx=(10, 0))

        self.content_container = ctk.CTkFrame(self.mod_tab, fg_color="transparent")
        self.content_container.pack(fill="both", expand=True, pady=(0, 10))
        self.content_container.grid_columnconfigure(0, weight=3)
        self.content_container.grid_columnconfigure(1, weight=1)
        self.content_container.grid_rowconfigure(0, weight=1)

        self.tree_frame = ctk.CTkFrame(self.content_container)
        self.tree_frame.grid(row=0, column=0, sticky="nsew")

        self.tree_scroll = ttk.Scrollbar(self.tree_frame, style="Custom.Vertical.TScrollbar")
        self.tree_scroll.pack(side="right", fill="y")

        self.tree = ttk.Treeview(
            self.tree_frame, columns=("size", "status", "priority"), show="tree headings", selectmode="extended", yscrollcommand=self.tree_scroll.set
        )
        self.tree_scroll.config(command=self.tree.yview)

        self.tree.column("#0", width=0, stretch=tk.NO)
        self.tree.config(displaycolumns=("size", "status", "priority"))
        self.tree.heading("size", text="Size", anchor="w")
        self.tree.heading("status", text="State", anchor="w")
        self.tree.heading("priority", text="Filename (Load Order)", anchor="w")
        self.tree.pack(fill="both", expand=True, padx=2, pady=2)

        self.preview_frame = ctk.CTkFrame(self.content_container)
        self.preview_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self.lbl_preview_title = ctk.CTkLabel(self.preview_frame, text="Mod Preview", font=ctk.CTkFont(weight="bold"))
        self.lbl_preview_title.pack(pady=(10, 5))

        self.preview_box = ctk.CTkFrame(self.preview_frame, fg_color="#1a1a1a", corner_radius=10)
        self.preview_box.pack(fill="both", expand=True, padx=10, pady=10)
        self.preview_box.pack_propagate(False)

        self.preview_canvas = ctk.CTkLabel(self.preview_box, text="No Preview", text_color=COLOR_TEXT_DIM)
        self.preview_canvas.pack(fill="both", expand=True)

        action_bar = ctk.CTkFrame(self.mod_tab, fg_color="transparent")
        action_bar.pack(fill="x", pady=(10, 0))

        self.btn_install = ctk.CTkButton(action_bar, text="Install", command=self.install_mods_threaded, fg_color=COLOR_PRIMARY)
        self.btn_install.pack(side="left", padx=(0, 10))

        self.btn_delete_mod = ctk.CTkButton(action_bar, text="Remove", fg_color=COLOR_DANGER, hover_color="#8e2922", command=self.delete_selected_threaded)
        self.btn_delete_mod.pack(side="left", padx=(0, 10))

        self.btn_enable = ctk.CTkButton(action_bar, text="Enable Selected", fg_color=COLOR_SUCCESS, hover_color="#25a06a", command=lambda: self.toggle_selected_mods_and_status("enable"))
        self.btn_enable.pack(side="left", padx=(0, 10))

        self.btn_disable = ctk.CTkButton(action_bar, text="Disable Selected", fg_color=COLOR_WARNING, hover_color="#d35400", command=lambda: self.toggle_selected_mods_and_status("disable"))
        self.btn_disable.pack(side="left", padx=(0, 10))

        self.btn_refresh = ctk.CTkButton(action_bar, text="⟳ Refresh", width=80, fg_color="#444", command=self.refresh_list)
        self.btn_refresh.pack(side="right")

        self.lbl_status = ctk.CTkLabel(self.mod_tab, textvariable=self.status_var, anchor="w", text_color=COLOR_TEXT_DIM)
        self.lbl_status.pack(fill="x", pady=(5, 0))

        self.tree.bind("<<TreeviewSelect>>", self.on_mod_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Double-1>", lambda e: self.toggle_selected_mods_and_status())

    def create_rcon_tab(self):
        self.rcon_tab.grid_columnconfigure(0, weight=1)
        self.rcon_tab.grid_rowconfigure(7, weight=1)

        connection_frame = ctk.CTkFrame(self.rcon_tab, fg_color="transparent")
        connection_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        connection_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(connection_frame, text="Server Name:", anchor="w").grid(row=0, column=0, padx=5, pady=(0, 2), sticky="w")
        self.rcon_server_name_entry = ctk.CTkEntry(connection_frame)
        self.rcon_server_name_entry.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="ew")

        ctk.CTkLabel(connection_frame, text="Server IP:", anchor="w").grid(row=2, column=0, padx=5, pady=(0, 2), sticky="w")
        self.rcon_server_ip_entry = ctk.CTkEntry(connection_frame)
        self.rcon_server_ip_entry.grid(row=3, column=0, padx=5, pady=(0, 5), sticky="ew")

        port_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
        port_frame.grid(row=4, column=0, sticky="ew")
        port_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(port_frame, text="Server Port:", anchor="w").grid(row=0, column=0, padx=5, pady=(0, 2), sticky="w")
        self.rcon_server_port_entry = ctk.CTkEntry(port_frame)
        self.rcon_server_port_entry.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="ew")

        ctk.CTkLabel(connection_frame, text="RCON Password:", anchor="w").grid(row=5, column=0, padx=5, pady=(0, 2), sticky="w")
        self.rcon_password_entry = ctk.CTkEntry(connection_frame, show="*")
        self.rcon_password_entry.grid(row=6, column=0, padx=5, pady=(0, 10), sticky="ew")

        self.rcon_output_text = CTkTextbox(self.rcon_tab)
        self.rcon_output_text.grid(row=7, column=0, padx=10, pady=(0, 10), sticky="nsew")

        input_frame = ctk.CTkFrame(self.rcon_tab, fg_color="transparent")
        input_frame.grid(row=8, column=0, padx=10, pady=(0, 10), sticky="ew")
        input_frame.grid_columnconfigure(0, weight=1)

        self.rcon_input_entry = ctk.CTkEntry(input_frame, placeholder_text="Enter RCON command...")
        self.rcon_input_entry.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="ew")
        self.rcon_input_entry.bind("<Return>", self.rcon_send_on_enter)

        self.rcon_send_button = ctk.CTkButton(input_frame, text="Send", command=self.rcon_send_command)
        self.rcon_send_button.grid(row=0, column=1, padx=0, pady=0)

        server_mgmt_frame = ctk.CTkFrame(self.rcon_tab, fg_color="transparent")
        server_mgmt_frame.grid(row=9, column=0, padx=10, pady=(0, 10), sticky="ew")
        server_mgmt_frame.grid_columnconfigure(0, weight=1)

        self.rcon_saved_servers_combobox = ctk.CTkComboBox(
            server_mgmt_frame, values=[], state="readonly", width=200
        )
        self.rcon_saved_servers_combobox.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="ew")
        self.rcon_saved_servers_combobox.configure(command=self.rcon_fill_server_credentials)

        self.rcon_save_button = ctk.CTkButton(
            server_mgmt_frame, text="Save Server", command=self.rcon_save_server_credentials, width=100
        )
        self.rcon_save_button.grid(row=0, column=1, padx=(0, 5), pady=0)

        self.rcon_delete_button = ctk.CTkButton(
            server_mgmt_frame, text="Delete Server", command=self.rcon_delete_server, fg_color=COLOR_DANGER, hover_color="#8e2922", width=100
        )
        self.rcon_delete_button.grid(row=0, column=2, padx=0, pady=0)

        self.load_rcon_saved_servers()

    # Core Logic
    def _load_config(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Config error: {e}")
                self.show_error("Config Error", "Configuration file is corrupt or unreadable. Using default settings.")
        return {"profiles": {"Default": {"mod_folder": "", "game_exe": ""}}, "active_profile": "Default"}

    def save_config(self):
        self.config = {
            "geometry": self.geometry(),
            "profiles": self.profiles,
            "active_profile": self.active_profile,
            "appearance_mode": ctk.get_appearance_mode()
        }
        if self.active_profile and self.active_profile in self.profiles:
            self.profiles[self.active_profile].update({
                "devmode": self.devmode_var.get(),
                "logfile": self.logfile_var.get(),
                "custom_params": self.custom_params_var.get()
            })
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    def on_close(self):
        if self.game_process and self.game_process.poll() is None:
            try:
                if os.name == 'nt':
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.game_process.pid)])
                else:
                    self.game_process.terminate()
                    try:
                        self.game_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.game_process.kill()
            except Exception as e:
                logging.error(f"Failed to terminate game process: {e}")
        self.save_config()
        self.destroy()

    def refresh_profile_dropdown(self):
        names = list(self.profiles.keys())
        if not names:
            names = ["Default"]
            self.profiles["Default"] = {"mod_folder": "", "game_exe": ""}
            self.active_profile = "Default"
        self.opt_profile.configure(values=names)
        if self.active_profile in names:
            self.opt_profile.set(self.active_profile)
        else:
            self.opt_profile.set(names[0])
            self.change_profile_event(names[0])

    def change_profile_event(self, new_profile: str):
        self.active_profile = new_profile
        self.load_profile_folder()
        self.update_status()
        self.save_config()

    def create_profile(self):
        name = self.ask_string("New Profile", "Enter profile name:")
        if not name:
            return
        if name in self.profiles:
            self.show_error("Error", "Profile exists.")
            return
        self.profiles[name] = {
            "mod_folder": "",
            "game_exe": "",
            "devmode": False,
            "logfile": False,
            "custom_params": ""
        }
        self.active_profile = name
        self.refresh_profile_dropdown()
        self.load_profile_folder()
        self.show_info("Profile Created", f"Profile '{name}' created.\nPlease select a Base Folder.")

    def rename_profile(self):
        if not self.active_profile or not self.profiles:
            self.show_error("Error", "No active profile to rename.")
            return
        new_name = self.ask_string("Rename", "New name:", initialvalue=self.active_profile)
        if not new_name or new_name == self.active_profile:
            return
        if new_name in self.profiles:
            self.show_error("Error", "Profile name already exists.")
            return
        data = self.profiles.pop(self.active_profile)
        self.profiles[new_name] = data
        self.active_profile = new_name
        self.refresh_profile_dropdown()
        self.save_config()
        self.update_status()

    def delete_profile(self):
        if not self.active_profile:
            self.show_error("Error", "No profile selected to delete.")
            return
        is_last_profile = len(self.profiles) == 1
        if is_last_profile:
            if not self.ask_yesno("Delete Last Profile", f"Profile '{self.active_profile}' is the only profile. Deleting it will create a new 'Default' profile. Proceed?"):
                return
        else:
            if not self.ask_yesno("Delete Profile", f"Permanently delete profile '{self.active_profile}'?"):
                return
        del self.profiles[self.active_profile]
        if self.profiles:
            self.active_profile = next(iter(self.profiles))
        else:
            self.active_profile = "Default"
            self.profiles["Default"] = {"mod_folder": "", "game_exe": ""}
        self.refresh_profile_dropdown()
        self.load_profile_folder()
        self.save_config()
        self.show_info("Profile Deleted", "Profile successfully deleted.")

    def load_profile_folder(self):
        if not self.active_profile:
            return
        profile = self.profiles[self.active_profile]
        folder_str = profile.get("mod_folder", "")
        self.game_exe_path = Path(profile.get("game_exe", "")) if profile.get("game_exe") else None
        self.devmode_var.set(profile.get("devmode", False))
        self.logfile_var.set(profile.get("logfile", False))
        self.custom_params_var.set(profile.get("custom_params", ""))
        if folder_str and os.path.exists(folder_str):
            self.set_mod_folder(Path(folder_str))
        else:
            self.path_var.set("Base folder path missing or invalid for this profile.")
            self.mod_folder = None
            self.refresh_list()

    def browse_folder(self):
        default_path = Path.home()
        if os.name == 'nt':
            default_path = Path("C:/")
        elif os.name == 'posix':
            default_path = Path.home() / "Games"
        path_str = filedialog.askdirectory(parent=self, title="Select JK2/Base Folder", initialdir=str(default_path))
        if path_str:
            path_obj = Path(path_str)
            self.set_mod_folder(path_obj)
            if self.active_profile:
                self.profiles[self.active_profile]["mod_folder"] = path_str
                self.save_config()
                self.update_status()

    def set_mod_folder(self, path_obj: Path):
        self.mod_folder = path_obj
        self.path_var.set(str(path_obj))
        disabled = self.mod_folder / DISABLED_DIR_NAME
        if not disabled.exists():
            try:
                disabled.mkdir()
            except Exception as e:
                logging.error(f"Failed to create disabled directory: {e}")
        self.refresh_list()

    def open_in_explorer(self):
        if not self.mod_folder:
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", str(self.mod_folder)])
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", str(self.mod_folder)])
            else:
                subprocess.Popen(["xdg-open", str(self.mod_folder)])
        except Exception as e:
            self.show_error("Error", f"Could not open folder: {e}")

    def _clear_treeview(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def _collect_mods(self) -> list[dict]:
        mods = []
        search = self.search_var.get().lower()

        def collect(base: Path, enabled: bool):
            if not base.exists():
                return
            try:
                for f in base.iterdir():
                    if not f.is_file():
                        continue
                    if f.name in PROTECTED_MODS:
                        continue
                    if f.suffix.lower() != ".pk3":
                        continue
                    if search and search not in f.name.lower():
                        continue
                    size_mb = f.stat().st_size / (1024 * 1024)
                    mods.append({
                        "path": f,
                        "enabled": enabled,
                        "size": f"{size_mb:.2f} MB",
                        "sort_key": f.name.lower()
                    })
            except Exception as e:
                logging.error(f"Error collecting mods: {e}")

        if self.mod_folder:
            collect(self.mod_folder, True)
            collect(self.mod_folder / DISABLED_DIR_NAME, False)

        mods.sort(key=lambda m: m["sort_key"])
        return mods

    def _populate_treeview(self, mods: list[dict]):
        self.mod_index.clear()
        for i, mod in enumerate(mods):
            iid = f"mod_{i}"
            self.mod_index[iid] = mod["path"]
            status_text = "ENABLED" if mod["enabled"] else "DISABLED"
            tag = "enabled" if mod["enabled"] else "disabled"
            self.tree.insert("", "end", iid=iid, values=(mod["size"], status_text, mod["path"].name), tags=(tag,))

    def refresh_list(self):
        self._clear_treeview()
        mods = self._collect_mods()
        self._populate_treeview(mods)
        self.auto_adjust_columns()
        self.update_status()

    def auto_adjust_columns(self):
        if not self.tree.get_children():
            self.tree.column("size", width=100, stretch=tk.NO)
            self.tree.column("status", width=100, stretch=tk.NO)
            self.tree.column("priority", width=400, stretch=tk.YES)
            return
        PIXEL_PER_CHAR = 10
        padding = 20
        widths = {
            "size": len(self.tree.heading("size", option="text")) * PIXEL_PER_CHAR,
            "status": len(self.tree.heading("status", option="text")) * PIXEL_PER_CHAR,
        }
        for iid in self.tree.get_children():
            values = self.tree.item(iid, 'values')
            if len(values) >= 3:
                widths["size"] = max(widths["size"], len(values[0]) * PIXEL_PER_CHAR)
                widths["status"] = max(widths["status"], len(values[1]) * PIXEL_PER_CHAR)
        self.tree.column("size", width=max(100, widths["size"] + padding), stretch=tk.NO)
        self.tree.column("status", width=max(100, widths["status"] + padding), stretch=tk.NO)
        self.tree.column("priority", minwidth=400, width=400, stretch=tk.YES)

    def update_status(self):
        if not self.active_profile:
            self.status_var.set("No profile selected.")
            return
        enabled_count = sum(1 for p in self.mod_index.values() if p.parent == self.mod_folder)
        disabled_count = sum(1 for p in self.mod_index.values() if p.parent == (self.mod_folder / DISABLED_DIR_NAME))
        self.status_var.set(f"Profile: {self.active_profile} | Enabled: {enabled_count} | Disabled: {disabled_count} | Total: {enabled_count + disabled_count}")

    def toggle_mod_action(self, path: Path, target_state: str | None = None) -> bool:
        if not self.mod_folder:
            return False
        is_enabled = path.parent == self.mod_folder
        if target_state == "enable" and is_enabled:
            return False
        if target_state == "disable" and not is_enabled:
            return False
        target_dir = self.mod_folder if not is_enabled else self.mod_folder / DISABLED_DIR_NAME
        dest = target_dir / path.name
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if os.name != 'nt':
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
            path.rename(dest)
            return True
        except Exception as e:
            self.show_error("Toggle Error", f"Failed to move {path.name}: {e}")
            return False

    def toggle_selected_mods_and_status(self, force: str | None = None):
        if not self.tree.selection():
            return
        success = True
        for iid in self.tree.selection():
            if iid in self.mod_index:
                if not self.toggle_mod_action(self.mod_index[iid], force):
                    success = False
        self.refresh_list()
        if not success:
            self.show_error("Error", "Some mods failed to toggle.")

    def install_mods_threaded(self):
        if not self.mod_folder:
            return self.show_error("Error", "Select Base Folder first.")
        files = self.ask_open_files(title="Select PK3 Files", filetypes=[("PK3", "*.pk3")])
        if not files:
            return
        self.set_processing_state(True)
        threading.Thread(target=self._install_worker, args=(files,), daemon=True).start()

    def _install_worker(self, files: list[str]):
        count, errors = 0, 0
        target_dir = self.mod_folder
        for i, f_path_str in enumerate(files):
            self.after(0, lambda: self.status_var.set(f"Installing... ({i+1}/{len(files)})"))
            f = Path(f_path_str)
            try:
                if (target_dir / f.name).exists():
                    if not self.ask_yesno("Overwrite?", f"'{f.name}' already exists. Overwrite?"):
                        continue
                shutil.copy2(f, target_dir / f.name)
                count += 1
            except Exception as e:
                logging.error(f"Failed to install {f.name}: {e}")
                errors += 1
        self.after(0, lambda: self._op_complete(f"Installed {count} mods ({errors} errors)."))

    def delete_selected_threaded(self):
        items = self.tree.selection()
        if not items:
            return
        valid_items = [iid for iid in items if iid in self.mod_index]
        if not valid_items:
            return
        if not self.ask_yesno("Delete", f"Permanently delete {len(valid_items)} file(s)?"):
            return
        self.set_processing_state(True)
        threading.Thread(target=self._delete_worker, args=(valid_items,), daemon=True).start()

    def _delete_worker(self, items: list[str]):
        count = 0
        for iid in items:
            try:
                self.mod_index[iid].unlink()
                count += 1
            except Exception as e:
                logging.error(f"Failed to delete {self.mod_index[iid].name}: {e}")
        self.after(0, lambda: self._op_complete(f"Deleted {count} files."))

    def start_game_threaded(self):
        if not self.game_exe_path or not Path(self.game_exe_path).exists():
            self.show_info("Select Executable", "Please locate the game executable, for example 'jk2mvmp(.exe)' or 'nwhmp(.exe)'.")
            exe = filedialog.askopenfilename(parent=self, title="Select Game Executable")
            if not exe:
                return
            self.game_exe_path = Path(exe)
            if self.active_profile:
                self.profiles[self.active_profile]["game_exe"] = str(exe)
            self.save_config()
        self.set_processing_state(True)
        threading.Thread(target=self._launch_game, daemon=True).start()

    def _launch_game(self):
        try:
            exe_path = Path(self.game_exe_path)
            if os.name != 'nt':
                exe_path.chmod(exe_path.stat().st_mode | stat.S_IEXEC)
            params = []
            if self.devmode_var.get():
                params.append("+developer 1")
            if self.logfile_var.get():
                params.append("+logfile 2")
            custom = self.custom_params_var.get().strip()
            if custom:
                params.extend(custom.split())
            command = [str(exe_path)] + params
            self.game_process = subprocess.Popen(command, cwd=str(exe_path.parent))
            self.after(0, lambda: self._op_complete("Game launched successfully."))
        except Exception as e:
            error_msg = f"Failed to launch game: {e}"
            self.after(0, lambda: self.show_error("Launch Error", error_msg))
            self.after(0, lambda: self.set_processing_state(False))

    def _op_complete(self, msg: str):
        self.set_processing_state(False)
        self.status_var.set(msg)
        self.refresh_list()

    def set_processing_state(self, is_processing: bool):
        state = "disabled" if is_processing else "normal"
        self.btn_launch.configure(state=state)
        self.btn_install.configure(state=state)
        self.btn_enable.configure(state=state)
        self.btn_disable.configure(state=state)
        self.btn_delete_mod.configure(state=state)

    def rename_mod_dialog(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid not in self.mod_index:
            return
        path = self.mod_index[iid]
        new_name = self.ask_string("Rename", "New filename:", initialvalue=path.name)
        if not new_name:
            return
        if not new_name.lower().endswith(".pk3"):
            new_name += ".pk3"
        if not re.match(r'^[a-zA-Z0-9_\-\.]+\.pk3$', new_name):
            self.show_error("Error", "Invalid filename.")
            return
        try:
            path.rename(path.parent / new_name)
            self.refresh_list()
        except Exception as e:
            self.show_error("Error", str(e))

    def export_json(self):
        if not self.mod_folder:
            return
        filename = self.ask_save_file(title="Export JSON", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not filename:
            return
        mod_list = []
        self._load_order_counter = 1

        def collect_dir_data(base: Path, status: str):
            if not base.exists():
                return
            sorted_files = sorted(base.iterdir(), key=lambda p: p.name.lower())
            for fpath in sorted_files:
                if fpath.suffix.lower() == ".pk3":
                    if fpath.name in PROTECTED_MODS:
                        continue
                    file_stats = fpath.stat()
                    size_bytes = file_stats.st_size
                    size_mb = size_bytes / (1024 * 1024)
                    file_hash = get_sha256_hash(fpath)
                    raw_timestamp = file_stats.st_mtime
                    formatted_time = datetime.datetime.fromtimestamp(raw_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    current_order = self._load_order_counter
                    self._load_order_counter += 1
                    mod_list.append({
                        "name": fpath.name,
                        "status": status,
                        "load_order": current_order,
                        "size_mb": size_mb,
                        "path": str(fpath),
                        "sha256": file_hash,
                        "last_modified": formatted_time
                    })

        collect_dir_data(self.mod_folder, "Enabled")
        collect_dir_data(self.mod_folder / DISABLED_DIR_NAME, "Disabled")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(mod_list, f, indent=4)
            self.show_info("Exported", f"List saved to {filename}")
        except Exception as e:
            self.show_error("Export Error", f"Failed to save JSON: {e}")

    # RCON Logic
    def load_rcon_saved_servers(self):
        self.rcon_config.read(RCON_CONFIG_FILE)
        saved_servers = self.rcon_config.sections()
        self.rcon_saved_servers_combobox.configure(values=saved_servers)

    def rcon_fill_server_credentials(self, choice: str):
        server_name = choice
        if server_name:
            self.rcon_config.read(RCON_CONFIG_FILE)
            self.rcon_server_name_entry.delete(0, tk.END)
            self.rcon_server_name_entry.insert(0, server_name)
            self.rcon_server_ip_entry.delete(0, tk.END)
            self.rcon_server_ip_entry.insert(0, self.rcon_config[server_name]['ip'])
            self.rcon_server_port_entry.delete(0, tk.END)
            self.rcon_server_port_entry.insert(0, self.rcon_config[server_name]['port'])
            self.rcon_password_entry.delete(0, tk.END)
            self.rcon_password_entry.insert(0, self.rcon_config[server_name]['password'])

    def rcon_delete_server(self):
        server_name = self.rcon_saved_servers_combobox.get()
        if not server_name:
            self.show_error("Error", "No server selected to delete.")
            return
        if not self.ask_yesno("Delete Server", f"Permanently delete server '{server_name}'?"):
            return
        try:
            self.rcon_config.read(RCON_CONFIG_FILE)
            if server_name in self.rcon_config:
                self.rcon_config.remove_section(server_name)
                with open(RCON_CONFIG_FILE, 'w') as configfile:
                    self.rcon_config.write(configfile)
                self.load_rcon_saved_servers()
                self.show_info("Server Deleted", f"Server '{server_name}' successfully deleted.")
        except Exception as e:
            self.show_error("Error", f"Failed to delete server: {e}")

    def rcon_save_server_credentials(self):
        server_name = self.rcon_server_name_entry.get()
        server_ip = self.rcon_server_ip_entry.get()
        server_port = self.rcon_server_port_entry.get()
        rcon_password = self.rcon_password_entry.get()
        if not server_name or not server_ip or not server_port:
            self.show_error("Error", "Server name, IP, and port are required.")
            return
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', server_name):
            self.show_error("Error", "Invalid server name.")
            return
        self.rcon_config.read(RCON_CONFIG_FILE)
        self.rcon_config[server_name] = {
            'ip': server_ip,
            'port': server_port,
            'password': rcon_password
        }
        with open(RCON_CONFIG_FILE, 'w') as configfile:
            self.rcon_config.write(configfile)
        self.load_rcon_saved_servers()
        self.show_info("Server Saved", f"Server '{server_name}' successfully saved.")

    def rcon_send_on_enter(self, event):
        self.rcon_send_command()

    def rcon_send_command(self):
        server_ip = self.rcon_server_ip_entry.get()
        server_port = self.rcon_server_port_entry.get()
        rcon_password = self.rcon_password_entry.get()
        command = self.rcon_input_entry.get()
        if not server_ip or not server_port or not command:
            self.show_error("Error", "Server IP, port, and command are required.")
            return
        if not re.match(r'^[a-zA-Z0-9_\-\.\s]+$', command):
            self.show_error("Error", "Invalid command.")
            return
        try:
            server_port = int(server_port)
            self.socket.sendto(
                b"\xff\xff\xff\xffrcon %s %s\n" % (rcon_password.encode(), command.encode()),
                (server_ip, server_port)
            )
            response, _ = self.socket.recvfrom(4096)
            response = response.decode('utf-8', 'ignore')
            cleaned_response = clean_rcon_response(response)
            self.rcon_output_text.insert("end", f">>> {command}\n{cleaned_response}\n\n")
            self.rcon_output_text.see("end")
        except socket.timeout:
            self.rcon_output_text.insert("end", f"Connection timed out.\n\n")
            self.rcon_output_text.see("end")
        except ValueError:
            self.show_error("Error", "Server port must be a valid number.")
        except Exception as e:
            self.rcon_output_text.insert("end", f"Error: {str(e)}\n\n")
            self.rcon_output_text.see("end")
        finally:
            self.rcon_input_entry.delete(0, tk.END)

    # UI Helpers
    def on_mod_selected(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        mod_name = selection[0]
        mod_path = self.mod_index.get(mod_name)
        if mod_path and mod_path.suffix.lower() == ".pk3":
            self.update_preview(mod_path)
        else:
            self.preview_canvas.configure(image=None, text="No Preview Available")

    def update_preview(self, pk3_path: Path):
        try:
            with zipfile.ZipFile(pk3_path, 'r') as z:
                img_exts = {'.jpg', '.jpeg', '.png', '.tga', '.gif', '.bmp'}
                image_files = [f for f in z.namelist() if any(f.lower().endswith(ext) for ext in img_exts)]
                if not image_files:
                    self.preview_canvas.configure(image=None, text="No Image Found")
                    return
                best_match = image_files[0]
                for f in image_files:
                    if "levelshot" in f.lower() or "preview" in f.lower():
                        best_match = f
                        break
                with z.open(best_match) as img_file:
                    img_data = img_file.read()
                    try:
                        img = Image.open(io.BytesIO(img_data))
                        preview_width = self.preview_box.winfo_width() - 20
                        ratio = preview_width / float(img.size[0])
                        preview_height = int((float(img.size[1]) * float(ratio)))
                        img = img.resize((preview_width, preview_height), Image.Resampling.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(preview_width, preview_height))
                        self.preview_canvas.configure(image=ctk_img, text="")
                        self.preview_canvas.image = ctk_img
                    except Exception as e:
                        self.preview_canvas.configure(image=None, text="Unsupported Image")
        except Exception as e:
            self.preview_canvas.configure(image=None, text="Preview Error")

    def show_info(self, title: str, message: str):
        CTkMessagebox(title=title, message=message, icon="info", option_focus=1)

    def show_error(self, title: str, message: str):
        CTkMessagebox(title=title, message=message, icon="cancel")

    def ask_yesno(self, title: str, message: str) -> bool:
        msg = CTkMessagebox(title=title, message=message, icon="question", option_1="No", option_2="Yes")
        response = msg.get()
        return response == "Yes"

    def ask_string(self, title: str, prompt: str, initialvalue: str = "") -> str | None:
        return ctk_ask_string(self, title, prompt, initialvalue)

    def ask_open_files(self, title: str, filetypes: list[tuple[str, str]]) -> list[str]:
        return list(filedialog.askopenfilenames(parent=self, title=title, filetypes=filetypes))

    def ask_save_file(self, title: str, defaultextension: str, filetypes: list[tuple[str, str]]) -> str | None:
        return filedialog.asksaveasfilename(parent=self, title=title, defaultextension=defaultextension, filetypes=filetypes)

    def create_context_menu(self):
        mode = ctk.get_appearance_mode()
        if mode == "Light":
            bg_color = LIGHT_BG_COLOR
            fg_color = "#000000"
            select_bg = COLOR_PRIMARY
            select_fg = "#ffffff"
        else:
            bg_color = "#343638"
            fg_color = "#ffffff"
            select_bg = COLOR_PRIMARY
            select_fg = "#ffffff"
        self.context_menu = tk.Menu(
            self, tearoff=0, bg=bg_color, fg=fg_color, activebackground=select_bg,
            activeforeground=select_fg, selectcolor=select_fg, relief="flat", borderwidth=0
        )
        self.context_menu.add_command(label="Toggle State", command=self.toggle_selected_mods_and_status)
        self.context_menu.add_command(label="Rename File", command=self.rename_mod_dialog)
        self.context_menu.add_separator(background=bg_color)
        self.context_menu.add_command(label="Delete File", command=self.delete_selected_threaded)

    def show_context_menu(self, event):
        if hasattr(self, 'context_menu') and self.context_menu:
            self.context_menu.destroy()
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.create_context_menu()
            self.context_menu.post(event.x_root, event.y_root)

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)
        self.update_treeview_style(new_appearance_mode)
        if hasattr(self, 'context_menu') and self.context_menu:
            self.context_menu.destroy()
        self.create_context_menu()
        self.config["appearance_mode"] = new_appearance_mode
        self.save_config()

    def update_treeview_style(self, mode: str):
        style = ttk.Style()
        style.theme_use("default")
        if mode == "Light":
            bg_color = "#ffffff"
            fg_color = "#000000"
            field_bg = "#ffffff"
            header_bg = "#e0e0e0"
            header_fg = "#000000"
            select_bg = COLOR_PRIMARY
            grid_line_color = "#cccccc"
            scroll_trough = "#f0f0f0"
            scroll_thumb = "#cccccc"
            scroll_arrow = "#000000"
        else:
            bg_color = "#2b2b2b"
            fg_color = "#ffffff"
            field_bg = "#2b2b2b"
            header_bg = "#343638"
            header_fg = "#ffffff"
            select_bg = COLOR_PRIMARY
            grid_line_color = "#444444"
            scroll_trough = COLOR_SCROLL_TROUGH
            scroll_thumb = COLOR_SCROLL_THUMB
            scroll_arrow = COLOR_SCROLL_ARROW

        style.configure(
            "Treeview", background=bg_color, foreground=fg_color, fieldbackground=field_bg, borderwidth=0,
            font=("Roboto", 11), rowheight=28, fieldrelief="solid", bordercolor=grid_line_color
        )
        style.configure(
            "Treeview.Heading", background=header_bg, foreground=header_fg, relief="flat",
            font=("Roboto", 11, "bold"), separator=True
        )
        style.map(
            "Treeview.Heading", background=[("!active", header_bg), ("active", header_bg)], foreground=[("!active", header_fg), ("active", header_fg)], relief=[("active", "flat")]
        )
        style.map(
            "Treeview", background=[("selected", select_bg)], fieldbackground=[("focus", field_bg), ("!focus", field_bg)]
        )
        style.layout(
            "Treeview", [('Treeview.treearea', {'sticky': 'nswe'})]
        )
        style.configure(
            "Custom.Vertical.TScrollbar", troughcolor=scroll_trough, background=scroll_thumb,
            fieldbackground=scroll_thumb, fieldrelief="flat", bordercolor=scroll_trough,
            arrowcolor=scroll_arrow, troughrelief="flat", relief="flat", arrowsize=16
        )
        style.map(
            "Custom.Vertical.TScrollbar", background=[("active", scroll_thumb)], troughcolor=[("active", scroll_trough)], bordercolor=[("active", scroll_trough)]
        )

        self.tree.tag_configure("enabled", foreground=COLOR_SUCCESS)
        self.tree.tag_configure("disabled", foreground=COLOR_DANGER)

    def check_for_updates_threaded(self):
        self.btn_check_updates.configure(state="disabled")
        threading.Thread(target=self.check_for_updates, daemon=True).start()

    def check_for_updates(self):
        try:
            response = requests.get(UPDATE_VERSION_URL, timeout=5)
            response.raise_for_status()
            latest_version = response.text.strip()
            if self.version_tuple(latest_version) <= self.version_tuple(APP_VERSION):
                self.after(0, lambda: self.show_info("Up to Date", f"You are running the latest version ({APP_VERSION})."))
            else:
                self.after(0, lambda: self.show_info(
                    "Update Available",
                    f"A new version is available!\n\nCurrent: {APP_VERSION}\nLatest: {latest_version}\n\nCheck the GitHub Repository."
                ))
        except Exception as e:
            self.after(0, lambda: self.show_error("Update Check Failed", f"Could not check for updates.\n\n{e}"))
        finally:
            self.after(0, lambda: self.btn_check_updates.configure(state="normal"))

    def version_tuple(self, v: str) -> tuple[int, int, int]:
        try:
            return tuple(map(int, v.split(".")))
        except ValueError:
            return (0, 0, 0)

if __name__ == "__main__":
    scaling = get_dpi_scaling()
    ctk.set_widget_scaling(scaling)
    ctk.set_window_scaling(scaling)

    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("dark-blue")

    root = ctk.CTk()
    root.withdraw()
    splash = CTkSplash()

    def start_app():
        splash.destroy()
        root.destroy()
        app = JK2ModManager()
        app.mainloop()

    splash.after(1000, start_app)
    splash.mainloop()
