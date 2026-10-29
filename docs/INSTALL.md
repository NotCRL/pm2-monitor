# Installation and configuration

**English** · [Italiano](INSTALL.it.md)

A guide to installing **pm2**, configuring it for your processes and using **pm2-monitor** to control them. It covers Linux, macOS and Windows: where commands differ, there is one entry per system.

Contents
1. [What you need](#1-what-you-need)
2. [Install Node.js](#2-install-nodejs)
3. [Install pm2](#3-install-pm2)
4. [Configure pm2 for your processes](#4-configure-pm2-for-your-processes)
5. [Several separate pm2 daemons](#5-several-separate-pm2-daemons)
6. [Start pm2 automatically at login or boot](#6-start-pm2-automatically-at-login-or-boot)
7. [Install and start pm2-monitor](#7-install-and-start-pm2-monitor)
8. [Configure pm2-monitor](#8-configure-pm2-monitor)
9. [Start pm2-monitor automatically](#9-start-pm2-monitor-automatically)
10. [Common problems](#10-common-problems)

---

## 1. What you need

| For | You need | Check |
|---|---|---|
| pm2 | Node.js (a recent LTS version) and npm | `node -v` · `npm -v` |
| pm2-monitor | Python 3.8 or newer. No packages to install | `python3 --version` (on Windows `python --version` or `py --version`) |

On Windows, the commands in this guide go in **PowerShell** unless stated otherwise.

## 2. Install Node.js

Skip this step if `node -v` already prints a version.

**All systems:** download the LTS installer from <https://nodejs.org> and run it.

Command-line alternatives:

- **Linux / macOS, with nvm** (recommended: no `sudo`, several versions side by side). Install nvm following <https://github.com/nvm-sh/nvm>, reopen the terminal, then:
  ```bash
  nvm install --lts
  nvm use --lts
  ```
- **macOS, with Homebrew:** `brew install node`
- **Windows, with winget:** `winget install OpenJS.NodeJS.LTS`
- **Windows, with nvm-windows:** install from <https://github.com/coreybutler/nvm-windows>, then `nvm install lts` and `nvm use lts`
- **Linux, from the package manager** (often outdated versions): `sudo apt install nodejs npm` · `sudo dnf install nodejs npm` · `sudo pacman -S nodejs npm`

Close and reopen the terminal, then check `node -v` and `npm -v`.

## 3. Install pm2

```bash
npm install -g pm2
pm2 --version
```

- **Linux with the system Node** (not nvm): if `npm install -g` fails with `EACCES`, do not use `sudo`; set a global folder of your own:
  ```bash
  mkdir -p ~/.npm-global
  npm config set prefix ~/.npm-global
  ```
  and add `~/.npm-global/bin` to your `PATH` (in `~/.bashrc` or `~/.zshrc`: `export PATH="$HOME/.npm-global/bin:$PATH"`).
- **Windows:** if PowerShell says that running scripts is disabled (`pm2.ps1 cannot be loaded`), use `pm2.cmd` instead of `pm2`, or allow scripts for your user only with
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- **Where it is installed** (useful for `pm2Path`, see section 8): `npm root -g` shows the packages folder, and the `pm2` command sits in the `bin` folder next to it (on Windows directly in the folder shown by `npm prefix -g`).

## 4. Configure pm2 for your processes

### Start a process

```bash
pm2 start app.js --name my-app              # a node script
pm2 start npm --name my-frontend -- start   # an npm command (npm start)
pm2 start /path/server.py --interpreter python3 --name my-script   # a Python script
pm2 start /path/bin/my-program --name my-binary                    # an executable
```
On Windows start a Python script with `--interpreter python` and use `\` in paths. To start from the right folder, `cd` there first or use `--cwd <folder>`.

### Everyday commands

| Command | What it does |
|---|---|
| `pm2 list` | lists processes and their status |
| `pm2 logs [name]` | follows the logs (Ctrl+C to exit) |
| `pm2 stop <name>` / `pm2 start <name>` | stops / starts an already registered process |
| `pm2 restart <name>` | restarts |
| `pm2 delete <name>` | removes it from pm2 (files are not deleted) |
| `pm2 save` | saves the current list to `dump.pm2` |
| `pm2 resurrect` | restores the list saved with `pm2 save` |
| `pm2 kill` | stops the pm2 daemon and all its processes |

pm2 works with a background **daemon**: the first command starts it, and processes stay alive after you close the terminal.

### Configuration file (recommended for several processes)

Create `ecosystem.config.js` in the project folder:

```js
module.exports = {
  apps: [
    {
      name: 'database',
      script: '/path/db/start.sh',
      cwd: '/path/db',
    },
    {
      name: 'backend',
      script: 'npm',
      args: 'start',
      cwd: '/path/backend',
      env: { NODE_ENV: 'development', PORT: 3000 },
    },
  ],
};
```
Then:
```bash
pm2 start ecosystem.config.js            # all of them
pm2 start ecosystem.config.js --only backend
pm2 save
```
On Windows write paths with `/` or with a doubled `\\` in the JS file.

**Saving** with `pm2 save` matters: pm2-monitor rebuilds the configuration of your processes, even while the daemon is down, from `dump.pm2`.

## 5. Several separate pm2 daemons

Usually one is enough (the `~/.pm2` folder). To keep groups of processes apart (for example two projects that must not affect each other), use a different `PM2_HOME` folder for each. pm2-monitor finds the folders named `.pm2*` in your home by itself.

| Shell | Command |
|---|---|
| Linux / macOS (bash, zsh) | `PM2_HOME=~/.pm2-project pm2 start ecosystem.config.js` |
| Windows PowerShell | `$env:PM2_HOME="$HOME\.pm2-project"; pm2 start ecosystem.config.js` |
| Windows cmd | `set PM2_HOME=%USERPROFILE%\.pm2-project` and then `pm2 start ecosystem.config.js` |

Remember to set the same `PM2_HOME` for **every** later pm2 command on that daemon (`pm2 list`, `pm2 stop`, ...), otherwise you talk to the default daemon. For a folder not named `.pm2*`, add it by hand from "daemons" in the pm2-monitor interface.

## 6. Start pm2 automatically at login or boot

Needed if you want your processes back after the computer restarts. First `pm2 save` to fix the list, then:

- **Linux and macOS:**
  ```bash
  pm2 startup
  ```
  pm2 prints **a command to copy and run** (usually with `sudo`): run it, then `pm2 save`. It works with systemd on Linux and launchd on macOS.
- **Windows:** `pm2 startup` is not supported. Options:
  - Community tools such as [pm2-installer](https://github.com/jessety/pm2-installer), which registers pm2 as a service.
  - A scheduled task that runs `pm2 resurrect` at login (Task Scheduler → "Create Task"; action: start `pm2.cmd` with argument `resurrect`).

With several daemons (section 5) the startup command must be repeated for each `PM2_HOME`; alternatively use a small login script that runs `pm2 resurrect` for each.

## 7. Install and start pm2-monitor

1. Download the latest version from the repository's [**Releases** page](https://github.com/NotCRL/pm2-monitor/releases) (`.zip` or `.tar.gz` file) and unpack it into a fixed folder, for example `~/pm2-monitor` (on Windows `C:\Users\<you>\pm2-monitor`). Alternatively `git clone` the repository.
2. Check Python: `python3 --version` (Windows: `python --version`). On Windows, if missing: `winget install Python.Python.3.12`. On macOS: `brew install python` or the installer from <https://www.python.org>. On Linux it is usually already there; otherwise `sudo apt install python3` (or your distribution's equivalent).
3. Start it from the unpacked folder:
   ```bash
   python3 server.py          # Windows: python server.py
   ```
4. Open **http://127.0.0.1:8440** in your browser. The server keeps running until you close the terminal (to keep it always on, see section 9).

Options: `--port N` (a different port), `--config PATH` (config elsewhere, see section 8), `--version`.

There are no packages to install: it only uses Python's standard library. The server listens **only** on `127.0.0.1`, so it is not reachable from the network. The interface is available in English and Italian (selector in the header).

## 8. Configure pm2-monitor

On first start the monitor looks for the computer's pm2 daemons by itself. Then, from the interface:

- **scan**: repeats the daemon search.
- **daemons**: rename a daemon, hide it, add one by hand (a `PM2_HOME` folder).
- **domains** (`+ domain`): group processes, even from different daemons. Assign a process to a domain from the row's drop-down.
- **ord**: start order within the domain (lower number = starts first). "start all" waits for each process to be online before the next. ⚙ next to the domain sets the maximum wait time.

### Where the configuration file lives

| System | Default location |
|---|---|
| Linux | `~/.config/pm2-monitor/config.json` (or under `$XDG_CONFIG_HOME`) |
| macOS | `~/Library/Application Support/pm2-monitor/config.json` |
| Windows | `%APPDATA%\pm2-monitor\config.json` |

To change it:
```bash
python3 server.py --config /path/my-config.json     # a file, or a folder
```
or with the `PM2_MONITOR_CONFIG` environment variable (Linux/macOS: `export PM2_MONITOR_CONFIG=...`; PowerShell: `$env:PM2_MONITOR_CONFIG="..."`). The command line wins. The current path is always visible in the interface, under **help**.

To use the same settings on another computer, copy the file.

### What it contains and what you can edit by hand (with the server stopped)

- `pm2Path`: path of a specific pm2 to use, if the monitor cannot find it or you have several. Example: `"pm2Path": "/home/you/.nvm/versions/node/v20.11.0/bin/pm2"` or on Windows `"pm2Path": "C:\\Users\\you\\AppData\\Roaming\\npm\\pm2.cmd"`.
- `extraHomes`: `PM2_HOME` folders to search in addition to the ones found by itself.
- `processes`: for each process its domain, order and launch spec (script, folder, arguments, interpreter). If a process needs environment variables to start from scratch, add `"env": { "NAME": "value" }` to its `spec`: the environment is not saved automatically because it may hold sensitive data.

## 9. Start pm2-monitor automatically

Replace `/path/pm2-monitor` with the real folder.

### Linux (systemd, user level)

Create `~/.config/systemd/user/pm2-monitor.service`:
```ini
[Unit]
Description=pm2-monitor

[Service]
ExecStart=/usr/bin/python3 /path/pm2-monitor/server.py
Restart=on-failure

[Install]
WantedBy=default.target
```
Then:
```bash
systemctl --user daemon-reload
systemctl --user enable --now pm2-monitor
```
(`which python3` gives you the right Python path. To start it without logging in: `loginctl enable-linger $USER`.)

### macOS (launchd)

Create `~/Library/LaunchAgents/pm2-monitor.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>pm2-monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/pm2-monitor/server.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```
Then `launchctl load ~/Library/LaunchAgents/pm2-monitor.plist` (to stop it: `launchctl unload ...`). With Homebrew's Python replace `/usr/bin/python3` with the output of `which python3`.

### Windows (Task Scheduler)

From PowerShell, to start it at every login without a console window:
```powershell
schtasks /Create /SC ONLOGON /TN "pm2-monitor" /TR "pythonw C:\path\pm2-monitor\server.py"
```
To remove it: `schtasks /Delete /TN "pm2-monitor" /F`.

In every case, if the monitor starts outside your terminal and cannot find pm2, set `pm2Path` in the config (section 8).

## 10. Common problems

| Symptom | Likely cause and fix |
|---|---|
| `pm2: command not found` / `not recognized` | npm's global folder is not on the `PATH`. Reopen the terminal; check with `npm prefix -g` and add that folder (Linux/macOS: its `bin`) to the `PATH`. |
| `EACCES` installing pm2 | Do not use `sudo`: see section 3 (personal global folder) or use nvm. |
| PowerShell: "scripts are disabled" | Use `pm2.cmd` or `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| The monitor says "pm2 not found" | Common when it starts from a service or a scheduled task, which do not have your `PATH`. Set `pm2Path` in the config. |
| A daemon does not show up | Add its folder from "daemons". On Windows running daemons are not discovered automatically: `PM2_HOME` or the `.pm2*` folders in your home are needed. |
| "daemon stopped" | That group's daemon is not running. Processes are shown from the saved config and "start" also brings the daemon back. |
| A "not started" process will not start | Read the error shown; check that the script and folder in its spec still exist, and if needed add `env` (section 8). |
| Port 8440 is in use | Start with `--port 8450` (or another free port). |
| `SyntaxError` when starting the monitor | Python too old: 3.8 or newer is required. |

For anything else, the monitor window has **help**; for bugs and requests open an Issue on the repository.
