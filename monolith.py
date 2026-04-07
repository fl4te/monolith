import pil_config

import base64
import configparser
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import io
import json
import logging
import os
import queue
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from threading import Timer
from typing import Callable
import zipfile
import tarfile
from pathlib import Path

from tkinter import filedialog, ttk
import tkinter as tk
import customtkinter as ctk
import requests
from PIL import Image


try:
    from _version import __version__ as APP_VERSION
except ImportError:
    _version_file = Path(__file__).parent / "version.txt"
    APP_VERSION = _version_file.read_text().strip() if _version_file.exists() else "0.0.0"


def _get_x11_dpi_scaling() -> float | None:
    try:
        output = subprocess.check_output(["xrdb", "-query"], text=True)
        for line in output.splitlines():
            if "Xft.dpi" in line:
                dpi = float(line.split(":")[1].strip())
                return dpi / 96.0
    except Exception as e:
        logging.debug(f"xrdb DPI detection failed: {e}")
    return None


def get_dpi_scaling() -> float:
    for var in ["GDK_SCALE", "QT_SCALE_FACTOR", "ELM_SCALE"]:
        val = os.environ.get(var)
        if val:
            try:
                return max(0.5, min(float(val), 3.0))
            except ValueError:
                continue

    scaling = 1.0

    try:
        if os.name == "nt":
            try:
                monitor = ctypes.windll.user32.MonitorFromPoint(
                    wintypes.POINT(0, 0), 1
                )
                dpi_x = ctypes.c_uint()
                ctypes.windll.shcore.GetDpiForMonitor(
                    monitor, 0, ctypes.byref(dpi_x), None
                )
                scaling = dpi_x.value / 96.0
            except Exception as e:
                logging.warning(f"Windows DPI scaling failed: {e}")

        elif sys.platform == "darwin":
            try:
                from AppKit import NSScreen
                scaling = NSScreen.mainScreen().backingScaleFactor()
            except Exception as e:
                logging.warning(f"macOS DPI scaling failed: {e}")

        elif os.name == "posix":
            dpi_scaling = _get_x11_dpi_scaling()
            if dpi_scaling:
                scaling = dpi_scaling
            else:
                scaling = 1.0

    except Exception as e:
        logging.warning(f"General DPI detection failed: {e}")

    return max(0.5, min(scaling, 3.0))

def _platform_config_dir(app_name: str) -> Path:
    if sys.platform.startswith("linux"):
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return base / app_name
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / app_name
    return Path.home() / f".{app_name.lower()}"

def _get_config_dir() -> Path:
    old = _platform_config_dir("JK2ModManager")
    new = _platform_config_dir("monolith")
    if old.exists() and old.is_dir():
        new.mkdir(parents=True, exist_ok=True)
        for fname in ["config.json", "servers.ini", "error.log"]:
            src = old / fname
            if src.exists():
                shutil.copy2(src, new / fname)
        shutil.rmtree(old, ignore_errors=True)
    else:
        new.mkdir(parents=True, exist_ok=True)
    return new

CONFIG_DIR      = _get_config_dir()
CONFIG_FILE     = CONFIG_DIR / "config.json"
RCON_CONFIG_FILE = CONFIG_DIR / "servers.ini"
LOG_FILE        = CONFIG_DIR / "error.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

DISABLED_DIR_NAME = "_disabled"

PROTECTED_ASSETS: frozenset[str] = frozenset(
    {f"assets{i}.pk3" for i in range(7)}
    | {"assetsmv.pk3", "assetsmv2.pk3"}
    | {"jk2pro-assets.pk3", "jk2pro-bins.pk3"}
    | {"nwh-assets.pk3", "nwh-bins.pk3"}
)

JK2_COLORS: dict[str, str] = {
    "0": "#383838", "1": "#ff4444", "2": "#44ff44", "3": "#ffff44",
    "4": "#4488ff", "5": "#44ffff", "6": "#ff44ff", "7": "#ffffff",
    "8": "#383838",
}
RCON_DEFAULT_COLOR = "#ffffff"
RCON_CMD_COLOR     = "#00d4ff"

C = {
    "bg":           "#0d0d1a",
    "surface":      "#12122a",
    "surface2":     "#1a1a35",
    "border":       "#252550",
    "primary":      "#3a86ff",
    "accent":       "#00d4ff",
    "success":      "#8338ec",
    "danger":       "#ff006e",
    "warning":      "#fb5607",
    "text":         "#e8e8f0",
    "text_dim":     "#7070a0",
    "text_bright":  "#ffffff",
    "scrollbar":    "#2a2a55",
    "trough":       "#0d0d1a",
}

FONT_MONO = "Courier"

class ModStatus(Enum):
    ENABLED  = "✔"
    DISABLED = "✘"

@dataclass
class Mod:
    path: Path
    status: ModStatus

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @property
    def size_str(self) -> str:
        b = self.size_bytes
        if b >= 1_048_576:
            return f"{b / 1_048_576:.2f} MB"
        if b >= 1024:
            return f"{b / 1024:.1f} KB"
        return f"{b} B"

    @property
    def is_enabled(self) -> bool:
        return self.status == ModStatus.ENABLED

@dataclass
class Profile:
    name:          str
    mod_folder:    str = ""
    game_exe:      str = ""
    devmode:       bool = False
    logfile:       bool = False
    custom_params: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(name: str, d: dict) -> "Profile":
        return Profile(
            name=name,
            mod_folder=d.get("mod_folder", ""),
            game_exe=d.get("game_exe", ""),
            devmode=d.get("devmode", False),
            logfile=d.get("logfile", False),
            custom_params=d.get("custom_params", ""),
        )

@dataclass
class AppConfig:
    profiles:       dict[str, Profile] = field(default_factory=dict)
    active_profile: str = "Default"
    geometry:       str = "1100x720"

    def to_dict(self) -> dict:
        return {
            "profiles": {n: p.to_dict() for n, p in self.profiles.items()},
            "active_profile": self.active_profile,
            "geometry": self.geometry,
        }

    @staticmethod
    def load() -> "AppConfig":
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                profiles = {
                    n: Profile.from_dict(n, d)
                    for n, d in raw.get("profiles", {}).items()
                }
                if not profiles:
                    profiles = {"Default": Profile(name="Default")}
                return AppConfig(
                    profiles=profiles,
                    active_profile=raw.get("active_profile", "Default"),
                    geometry=raw.get("geometry", "1100x720"),
                )
        except Exception as e:
            logging.error(f"Config load failed: {e}")
        return AppConfig(profiles={"Default": Profile(name="Default")})

    def save(self) -> None:
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.to_dict(), indent=4), encoding="utf-8"
            )
        except Exception as e:
            logging.error(f"Config save failed: {e}")

class ModRepository:
    def __init__(self, folder: Path):
        self.folder = folder
        self._disabled_dir = folder / DISABLED_DIR_NAME
        self._disabled_dir.mkdir(parents=True, exist_ok=True)

    def list_mods(self, search: str = "") -> list[Mod]:
        mods: list[Mod] = []
        s = search.lower()

        def _scan(base: Path, status: ModStatus) -> None:
            if not base.exists():
                return
            try:
                for f in base.iterdir():
                    if not f.is_file():
                        continue
                    if f.suffix.lower() != ".pk3":
                        continue
                    if f.name in PROTECTED_ASSETS:
                        continue
                    if s and s not in f.name.lower():
                        continue
                    mods.append(Mod(path=f, status=status))
            except Exception as e:
                logging.error(f"Scan error in {base}: {e}")

        _scan(self.folder, ModStatus.ENABLED)
        _scan(self._disabled_dir, ModStatus.DISABLED)
        mods.sort(key=lambda m: m.name.lower())
        return mods

    def toggle(self, mod: Mod, force: str | None = None) -> bool:
        if force == "enable" and mod.is_enabled:
            return False
        if force == "disable" and not mod.is_enabled:
            return False
        target = self.folder if not mod.is_enabled else self._disabled_dir
        dest = target / mod.name
        try:
            target.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                mod.path.chmod(mod.path.stat().st_mode | stat.S_IWUSR)
            mod.path.rename(dest)
            return True
        except Exception as e:
            logging.error(f"Toggle failed for {mod.name}: {e}")
            return False

    def install(self, src: Path, overwrite: bool = False) -> bool:
        dest = self.folder / src.name
        if dest.exists() and not overwrite:
            return False
        try:
            shutil.copy2(src, dest)
            return True
        except Exception as e:
            logging.error(f"Install failed for {src.name}: {e}")
            return False

    def delete(self, mod: Mod) -> bool:
        try:
            mod.path.unlink()
            return True
        except Exception as e:
            logging.error(f"Delete failed for {mod.name}: {e}")
            return False

    def rename(self, mod: Mod, new_name: str) -> bool:
        try:
            mod.path.rename(mod.path.parent / new_name)
            return True
        except Exception as e:
            logging.error(f"Rename failed: {e}")
            return False

    def export_manifest(self, dest_path: Path) -> int:
        mods = self.list_mods()
        records = []
        for i, mod in enumerate(mods, 1):
            try:
                st = mod.path.stat()
                records.append({
                    "name":          mod.name,
                    "status":        mod.status.value,
                    "load_order":    i,
                    "size_mb":       round(st.st_size / 1_048_576, 4),
                    "path":          str(mod.path),
                    "sha256":        _sha256(mod.path),
                    "last_modified": datetime.datetime.fromtimestamp(st.st_mtime)
                                     .strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception as e:
                logging.error(f"Manifest error for {mod.name}: {e}")
        dest_path.write_text(json.dumps(records, indent=4), encoding="utf-8")
        return len(records)

    def get_preview_image(self, mod: Mod) -> Image.Image | None:
        try:
            with zipfile.ZipFile(mod.path, "r") as z:
                return _pick_preview(z)
        except Exception as e:
            logging.debug(f"Preview extraction failed for {mod.name}: {e}")
            return None

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logging.error(f"SHA256 failed for {path}: {e}")
        return "ERROR"

def _version_tuple(v: str) -> tuple[int, int, int]:
    try:
        parts = v.replace("v", "").split(".")
        while len(parts) < 3:
            parts.append("0")
        return tuple(map(int, parts[:3]))
    except ValueError:
        return (0, 0, 0)

def _pick_preview(z: zipfile.ZipFile) -> Image.Image | None:
    IMG_EXT = {".jpg", ".jpeg", ".png", ".tga"}
    FOLDER_SCORES = {
        "levelshots/": 10000, "models/players/": 400,
        "models/weapons2/": 300, "gfx/menus/": 100, "gfx/ui/": 50,
    }
    TRASH_KW = {"eye", "mouth", "face", "hand", "torso", "arm", "leg",
                "hips", "cap", "_glow", "_spec", "_norm", "_reflect"}

    best_name, best_score = None, -99999
    for name in z.namelist():
        lo = name.lower()
        if name.endswith("/") or "__macosx" in lo or "thumbs.db" in lo:
            continue
        stem, ext = os.path.splitext(os.path.basename(lo))
        if ext not in IMG_EXT:
            continue
        score = 1
        for folder, w in FOLDER_SCORES.items():
            if folder in lo:
                score += w
                break
        if stem == "preview":           score += 1600
        elif stem == "icon_default":    score += 1500
        elif stem == "levelshot":       score += 1000
        elif stem.startswith("map_"):   score += 400
        if any(k in lo for k in ("icon_blue", "icon_red", "_blue", "_red", "/team/")):
            score -= 800
        if any(k in stem for k in TRASH_KW):
            score -= 15000
        if ext in (".jpg", ".jpeg", ".png", ".tga"):
            score += 10
        if score > best_score:
            best_score, best_name = score, name

    if not best_name:
        return None
    with z.open(best_name) as fh:
        data = io.BytesIO(fh.read())
        img = Image.open(data)
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode else "RGB")
        return img

def parse_rcon_colored(raw: str) -> list[tuple[str, str]]:
    if raw.startswith("\xff\xff\xff\xff"):
        raw = raw[4:]
    if raw.startswith("print\n"):
        raw = raw[6:]
    lines = [ln.rstrip() for ln in raw.split("\n") if ln.strip()]
    joined = "\n".join(lines)
    if not joined:
        return []
    segments: list[tuple[str, str]] = []
    color = RCON_DEFAULT_COLOR
    buf = ""
    i = 0
    while i < len(joined):
        ch = joined[i]
        if ch == "^" and i + 1 < len(joined) and joined[i + 1] in JK2_COLORS:
            if buf:
                segments.append((buf, color))
                buf = ""
            color = JK2_COLORS[joined[i + 1]]
            i += 2
        else:
            buf += ch
            i += 1
    if buf:
        segments.append((buf, color))
    return segments

def _center_on_parent(dialog: ctk.CTkToplevel, parent: ctk.CTk,
                       w: int, h: int) -> None:
    dialog.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width()  - w) // 2
    y = parent.winfo_y() + (parent.winfo_height() - h) // 2
    dialog.geometry(f"{w}x{h}+{x}+{y}")

def _make_modal(dialog: ctk.CTkToplevel, parent: ctk.CTk) -> None:
    dialog.transient(parent)
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.focus_set()

class _BaseDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, w: int = 420, h: int = 160):
        super().__init__(parent)
        self.title("")
        self.resizable(False, False)
        self.configure(fg_color=C["surface"])
        _center_on_parent(self, parent, w, h)
        _make_modal(self, parent)

    def _btn(self, parent, text: str, cmd: Callable,
             fg: str, hover: str) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, width=88, height=32,
            fg_color=fg, hover_color=hover,
            font=ctk.CTkFont(size=12), corner_radius=6,
            command=cmd,
        )

class InfoDialog(_BaseDialog):
    def __init__(self, parent: ctk.CTk, message: str):
        super().__init__(parent)
        ctk.CTkLabel(self, text=message, font=ctk.CTkFont(size=12),
                     text_color=C["text"], wraplength=380).pack(padx=20, pady=(24, 12))
        self._btn(self, "OK", self.destroy, C["primary"], C["accent"]).pack(pady=(0, 20))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda _: self.destroy())

class ErrorDialog(_BaseDialog):
    def __init__(self, parent: ctk.CTk, message: str):
        super().__init__(parent)
        ctk.CTkLabel(self, text=message, font=ctk.CTkFont(size=12),
                     text_color=C["text"], wraplength=380).pack(padx=20, pady=(24, 12))
        self._btn(self, "OK", self.destroy, C["danger"], C["warning"]).pack(pady=(0, 20))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda _: self.destroy())

class YesNoDialog(_BaseDialog):
    def __init__(self, parent: ctk.CTk, message: str):
        super().__init__(parent, w=440, h=170)
        self.result = False
        ctk.CTkLabel(self, text=message, font=ctk.CTkFont(size=12),
                     text_color=C["text"], wraplength=400).pack(padx=20, pady=(24, 12))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=(0, 20))
        self._btn(row, "No",  self._no,  C["border"],  C["scrollbar"]).pack(side="left", padx=6)
        self._btn(row, "Yes", self._yes, C["accent"],  C["primary"]).pack(side="left", padx=6)
        self.protocol("WM_DELETE_WINDOW", self._no)
        self.bind("<Return>", lambda _: self._yes())
        self.bind("<Escape>", lambda _: self._no())

    def _yes(self) -> None:
        self.result = True
        self._close()

    def _no(self) -> None:
        self.result = False
        self._close()

    def _close(self) -> None:
        if self.grab_status():
            self.grab_release()
        self.destroy()

class InputDialog(_BaseDialog):
    def __init__(self, parent: ctk.CTk, prompt: str, initial: str = ""):
        super().__init__(parent, w=400, h=170)
        self.value: str | None = None
        ctk.CTkLabel(self, text=prompt, font=ctk.CTkFont(size=12),
                     text_color=C["text"]).pack(padx=20, pady=(20, 6), anchor="w")
        self._entry = ctk.CTkEntry(self, font=ctk.CTkFont(size=12),
                                   fg_color=C["bg"], border_color=C["border"],
                                   corner_radius=6)
        self._entry.insert(0, initial)
        self._entry.pack(padx=20, fill="x")
        self._entry.focus_set()
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=(10, 16), anchor="e", padx=20)
        self._btn(row, "Cancel", self._cancel, C["border"],  C["scrollbar"]).pack(side="left", padx=4)
        self._btn(row, "OK",     self._ok,     C["accent"],  C["primary"]).pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self._cancel())

    def _ok(self) -> None:
        self.value = self._entry.get()
        self._close()

    def _cancel(self) -> None:
        self.value = None
        self._close()

    def _close(self) -> None:
        if self.grab_status():
            self.grab_release()
        self.destroy()

class UpdateDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, release_data: dict):
        super().__init__(parent)
        self.result = False
        self.release_data = release_data
        latest = release_data["tag_name"].lstrip("v").split("-")[0]
        self.title(f"Update {latest} Available")
        self.resizable(False, False)
        self.configure(fg_color=C["surface"])
        _center_on_parent(self, parent, 620, 480)
        _make_modal(self, parent)

        raw = release_data.get("body", "No changelog provided.")
        for ch in ["\r", "\u200b", "\u200d", "\ufeff", "\u00ad"]:
            raw = raw.replace(ch, "")
        raw = re.sub(r"\*\*|#+\s*", "", raw).strip()

        ctk.CTkLabel(self, text=f"Version {latest} is available",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["text_bright"]).pack(pady=(18, 6))

        ctk.CTkLabel(self, text="Changelog", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text_dim"]).pack(anchor="w", padx=20)

        box = ctk.CTkTextbox(self, fg_color=C["bg"], text_color=C["text"],
                             font=ctk.CTkFont(size=12), corner_radius=6)
        box.pack(fill="both", expand=True, padx=20, pady=(4, 12))
        box.insert("1.0", raw)
        box.configure(state="disabled")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=(0, 18))
        ctk.CTkButton(row, text="Later", width=100, fg_color=C["border"],
                      hover_color=C["scrollbar"], corner_radius=6,
                      command=self._no).pack(side="left", padx=8)
        ctk.CTkButton(row, text="Update Now", width=120, fg_color=C["primary"],
                      hover_color=C["accent"], corner_radius=6,
                      command=self._yes).pack(side="left", padx=8)
        self.protocol("WM_DELETE_WINDOW", self._no)

    def _yes(self) -> None:
        self.result = True
        self._close()

    def _no(self) -> None:
        self.result = False
        self._close()

    def _close(self) -> None:
        if self.grab_status():
            self.grab_release()
        self.destroy()

def apply_treeview_style() -> None:
    s = ttk.Style()
    s.theme_use("default")
    s.configure("Treeview",
                 background=C["surface2"], foreground=C["text"],
                 fieldbackground=C["surface2"], borderwidth=0,
                 font=("Segoe UI", 11) if os.name == "nt" else ("Helvetica", 11),
                 rowheight=30)
    s.configure("Treeview.Heading",
                 background=C["surface"], foreground=C["text_dim"],
                 relief="flat",
                 font=("Segoe UI", 11, "bold") if os.name == "nt" else ("Helvetica", 11, "bold"))
    s.map("Treeview.Heading",
          background=[("active", C["surface"])],
          foreground=[("active", C["text"])])
    s.map("Treeview",
          background=[("selected", C["primary"])],
          foreground=[("selected", C["text_bright"])])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Monolith.Vertical.TScrollbar",
                 troughcolor=C["trough"], background=C["scrollbar"],
                 bordercolor=C["trough"], arrowcolor=C["text_dim"],
                 relief="flat", arrowsize=14)
    s.map("Monolith.Vertical.TScrollbar",
          background=[("active", C["primary"])],
          troughcolor=[("active", C["trough"])])

def section_label(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text,
                        font=ctk.CTkFont(size=11, weight="bold"),
                        text_color=C["text_dim"])

class ModManagerTab(ctk.CTkFrame):
    def __init__(self, parent, app: "MonolithApp"):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._mod_index: dict[str, Mod] = {}
        self._search_timer: Timer | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(top, text="Base Folder", width=120,
                      fg_color=C["bg"], hover_color=C["border"],
                      font=ctk.CTkFont(size=12), corner_radius=6,
                      command=self.browse_folder).pack(side="left", padx=(0, 8))

        self._path_var = ctk.StringVar()
        ctk.CTkEntry(top, textvariable=self._path_var, state="readonly",
                     placeholder_text="No base folder selected…",
                     font=ctk.CTkFont(size=12), fg_color=C["surface"],
                     border_color=C["border"], corner_radius=6
                     ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(top, text="Open", width=60,
                      fg_color=C["bg"], hover_color=C["border"],
                      font=ctk.CTkFont(size=12), corner_radius=6,
                      command=self._open_explorer).pack(side="right")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))

        self._search_var = ctk.StringVar()
        ctk.CTkEntry(bar, textvariable=self._search_var,
                     font=ctk.CTkFont(size=12), fg_color=C["surface"],
                     border_color=C["border"], corner_radius=6
                     ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._search_var.trace_add("write", self._on_search_changed)

        ctk.CTkButton(bar, text="Export JSON", width=100,
                      fg_color=C["bg"], hover_color=C["border"],
                      font=ctk.CTkFont(size=12), corner_radius=6,
                      command=self._export).pack(side="right")

        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True, pady=(0, 8))
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=1)
        split.grid_rowconfigure(0, weight=1)

        list_panel = ctk.CTkFrame(split, fg_color=C["surface"],
                                   corner_radius=10)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        list_panel.grid_rowconfigure(0, weight=1)
        list_panel.grid_columnconfigure(0, weight=1)

        self._scrollbar = ttk.Scrollbar(list_panel,
                                         style="Monolith.Vertical.TScrollbar")
        self._scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)

        self._tree = ttk.Treeview(
            list_panel,
            columns=("status", "size", "name"),
            show="headings",
            selectmode="extended",
            yscrollcommand=self._scrollbar.set,
        )
        self._scrollbar.config(command=self._tree.yview)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)

        self._tree.heading("status", text="State",  anchor="w")
        self._tree.heading("size",   text="Size",   anchor="w")
        self._tree.heading("name",   text="Filename (Load Order)", anchor="w")
        self._tree.column("status", width=90,  stretch=tk.NO, anchor="w")
        self._tree.column("size",   width=90,  stretch=tk.NO, anchor="w")
        self._tree.column("name",   width=400, stretch=tk.YES, anchor="w")

        self._tree.tag_configure("enabled",  foreground=C["success"])
        self._tree.tag_configure("disabled", foreground=C["danger"])

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Button-3>",         self._show_context_menu)
        self._tree.bind("<Double-1>",         lambda _: self.toggle_selected())

        prev = ctk.CTkFrame(split, fg_color=C["surface"], corner_radius=10)
        prev.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(prev, text="Preview",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text_dim"]).pack(pady=(12, 4))

        self._preview_box = ctk.CTkFrame(prev, fg_color=C["bg"], corner_radius=8)
        self._preview_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._preview_box.pack_propagate(False)

        self._preview_label = ctk.CTkLabel(
            self._preview_box, text="No preview",
            text_color=C["text_dim"], font=ctk.CTkFont(size=11))
        self._preview_label.pack(fill="both", expand=True)

        self._info_name = ctk.CTkLabel(prev, text="",
                                        font=ctk.CTkFont(size=11, weight="bold"),
                                        text_color=C["text"], wraplength=200)
        self._info_name.pack(padx=10, anchor="w")
        self._info_meta = ctk.CTkLabel(prev, text="",
                                        font=ctk.CTkFont(size=10),
                                        text_color=C["text_dim"], wraplength=200)
        self._info_meta.pack(padx=10, pady=(2, 12), anchor="w")

        acts = ctk.CTkFrame(self, fg_color="transparent")
        acts.pack(fill="x")

        def _btn(text, cmd, fg, hover, width=110):
            return ctk.CTkButton(acts, text=text, width=width, command=cmd,
                                 fg_color=fg, hover_color=hover,
                                 font=ctk.CTkFont(size=12), corner_radius=6)

        _btn("Install",          self.install_mods,    C["primary"], "#2a68d3").pack(side="left", padx=(0, 6))
        _btn("Remove",           self.delete_selected, C["danger"],  "#ff3b3b").pack(side="left", padx=(0, 6))
        _btn("Enable",           lambda: self.toggle_selected("enable"),  C["success"], "#6a2c70").pack(side="left", padx=(0, 6))
        _btn("Disable",          lambda: self.toggle_selected("disable"), C["warning"], "#fa714b").pack(side="left", padx=(0, 6))
        _btn("⟳ Refresh", self.refresh, C["bg"], C["border"], 90).pack(side="right")

        self._status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(self, textvariable=self._status_var, anchor="w",
                     text_color=C["text_dim"], font=ctk.CTkFont(size=11)
                     ).pack(fill="x", pady=(6, 0))

        self._ctx = tk.Menu(self, tearoff=0,
                             bg=C["surface"], fg=C["text"],
                             activebackground=C["primary"],
                             activeforeground=C["text_bright"],
                             relief="flat", borderwidth=0)
        self._ctx.add_command(label="Toggle State",  command=self.toggle_selected)
        self._ctx.add_command(label="Rename File",   command=self._rename_dialog)
        self._ctx.add_separator()
        self._ctx.add_command(label="Delete File",   command=self.delete_selected)

    def set_folder(self, folder: Path) -> None:
        self._path_var.set(str(folder))
        self.refresh()

    def refresh(self) -> None:
        repo = self.app.repo
        if not repo:
            self._clear()
            self._status_var.set("No base folder set.")
            return
        mods = repo.list_mods(self._search_var.get())
        self._populate(mods)
        self._update_status_bar(mods)

    def _clear(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._mod_index.clear()

    def _populate(self, mods: list[Mod]) -> None:
        self._clear()
        for mod in mods:
            tag = "enabled" if mod.is_enabled else "disabled"
            iid = str(id(mod))
            self._mod_index[iid] = mod
            self._tree.insert("", "end", iid=iid,
                              values=(mod.status.value.upper(), mod.size_str, mod.name),
                              tags=(tag,))

    def _update_status_bar(self, mods: list[Mod]) -> None:
        enabled  = sum(1 for m in mods if m.is_enabled)
        disabled = len(mods) - enabled
        profile  = self.app.config_data.active_profile
        self._status_var.set(
            f"Profile: {profile}  ·  Enabled: {enabled}  ·  Disabled: {disabled}  ·  Total: {len(mods)}"
        )

    def _selected_mods(self) -> list[Mod]:
        return [self._mod_index[iid]
                for iid in self._tree.selection()
                if iid in self._mod_index]

    def _on_search_changed(self, *_) -> None:
        if self._search_timer:
            self._search_timer.cancel()
        self._search_timer = Timer(0.35, lambda: self.after(0, self.refresh))
        self._search_timer.start()

    def _on_select(self, _event) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        mod = mods[0]
        self._info_name.configure(text=mod.name)
        self._info_meta.configure(text=mod.size_str)
        threading.Thread(target=self._load_preview, args=(mod,), daemon=True).start()

    def _load_preview(self, mod: Mod) -> None:
        repo = self.app.repo
        if not repo:
            return
        img = repo.get_preview_image(mod)
        if img:
            w = max(self._preview_box.winfo_width() - 16, 120)
            ratio = w / img.width
            h = int(img.height * ratio)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
            self.after(0, lambda ci=cimg: (
                self._preview_label.configure(image=ci, text=""),
                setattr(self._preview_label, "_img_ref", ci),
            ))
        else:
            self.after(0, lambda: self._preview_label.configure(image=None, text="No preview"))

    def _show_context_menu(self, event) -> None:
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self._tree.selection():
            self._tree.selection_set(iid)
        self._ctx.post(event.x_root, event.y_root)

    def _open_explorer(self) -> None:
        repo = self.app.repo
        if not repo:
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", str(repo.folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(repo.folder)])
            else:
                subprocess.Popen(["xdg-open", str(repo.folder)])
        except Exception as e:
            self.app.show_error(f"Could not open folder: {e}")

    def browse_folder(self) -> None:
        default = Path("C:/") if os.name == "nt" else Path.home()
        path_str = filedialog.askdirectory(
            parent=self.app, title="Select Base Folder", initialdir=str(default))
        if not path_str:
            return
        self.app.set_mod_folder(Path(path_str))

    def install_mods(self) -> None:
        repo = self.app.repo
        if not repo:
            return self.app.show_error("Select a base folder first.")
        files = list(filedialog.askopenfilenames(
            parent=self.app, title="Select PK3 files",
            filetypes=[("PK3 files", "*.pk3")]))
        if not files:
            return
        confirmed: list[Path] = []
        for f in (Path(p) for p in files):
            if (repo.folder / f.name).exists():
                dlg = YesNoDialog(self.app, f"'{f.name}' already exists. Overwrite?")
                self.app.wait_window(dlg)
                if not dlg.result:
                    continue
            confirmed.append(f)
        if not confirmed:
            return
        self.app.set_busy(True)
        def _worker():
            ok = err = 0
            for i, f in enumerate(confirmed, 1):
                n, total = i, len(confirmed)
                self.after(0, lambda n=n, t=total:
                    self._status_var.set(f"Installing… {n}/{t}"))
                if repo.install(f):
                    ok += 1
                else:
                    err += 1
            self.after(0, lambda: self.app.finish_op(f"Installed {ok} mod(s). {err} error(s)."))
        threading.Thread(target=_worker, daemon=True).start()

    def delete_selected(self) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        dlg = YesNoDialog(self.app, f"Permanently delete {len(mods)} file(s)?")
        self.app.wait_window(dlg)
        if not dlg.result:
            return
        repo = self.app.repo
        self.app.set_busy(True)
        def _worker():
            count = sum(1 for m in mods if repo and repo.delete(m))
            self.after(0, lambda: self.app.finish_op(f"Deleted {count} file(s)."))
        threading.Thread(target=_worker, daemon=True).start()

    def toggle_selected(self, force: str | None = None) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        repo = self.app.repo
        if not repo:
            return
        failed = sum(1 for m in mods if not repo.toggle(m, force))
        self.refresh()
        if failed:
            self.app.show_error(f"{failed} mod(s) could not be toggled.")

    def _rename_dialog(self) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        mod = mods[0]
        dlg = InputDialog(self.app, "New filename:", initial=mod.name)
        self.app.wait_window(dlg)
        if not dlg.value:
            return
        new_name = dlg.value if dlg.value.lower().endswith(".pk3") else dlg.value + ".pk3"
        if not re.match(r'^[\w\-\.]+\.pk3$', new_name):
            return self.app.show_error("Invalid filename.")
        repo = self.app.repo
        if repo and repo.rename(mod, new_name):
            self.refresh()
        else:
            self.app.show_error("Rename failed.")

    def _export(self) -> None:
        repo = self.app.repo
        if not repo:
            return
        dest = filedialog.asksaveasfilename(
            parent=self.app, title="Export Mod List",
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not dest:
            return
        self.app.set_busy(True)
        self._status_var.set("Exporting…")
        def _worker():
            try:
                count = repo.export_manifest(Path(dest))
                self.after(0, lambda: self.app.finish_op(f"Exported {count} mods to {dest}"))
            except Exception as e:
                self.after(0, lambda: self.app.show_error(f"Export failed: {e}"))
                self.after(0, lambda: self.app.set_busy(False))
        threading.Thread(target=_worker, daemon=True).start()

class DownloadTab(ctk.CTkFrame):
    _API_URL = "https://jk2t.ddns.net/modmanager/api.php"

    def __init__(self, parent, app: "MonolithApp"):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._cache: list[dict] = []
        self._search_timer: Timer | None = None
        self._active_downloads: set[str] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))

        self._search_var = ctk.StringVar()
        ctk.CTkEntry(top, textvariable=self._search_var,
                     font=ctk.CTkFont(size=12), fg_color=C["surface"],
                     border_color=C["border"], corner_radius=6
                     ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._search_var.trace_add("write", self._on_search_changed)

        ctk.CTkButton(top, text="⟳ Refresh", width=90,
                      fg_color=C["bg"], hover_color=C["border"],
                      font=ctk.CTkFont(size=12), corner_radius=6,
                      command=self.fetch).pack(side="right")

        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True, pady=(0, 8))
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=1)
        split.grid_rowconfigure(0, weight=1)

        list_panel = ctk.CTkFrame(split, fg_color=C["surface"], corner_radius=10)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        list_panel.grid_rowconfigure(0, weight=1)
        list_panel.grid_columnconfigure(0, weight=1)

        sb = ttk.Scrollbar(list_panel, style="Monolith.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)

        self._tree = ttk.Treeview(
            list_panel,
            columns=("name", "author", "category", "size", "date"),
            show="headings",
            yscrollcommand=sb.set,
        )
        sb.config(command=self._tree.yview)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)

        for col, txt, w in [
            ("name",     "Name",     200),
            ("author",   "Author",   130),
            ("category", "Category", 110),
            ("size",     "Size",      80),
            ("date",     "Date",      90),
        ]:
            self._tree.heading(col, text=txt, anchor="w")
            self._tree.column(col, width=w, anchor="w")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        detail = ctk.CTkFrame(split, fg_color=C["surface"], corner_radius=10)
        detail.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(detail, text="Mod Details",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text_dim"]).pack(pady=(12, 4))

        self._prev_box = ctk.CTkFrame(detail, fg_color=C["bg"], corner_radius=8)
        self._prev_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._prev_box.pack_propagate(False)

        self._prev_lbl = ctk.CTkLabel(self._prev_box, text="No preview",
                                      text_color=C["text_dim"],
                                      font=ctk.CTkFont(size=11))
        self._prev_lbl.pack(fill="both", expand=True)

        self._detail_name = ctk.CTkLabel(detail, text="",
                                          font=ctk.CTkFont(size=12, weight="bold"),
                                          text_color=C["text"], wraplength=180)
        self._detail_name.pack(padx=10, pady=(8, 2), anchor="w")

        self._detail_meta = ctk.CTkLabel(detail, text="",
                                          font=ctk.CTkFont(size=10),
                                          text_color=C["text_dim"], wraplength=180,
                                          justify="left")
        self._detail_meta.pack(padx=10, anchor="w")

        prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        prog_frame.pack(fill="x", pady=(0, 6))

        self._progress = ctk.CTkProgressBar(prog_frame, height=6, corner_radius=4,
                                             progress_color=C["accent"],
                                             fg_color=C["surface"])
        self._progress.pack(fill="x", side="left", expand=True)
        self._progress.set(0)

        self._progress_lbl = ctk.CTkLabel(prog_frame, text="", width=50,
                                           text_color=C["text_dim"],
                                           font=ctk.CTkFont(size=11))
        self._progress_lbl.pack(side="left", padx=(8, 0))

        acts = ctk.CTkFrame(self, fg_color="transparent")
        acts.pack(fill="x")

        self._count_lbl = ctk.CTkLabel(acts, text="",
                                        text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=11))
        self._count_lbl.pack(side="left")

        ctk.CTkButton(acts, text="Download Selected", width=150,
                      fg_color=C["primary"], hover_color="#2a68d3",
                      font=ctk.CTkFont(size=12), corner_radius=6,
                      command=self.download_selected).pack(side="right")

    def fetch(self) -> None:
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        try:
            headers = {"User-Agent": f"Monolith-App-Client/{APP_VERSION}"}
            resp = requests.get(self._API_URL, headers=headers, timeout=8)
            resp.raise_for_status() 
            self._cache = resp.json()

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            
            if status == 503:
                try:
                    msg = e.response.json().get("message", "Server maintenance.")
                except:
                    msg = "Server is temporarily unavailable for maintenance."
                self.after(0, lambda m=msg: self.app.show_error(m))

            elif status == 426:
                try:
                    msg = e.response.json().get("message", "Update available.")
                except:
                    msg = "Your app version is outdated. Please update."
                self.after(0, lambda m=msg: self.app.show_error(m))

            else:
                self.after(0, lambda: self.app.show_error(f"Server Error ({status})"))
            
            self._cache = []

        except Exception as e:
            error_msg = str(e)
            self.after(0, lambda msg=error_msg: self.app.show_error(f"Fetch failed: {msg}"))
            self._cache = []
        
        self.after(0, self._apply_filter)

    def _apply_filter(self) -> None:
        term = self._search_var.get().lower()
        
        def _parse_date(m: dict):
            raw = m.get("date", "")
            for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
                try:
                    return datetime.datetime.strptime(raw, fmt)
                except ValueError:
                    continue
            return datetime.datetime.min

        if term:
            def score(m: dict) -> int:
                s = 0
                if term in m.get("name",     "").lower(): s += 4
                if term in m.get("category", "").lower(): s += 3
                if term in m.get("author",   "").lower(): s += 2
                if term in m.get("uploader", "").lower(): s += 1
                return s
            mods = sorted(
                [m for m in self._cache if score(m) > 0],
                key=lambda m: (-score(m), m.get("name", "").lower())
            )
        else:
            mods = sorted(self._cache, key=_parse_date, reverse=True)
        self._populate(mods)

    def _populate(self, mods: list[dict]) -> None:
        self._tree.delete(*self._tree.get_children())
        for mod in mods:
            self._tree.insert("", "end", iid=mod["download_url"], values=(
                mod.get("name",     "?"),
                mod.get("author",   "—"),
                mod.get("category", "—"),
                mod.get("size",     "—"),
                mod.get("date",     "—"),
            ))
        self._count_lbl.configure(text=f"{len(mods)} mod(s)")

    def _on_search_changed(self, *_) -> None:
        if self._search_timer:
            self._search_timer.cancel()
        self._search_timer = Timer(0.35, lambda: self.after(0, self._apply_filter))
        self._search_timer.start()

    def _on_select(self, _event) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        url = sel[0]
        mod = next((m for m in self._cache if m["download_url"] == url), None)
        if not mod:
            return
        self._detail_name.configure(text=mod.get("name", ""))
        meta_lines = [
            f"Author:   {mod.get('author', '—')}",
            f"Uploader: {mod.get('uploader', '—')}",
            f"Category: {mod.get('category', '—')}",
            f"Size:     {mod.get('size', '—')}",
            f"Date:     {mod.get('date', '—')}",
        ]
        self._detail_meta.configure(text="\n".join(meta_lines))
        preview_url = mod.get("preview_image")
        if preview_url:
            threading.Thread(target=self._load_preview,
                             args=(preview_url,), daemon=True).start()
        else:
            self._prev_lbl.configure(image=None, text="No preview")

    def _load_preview(self, url: str) -> None:
        try:
            resp = requests.get(url, timeout=6)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            w = max(self._prev_box.winfo_width() - 10, 120)
            h = int(img.height * (w / img.width))
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
            self.after(0, lambda ci=cimg: (
                self._prev_lbl.configure(image=ci, text=""),
                setattr(self._prev_lbl, "_img_ref", ci),
            ))
        except Exception:
            self.after(0, lambda: self._prev_lbl.configure(image=None, text="Preview error"))

    def download_selected(self) -> None:
        if not self.app.repo:
            return self.app.show_error("Select a base folder first.")
        sel = self._tree.selection()
        if not sel:
            return self.app.show_error("Select at least one mod to download.")
        for url in sel:
            if url not in self._active_downloads:
                self._active_downloads.add(url)
                mod_name = self._tree.item(url, "values")[0]
                threading.Thread(target=self._download_worker,
                                 args=(url, mod_name), daemon=True).start()

    def _download_worker(self, url: str, name: str) -> None:
        repo = self.app.repo
        if not repo:
            return
        filename = url.split("/")[-1]
        dest = repo.folder / filename
        try:
            resp = requests.get(url, stream=True, timeout=15)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            done  = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        p = done / total
                        pct = int(p * 100)
                        self.after(0, lambda p=p, pct=pct: (
                            self._progress.set(p),
                            self._progress_lbl.configure(text=f"{pct}%"),
                        ))
            self.after(0, lambda: self.app.finish_op(f"Downloaded {name}."))
        except Exception as e:
            if dest.exists():
                dest.unlink(missing_ok=True)
            self.after(0, lambda: self.app.show_error(f"Download failed: {e}"))
        finally:
            self._active_downloads.discard(url)
            self.after(0, lambda: (
                self._progress.set(0),
                self._progress_lbl.configure(text=""),
            ))

class RconTab(ctk.CTkFrame):
    def __init__(self, parent, app: "MonolithApp"):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._history: list[str] = []
        self._history_idx = -1
        self._rcon_cfg = configparser.ConfigParser()
        if not RCON_CONFIG_FILE.exists():
            RCON_CONFIG_FILE.write_text("")
        self._rcon_cfg.read(RCON_CONFIG_FILE)
        self._build_ui()
        self._load_servers()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        conn = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=10)
        conn.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        conn.grid_columnconfigure((1, 3, 5), weight=1)

        def _lbl(text, col):
            ctk.CTkLabel(conn, text=text, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["text_dim"]).grid(
                             row=0, column=col, padx=(12, 4), pady=10, sticky="w")

        def _entry(col, show=""):
            e = ctk.CTkEntry(conn, font=ctk.CTkFont(size=12),
                             fg_color=C["bg"], border_color=C["border"],
                             corner_radius=6, show=show)
            e.grid(row=0, column=col, padx=(0, 8), pady=8, sticky="ew")
            return e

        _lbl("Name",     0); self._name_entry = _entry(1)
        _lbl("IP",       2); self._ip_entry   = _entry(3)
        _lbl("Port",     4); self._port_entry = _entry(5)
        _lbl("Password", 6); self._pass_entry = _entry(7, show="•")

        btn_row = ctk.CTkFrame(conn, fg_color="transparent")
        btn_row.grid(row=1, column=0, columnspan=8, sticky="ew", padx=12, pady=(0, 10))

        self._server_combo = ctk.CTkComboBox(
            btn_row, values=[], state="readonly", width=200,
            font=ctk.CTkFont(size=12), fg_color=C["bg"],
            border_color=C["border"], corner_radius=6,
            command=self._load_server_creds)
        self._server_combo.pack(side="left", padx=(0, 8))

        for txt, cmd, fg, hover in [
            ("Save",   self._save_server,   C["primary"], "#2a68d3"),
            ("Delete", self._delete_server, C["danger"],  "#ff3b3b"),
            ("Clear",  self._clear_output,  C["warning"], "#fa714b"),
        ]:
            ctk.CTkButton(btn_row, text=txt, width=72, command=cmd,
                          fg_color=fg, hover_color=hover,
                          font=ctk.CTkFont(size=11), corner_radius=6
                          ).pack(side="left", padx=(0, 6))

        self._output = CTkMonoTextbox(self, fg_color=C["bg"], corner_radius=8,
                                      font=ctk.CTkFont(size=15, family=FONT_MONO))
        self._output.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        tw = self._output._textbox
        for code, hexcol in JK2_COLORS.items():
            tw.tag_configure(f"jk2_{code}", foreground=hexcol)
        tw.tag_configure("jk2_cmd", foreground=RCON_CMD_COLOR)
        tw.tag_configure("jk2_err", foreground=C["danger"])

        inp = ctk.CTkFrame(self, fg_color="transparent")
        inp.grid(row=2, column=0, sticky="ew")
        inp.grid_columnconfigure(0, weight=1)

        self._cmd_entry = ctk.CTkEntry(
            inp, placeholder_text="Enter RCON command…",
            font=ctk.CTkFont(size=15, family=FONT_MONO),
            fg_color=C["surface"], border_color=C["border"], corner_radius=6)
        self._cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._cmd_entry.bind("<Return>",   self._send)
        self._cmd_entry.bind("<Up>",       self._history_up)
        self._cmd_entry.bind("<Down>",     self._history_down)

        ctk.CTkButton(inp, text="Send", width=80,
                      fg_color=C["primary"], hover_color="#2a68d3",
                      font=ctk.CTkFont(size=12), corner_radius=6,
                      command=self._send).grid(row=0, column=1)

    def _load_servers(self) -> None:
        self._rcon_cfg.read(RCON_CONFIG_FILE)
        self._server_combo.configure(values=self._rcon_cfg.sections())

    def _load_server_creds(self, name: str) -> None:
        if name not in self._rcon_cfg:
            return
        sec = self._rcon_cfg[name]
        for entry, key in [
            (self._name_entry, None),
            (self._ip_entry,   "ip"),
            (self._port_entry, "port"),
            (self._pass_entry, "password"),
        ]:
            entry.delete(0, tk.END)
            if key:
                entry.insert(0, sec.get(key, ""))
            else:
                entry.insert(0, name)

    def _save_server(self) -> None:
        name = self._name_entry.get().strip()
        ip   = self._ip_entry.get().strip()
        port = self._port_entry.get().strip()
        pw   = self._pass_entry.get()
        if not (name and ip and port):
            return self.app.show_error("Name, IP, and port are required.")
        if not re.match(r'^[\w\-\.]+$', name):
            return self.app.show_error("Server name contains invalid characters.")
        self._rcon_cfg[name] = {"ip": ip, "port": port, "password": pw}
        with open(RCON_CONFIG_FILE, "w") as f:
            self._rcon_cfg.write(f)
        self._load_servers()
        self.app.show_info(f"Server '{name}' saved.")

    def _delete_server(self) -> None:
        name = self._server_combo.get()
        if not name:
            return self.app.show_error("No server selected.")
        dlg = YesNoDialog(self.app, f"Delete server '{name}'?")
        self.app.wait_window(dlg)
        if not dlg.result:
            return
        self._rcon_cfg.remove_section(name)
        with open(RCON_CONFIG_FILE, "w") as f:
            self._rcon_cfg.write(f)
        self._load_servers()

    def _clear_output(self) -> None:
        tw = self._output._textbox
        tw.configure(state="normal")
        tw.delete("1.0", "end")
        tw.configure(state="disabled")

    def _send(self, _event=None) -> None:
        ip   = self._ip_entry.get().strip()
        port = self._port_entry.get().strip()
        pw   = self._pass_entry.get()
        cmd  = self._cmd_entry.get().strip()
        if not (ip and port and cmd):
            return self.app.show_error("IP, port, and command are required.")
        if cmd:
            self._history.append(cmd)
            self._history_idx = -1
        self._cmd_entry.delete(0, tk.END)
        threading.Thread(target=self._worker,
                         args=(ip, port, pw, cmd), daemon=True).start()

    def _worker(self, ip: str, port: str, pw: str, cmd: str) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        try:
            sock.sendto(
                b"\xff\xff\xff\xffrcon %s %s\n" % (pw.encode(), cmd.encode()),
                (ip, int(port)),
            )
            data, _ = sock.recvfrom(4096)
            segs = parse_rcon_colored(data.decode("utf-8", "ignore"))
            self.after(0, lambda s=segs, c=cmd: self._insert_colored(s, cmd_prefix=f">>> {c}"))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda m=msg: self._insert_error(m))
        finally:
            sock.close()

    def _insert_colored(self, segs: list[tuple[str, str]],
                         cmd_prefix: str | None = None) -> None:
        tw = self._output._textbox
        tw.configure(state="normal")
        if cmd_prefix:
            tw.insert("end", cmd_prefix + "\n", "jk2_cmd")
        for text, hexcol in segs:
            tag = next((f"jk2_{k}" for k, v in JK2_COLORS.items() if v == hexcol), "jk2_8")
            tw.insert("end", text, tag)
        tw.insert("end", "\n\n")
        tw.configure(state="disabled")
        tw.see("end")

    def _insert_error(self, msg: str) -> None:
        tw = self._output._textbox
        tw.configure(state="normal")
        tw.insert("end", f"Error: {msg}\n\n", "jk2_err")
        tw.configure(state="disabled")
        tw.see("end")

    def _history_up(self, _event=None) -> None:
        if not self._history:
            return
        self._history_idx = max(self._history_idx - 1, -len(self._history))
        self._cmd_entry.delete(0, tk.END)
        self._cmd_entry.insert(0, self._history[self._history_idx])

    def _history_down(self, _event=None) -> None:
        if self._history_idx < -1:
            self._history_idx += 1
        self._cmd_entry.delete(0, tk.END)
        if self._history_idx < -1:
            self._cmd_entry.insert(0, self._history[self._history_idx])

class CTkMonoTextbox(ctk.CTkTextbox):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._textbox.configure(state="disabled")

class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, app: "MonolithApp"):
        super().__init__(parent, width=220, corner_radius=0,
                         fg_color=C["surface"])
        self.app = app
        self.grid_propagate(False)
        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(12, weight=1)

        ctk.CTkLabel(self, text="MONOLITH",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["accent"]).grid(
                         row=0, column=0, padx=20, pady=(24, 2))
        ctk.CTkLabel(self, text="MOD MANAGER",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["text_dim"]).grid(
                         row=1, column=0, padx=20, pady=(0, 20))

        ctk.CTkFrame(self, height=1, fg_color=C["border"]).grid(
            row=2, column=0, sticky="ew", padx=16, pady=(0, 16))

        section_label(self, "LAUNCH PARAMETERS").grid(
            row=3, column=0, padx=20, sticky="w")

        self.devmode_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Developer Mode",
                        variable=self.devmode_var,
                        font=ctk.CTkFont(size=12),
                        checkbox_height=16, checkbox_width=16,
                        fg_color=C["primary"], hover_color=C["accent"]
                        ).grid(row=4, column=0, padx=20, pady=(8, 0), sticky="w")

        self.logfile_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Logfile",
                        variable=self.logfile_var,
                        font=ctk.CTkFont(size=12),
                        checkbox_height=16, checkbox_width=16,
                        fg_color=C["primary"], hover_color=C["accent"]
                        ).grid(row=5, column=0, padx=20, pady=(6, 0), sticky="w")

        self.params_var = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.params_var,
                     font=ctk.CTkFont(size=11),
                     fg_color=C["bg"], border_color=C["border"],
                     height=28, corner_radius=6
                     ).grid(row=6, column=0, padx=20, pady=(6, 12), sticky="ew")

        self.btn_launch = ctk.CTkButton(
            self, text="▶  LAUNCH GAME", height=46,
            fg_color=C["success"], hover_color="#6a2c70",
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8, command=self.app.launch_game)
        self.btn_launch.grid(row=7, column=0, padx=20, pady=(0, 20), sticky="ew")

        ctk.CTkFrame(self, height=1, fg_color=C["border"]).grid(
            row=8, column=0, sticky="ew", padx=16, pady=(0, 14))

        section_label(self, "PROFILES").grid(row=9, column=0, padx=20, sticky="w")

        self.profile_menu = ctk.CTkOptionMenu(
            self, dynamic_resizing=False,
            command=self.app.change_profile,
            font=ctk.CTkFont(size=12),
            fg_color=C["bg"], button_color=C["border"],
            button_hover_color=C["primary"],
            height=30, corner_radius=6)
        self.profile_menu.grid(row=10, column=0, padx=20, pady=(6, 8), sticky="ew")

        pbtn = ctk.CTkFrame(self, fg_color="transparent")
        pbtn.grid(row=11, column=0, padx=20, pady=(0, 8))

        for text, cmd, fg in [
            ("+",  self.app.create_profile, C["success"]),
            ("✎",  self.app.rename_profile, C["primary"]),
            ("🗑", self.app.delete_profile, C["danger"]),
        ]:
            ctk.CTkButton(pbtn, text=text, width=50, height=28,
                          fg_color=fg, hover_color=C["border"],
                          font=ctk.CTkFont(size=12), corner_radius=6,
                          command=cmd).pack(side="left", padx=3)

        self.btn_updates = ctk.CTkButton(
            self, text="Check for Updates",
            fg_color=C["bg"], hover_color=C["border"],
            font=ctk.CTkFont(size=11), height=28, corner_radius=6,
            command=self.app.check_updates)
        self.btn_updates.grid(row=13, column=0, padx=20, pady=(0, 20), sticky="ew")

        self.grid_columnconfigure(0, weight=1)

    def load_profile(self, profile: Profile) -> None:
        self.devmode_var.set(profile.devmode)
        self.logfile_var.set(profile.logfile)
        self.params_var.set(profile.custom_params)

    def get_launch_params(self) -> list[str]:
        params = []
        if self.devmode_var.get():
            params.append("+developer 1")
        if self.logfile_var.get():
            params.append("+logfile 2")
        custom = self.params_var.get().strip()
        if custom:
            params.extend(custom.split())
        return params

    def save_to_profile(self, profile: Profile) -> None:
        profile.devmode       = self.devmode_var.get()
        profile.logfile       = self.logfile_var.get()
        profile.custom_params = self.params_var.get()

    def set_profiles(self, names: list[str], active: str) -> None:
        self.profile_menu.configure(values=names)
        if active in names:
            self.profile_menu.set(active)
        elif names:
            self.profile_menu.set(names[0])

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_launch.configure(state=state)

class MonolithApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config_data = AppConfig.load()
        self.repo: ModRepository | None = None
        self.game_process: subprocess.Popen | None = None

        self.title("MONOLITH MOD MANAGER")
        self.minsize(1100, 720)
        self.configure(fg_color=C["bg"])

        if self.config_data.geometry:
            try:
                self.geometry(self.config_data.geometry)
            except Exception:
                self.geometry("1100x720")
        else:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"1100x720+{(sw-1100)//2}+{(sh-720)//2}")

        apply_treeview_style()
        self._build_ui()
        self._restore_active_profile()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(self, app=self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(
            main,
            fg_color=C["surface"],
            segmented_button_fg_color=C["bg"],
            segmented_button_selected_color=C["primary"],
            segmented_button_selected_hover_color=C["accent"],
            segmented_button_unselected_color=C["bg"],
            segmented_button_unselected_hover_color=C["surface"],
            corner_radius=10,
        )
        self.tabs.pack(fill="both", expand=True)

        self.mod_tab      = self.tabs.add("  Mod Manager  ")
        self.download_tab = self.tabs.add("  Download Mods  ")
        self.rcon_tab_frame = self.tabs.add("  RCON Console  ")

        self.mod_panel      = ModManagerTab(self.mod_tab,      app=self)
        self.download_panel = DownloadTab(self.download_tab,   app=self)
        self.rcon_panel     = RconTab(self.rcon_tab_frame,     app=self)

        self.mod_panel.pack(fill="both", expand=True, padx=14, pady=14)
        self.download_panel.pack(fill="both", expand=True, padx=14, pady=14)
        self.rcon_panel.pack(fill="both", expand=True, padx=14, pady=14)

        self.after(200, self.download_panel.fetch)

    def _restore_active_profile(self) -> None:
        cfg = self.config_data
        if cfg.active_profile not in cfg.profiles:
            cfg.active_profile = next(iter(cfg.profiles), "Default")
        self._refresh_profile_menu()
        self._apply_profile(cfg.profiles[cfg.active_profile])

    def _refresh_profile_menu(self) -> None:
        names = list(self.config_data.profiles.keys())
        self.sidebar.set_profiles(names, self.config_data.active_profile)

    def _apply_profile(self, profile: Profile) -> None:
        self.sidebar.load_profile(profile)
        if profile.mod_folder and Path(profile.mod_folder).exists():
            self.set_mod_folder(Path(profile.mod_folder), save=False)
        else:
            self.repo = None
            self.mod_panel._path_var.set(
                "Folder missing, click 'Base Folder' to set one.")
            self.mod_panel.refresh()

    def change_profile(self, name: str) -> None:
        old = self.config_data.profiles.get(self.config_data.active_profile)
        if old:
            self.sidebar.save_to_profile(old)
            if self.repo:
                old.mod_folder = str(self.repo.folder)
        self.config_data.active_profile = name
        self._apply_profile(self.config_data.profiles[name])
        self.config_data.save()

    def create_profile(self) -> None:
        dlg = InputDialog(self, "New profile name:")
        self.wait_window(dlg)
        name = (dlg.value or "").strip()
        if not name:
            return
        if name in self.config_data.profiles:
            return self.show_error(f"Profile '{name}' already exists.")
        self.config_data.profiles[name] = Profile(name=name)
        self.config_data.active_profile = name
        self._refresh_profile_menu()
        self._apply_profile(self.config_data.profiles[name])
        self.config_data.save()
        self.show_info(f"Profile '{name}' created. Select a base folder to get started.")

    def rename_profile(self) -> None:
        current = self.config_data.active_profile
        dlg = InputDialog(self, "Rename profile:", initial=current)
        self.wait_window(dlg)
        new_name = (dlg.value or "").strip()
        if not new_name or new_name == current:
            return
        if new_name in self.config_data.profiles:
            return self.show_error(f"A profile named '{new_name}' already exists.")
        profile = self.config_data.profiles.pop(current)
        profile.name = new_name
        self.config_data.profiles[new_name] = profile
        self.config_data.active_profile = new_name
        self._refresh_profile_menu()
        self.config_data.save()

    def delete_profile(self) -> None:
        current = self.config_data.active_profile
        msg = (f"Delete profile '{current}'?\n\nThis will create a new Default profile."
               if len(self.config_data.profiles) == 1
               else f"Permanently delete profile '{current}'?")
        dlg = YesNoDialog(self, msg)
        self.wait_window(dlg)
        if not dlg.result:
            return
        del self.config_data.profiles[current]
        if not self.config_data.profiles:
            self.config_data.profiles["Default"] = Profile(name="Default")
        self.config_data.active_profile = next(iter(self.config_data.profiles))
        self._refresh_profile_menu()
        self._apply_profile(self.config_data.profiles[self.config_data.active_profile])
        self.config_data.save()

    def set_mod_folder(self, folder: Path, save: bool = True) -> None:
        self.repo = ModRepository(folder)
        self.mod_panel.set_folder(folder)
        if save:
            profile = self.config_data.profiles.get(self.config_data.active_profile)
            if profile:
                profile.mod_folder = str(folder)
            self.config_data.save()

    def launch_game(self) -> None:
        profile = self.config_data.profiles.get(self.config_data.active_profile)
        if not profile:
            return
        exe = Path(profile.game_exe) if profile.game_exe else None
        if not exe or not exe.exists():
            self.show_info("Locate your game executable (e.g. jk2mvmp.exe or nwhmp.exe).")
            path_str = filedialog.askopenfilename(parent=self, title="Select Game Executable")
            if not path_str:
                return
            exe = Path(path_str)
            profile.game_exe = str(exe)
            self.config_data.save()
        params = self.sidebar.get_launch_params()
        self.set_busy(True)
        threading.Thread(target=self._launch_worker, args=(exe, params), daemon=True).start()

    def _launch_worker(self, exe: Path, params: list[str]) -> None:
        try:
            if os.name != "nt":
                exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
            self.game_process = subprocess.Popen([str(exe)] + params, cwd=str(exe.parent))
            self.after(0, lambda: self.finish_op("Game launched."))
        except Exception as e:
            self.after(0, lambda: self.show_error(f"Launch failed: {e}"))
            self.after(0, lambda: self.set_busy(False))

    def check_updates(self) -> None:
        self.sidebar.btn_updates.configure(state="disabled", text="Checking…")
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self) -> None:
        try:
            vtxt = requests.get(
                "https://raw.githubusercontent.com/fl4te/monolith/refs/heads/main/version.txt",
                timeout=6).text.strip()
            if _version_tuple(vtxt) <= _version_tuple(APP_VERSION):
                self.after(0, lambda: (
                    self.sidebar.btn_updates.configure(state="normal", text="Check for Updates"),
                    self.show_info(f"You are on the latest version ({APP_VERSION})."),
                ))
                return
            resp = requests.get(
                "https://api.github.com/repos/fl4te/monolith/releases/latest", timeout=6)
            resp.raise_for_status()
            release = resp.json()
            self.after(0, lambda r=release: (
                self.sidebar.btn_updates.configure(state="normal",
                                                   text="Update Available!",
                                                   fg_color=C["success"]),
                self._show_update_dialog(r),
            ))
        except Exception as e:
            logging.error(f"Update check failed: {e}")
            self.after(0, lambda: (
                self.sidebar.btn_updates.configure(state="normal", text="Check for Updates"),
                self.show_error(f"Update check failed: {e}"),
            ))

    def _show_update_dialog(self, release: dict) -> None:
        dlg = UpdateDialog(self, release)
        self.wait_window(dlg)
        if dlg.result:
            threading.Thread(target=self._update_worker, args=(release,), daemon=True).start()

    def _update_worker(self, release: dict) -> None:
        asset_name = (
            "Monolith-windows.zip"  if os.name == "nt"
            else "Monolith-linux.tar.gz" if sys.platform.startswith("linux")
            else "Monolith-macos.dmg"
        )
        url = next((a["browser_download_url"] for a in release["assets"]
                    if a["name"] == asset_name), None)
        expected_hash = next((a.get("sha256") for a in release["assets"]
                               if a["name"] == asset_name), None)
        if not url:
            self.after(0, lambda: self.show_error("Release asset not found."))
            return

        temp = CONFIG_DIR / f"update_temp_{asset_name}"
        try:
            for attempt in range(3):
                try:
                    resp = requests.get(url, stream=True, timeout=15)
                    resp.raise_for_status()
                    with open(temp, "wb") as fh:
                        for chunk in resp.iter_content(65536):
                            fh.write(chunk)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    time.sleep(2)
            if expected_hash and _sha256(temp) != expected_hash:
                temp.unlink(missing_ok=True)
                self.after(0, lambda: self.show_error("Hash mismatch — update aborted."))
                return
        except Exception as e:
            self.after(0, lambda: self.show_error(f"Download failed: {e}"))
            return

        if asset_name.endswith(".dmg"):
            self.after(0, lambda: self.show_info(f"DMG downloaded to:\n{temp}\n\nDrag it to Applications."))
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(temp)])
            return

        lock = CONFIG_DIR / "update.lock"
        lock.touch()
        app_path = self._get_app_path()
        backup   = app_path.with_suffix(".old")
        try:
            extract = CONFIG_DIR / "update_extract"
            if os.name != "nt":
                backup.unlink(missing_ok=True)
                app_path.rename(backup)
            shutil.rmtree(extract, ignore_errors=True)
            extract.mkdir()

            if asset_name.endswith(".tar.gz"):
                with tarfile.open(temp, "r:gz") as tar:
                    _safe_extract_tar(tar, extract)
            else:
                with zipfile.ZipFile(temp, "r") as zf:
                    _safe_extract_zip(zf, extract)

            files = list(extract.rglob("*"))
            candidates = [f for f in files if f.is_file() and not f.name.startswith(".")]
            new_bin = (
                next((f for f in candidates if f.name == app_path.name), None)
                or next((f for f in candidates if os.access(f, os.X_OK)), None)
                or next(iter(candidates), None)
            )
            if not new_bin:
                raise FileNotFoundError("Executable not found in update package.")

            if os.name == "nt":
                bat = CONFIG_DIR / "update.bat"
                bat.write_text(
                    f"@echo off\n"
                    f":wait\n"
                    f"tasklist /FI \"PID eq {os.getpid()}\" 2>NUL | find /I \"{os.getpid()}\" >NUL\n"
                    f"if not errorlevel 1 (timeout /t 1 /nobreak >NUL & goto wait)\n"
                    f"move /Y \"{new_bin}\" \"{app_path}\"\n"
                    f"start \"\" \"{app_path}\"\n"
                    f"del \"%~f0\"\n",
                    encoding="utf-8",
                )
                lock.unlink(missing_ok=True)
                subprocess.Popen(
                    ["cmd", "/c", str(bat)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.after(0, lambda: self.show_info("Update ready. The app will restart automatically."))
                self.after(1500, self.destroy)
            else:
                shutil.move(str(new_bin), str(app_path))
                app_path.chmod(0o755)
                lock.unlink(missing_ok=True)
                self.after(0, lambda: self.show_info("Update installed. Restarting…"))
                self.after(1500, self._restart)
        except PermissionError:
            self.after(0, lambda: self.show_error(
                "Permission denied. Try running as administrator."))
            if os.name != "nt" and backup.exists():
                backup.rename(app_path)
            lock.unlink(missing_ok=True)
        except Exception as e:
            logging.error(f"Update apply failed: {e}")
            if os.name != "nt" and backup.exists():
                backup.rename(app_path)
            lock.unlink(missing_ok=True)
            self.after(0, lambda: self.show_error(f"Update failed: {e}"))

    @staticmethod
    def _get_app_path() -> Path:
        if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
            return Path(sys.executable).resolve()
        return Path(sys.argv[0]).resolve()

    def _restart(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable] + sys.argv[1:])
                sys.exit()
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            logging.error(f"Restart failed: {e}")
            self.show_error("Please restart the application manually.")

    def check_incomplete_update(self) -> None:
        lock = CONFIG_DIR / "update.lock"
        if lock.exists():
            backup = self._get_app_path().with_suffix(".old")
            if backup.exists():
                backup.rename(self._get_app_path())
            lock.unlink(missing_ok=True)
            self.show_error("Previous update was incomplete. Restored backup.")

    def set_busy(self, busy: bool) -> None:
        self.sidebar.set_busy(busy)

    def finish_op(self, msg: str) -> None:
        self.set_busy(False)
        self.mod_panel._status_var.set(msg)
        self.mod_panel.refresh()

    def show_info(self, message: str) -> None:
        dlg = InfoDialog(self, message)
        self.wait_window(dlg)

    def show_error(self, message: str) -> None:
        dlg = ErrorDialog(self, message)
        self.wait_window(dlg)

    def _on_close(self) -> None:
        profile = self.config_data.profiles.get(self.config_data.active_profile)
        if profile:
            self.sidebar.save_to_profile(profile)
            if self.repo:
                profile.mod_folder = str(self.repo.folder)
        self.config_data.geometry = self.geometry()
        self.config_data.save()

        if self.game_process and self.game_process.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.call(["taskkill", "/F", "/T", "/PID", str(self.game_process.pid)])
                else:
                    self.game_process.terminate()
                    try:
                        self.game_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.game_process.kill()
            except Exception as e:
                logging.error(f"Could not kill game process: {e}")
        self.destroy()

def _safe_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    dest_r = dest.resolve()
    for m in tar.getmembers():
        if not (dest_r / m.name).resolve().is_relative_to(dest_r):
            raise ValueError(f"Unsafe path in archive: {m.name}")
    tar.extractall(dest, filter="data")

def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    dest_r = dest.resolve()
    for m in zf.infolist():
        if not (dest_r / m.filename).resolve().is_relative_to(dest_r):
            raise ValueError(f"Unsafe path in archive: {m.filename}")
    zf.extractall(dest)


if __name__ == "__main__":
    scaling = get_dpi_scaling()
    ctk.set_widget_scaling(scaling)
    ctk.set_window_scaling(scaling)
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("dark-blue")

    app = MonolithApp()
    app.check_incomplete_update()
    app.mainloop()