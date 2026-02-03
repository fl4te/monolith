# JK2 Mod Manager

[![Release](https://img.shields.io/github/v/release/fl4te/jk2_mod_manager?label=latest%20release)](https://github.com/fl4te/jk2_mod_manager/releases) &nbsp;•&nbsp; [![Build Status](https://github.com/fl4te/jk2_mod_manager/actions/workflows/build_and_release.yml/badge.svg?branch=main)](https://github.com/fl4te/jk2_mod_manager/actions/workflows/build_and_release.yml) &nbsp;•&nbsp; [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


A modern graphical mod management tool for  
**Star Wars: Jedi Knight II – Jedi Outcast**

JK2 Mod Manager provides an all-in-one solution to manage PK3 mods, profiles, launch parameters, and RCON connections from a single interface.

---

## Features

### Mod Management
- Install PK3 mods via file selection
- Enable and disable mods without deleting them
- Protected core game files
- Automatic filename-based load order
- Search, rename, and delete mods
- Toggle mods by double-click, context menu, or buttons
- Embedded preview image support

### Profiles
- Multiple independent profiles
- Per-profile configuration:
  - Base folder
  - Game executable path
  - Launch parameters
- Quick profile switching

### Game Launcher
- Launch Jedi Knight II directly
- Developer mode support
- Logfile support
- Custom launch parameters
- Per-profile executable memory

### RCON Console
- Built-in RCON client
- Saved server list
- Live command execution
- Cleaned and readable output

### UI and Utilities
- Dark and Light themes
- Context menus
- Status indicators
- Export mod lists to JSON

---

## First-Time Setup

1. Launch JK2 Mod Manager
2. Create or select a profile
3. Select your Jedi Knight II `base` folder
4. Select the game executable
5. Click **Launch Game**

---

## Troubleshooting

### Mods do not appear
- Ensure the correct `base` folder is selected
- Verify that files use the `.pk3` extension

### Mods do not load in-game
- Adjust load order by renaming the file  
  Example: `zzz_mymod.pk3`

### Where are disabled mods stored?
- Disabled mods are moved to the `_disabled` folder inside the base directory

### Game does not launch
- Verify the executable path
- Check file permissions

### RCON connection issues
- Verify IP address, port, and password
- Check firewall and network settings

---

## Configuration and Log Locations
Windows: %APPDATA%\JK2ModManager\
Linux:   ~/.config/JK2ModManager/\
macOS:   ~/Library/Application Support/JK2ModManager/
