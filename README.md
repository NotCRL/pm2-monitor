# pm2-monitor

**English** · [Italiano](README.it.md)

[![tests](https://github.com/NotCRL/pm2-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/NotCRL/pm2-monitor/actions/workflows/tests.yml)

> **In italiano:** pm2-monitor è una UI web locale per vedere e gestire i processi pm2: scopre da sola i demoni, raggruppa i processi in domini con ordine di avvio e funziona su Linux, macOS e Windows. L'interfaccia, il README, la guida di installazione e il CHANGELOG sono disponibili **sia in inglese sia in italiano**: leggi il [README in italiano](README.it.md) e la [guida di installazione](docs/INSTALL.it.md).

Local web UI to view and manage the pm2 processes of any daemon on your computer.
Linux, macOS and Windows; Python standard library only (3.8+), no dependencies.

Start it with `python3 server.py [--port N] [--config PATH] [--version]` and open http://127.0.0.1:8440. The "help" button in the interface collects guides and troubleshooting. The interface is available in English and Italian (selector in the header).

Step-by-step guide (Node.js, pm2, monitor, autostart, for Linux / macOS / Windows): [docs/INSTALL.md](docs/INSTALL.md).

## What it does
- **Guided setup for beginners**: if no pm2 or no daemon is found, a highlighted card and a step-by-step wizard take you by the hand, in plain words: check Node.js, install pm2 (it can do it for you), pick your project folder with a folder browser, and start your first app. It notices on its own when a step is done, suggests the start command, saves the list, and explains how to keep your apps after a reboot. Always available from the "guided setup" button.
- **Notifications per domain**: be told when an app crashes, stops, restarts by itself or uses too much memory, when a daemon stops, or when a group start finishes. Each domain chooses its severities (errors / warnings / good news), the kinds of event, an optional memory limit and the channels: the bell menu, browser notifications, sound, and desktop notifications that also work while the page is closed. Open the bell in the header.
- **Start and stop with a double-click**, on any system: `Start pm2-monitor.bat` (Windows), `Start pm2-monitor.command` (macOS), `start-pm2-monitor.sh` (Linux). The power button in the header (or `python3 server.py --stop`) turns it off; your apps keep running under pm2.
- **Up to two logs side by side**, resizable by dragging the bars, with their own text size.
- **Type and labels**: a *type* column (backend / frontend / your own, guessed from what the process runs and editable) and any number of coloured *labels* per process; filter the list by type and labels.
- **Links to your running apps**: a column shows `localhost:PORT` for each app that serves a web page (found from the ports it listens on, including the program behind `npm start`), one click away.
- **Collapsible groups** in the list, and a **Settings** menu (gear) for the page size and the language.
- **Logs on the right or below** the list, as you prefer, with filters: search, ERROR / WARN / INFO / DEBUG levels, lines of context, hiding of repeated lines, a choice of how many lines to load, jump to the first / last line, and copy or save what you see.
- **Discovers pm2 daemons** by itself: the `PM2_HOME` of the environment, the `~/.pm2*` folders, running daemons (their process title contains the `PM2_HOME`; not on Windows) and folders added by hand from the "daemons" button. Each daemon gets a stable id (`.pm2` → `default`, `.pm2-work` → `work`) and an editable label; it can be hidden.
- **Recovers pm2's configuration**: from `pm2 jlist` while the daemon is up, from `dump.pm2` while it is down. For every process it saves how to relaunch it (script, cwd, args, interpreter, mode).
- **Domains** group processes, even from different daemons (e.g. `backend`). A process belongs to one domain.
- **Start order** per process within a domain. "start all" begins with the lowest number and, for each process, waits until it is online and stays so for 2 s before moving on; if one does not start within the domain timeout (default 30 s, editable from ⚙) the sequence stops and says so. "stop all" goes in reverse; "restart" stops, then starts.
- **Start from config**: a saved process that is no longer in the daemon (or whose daemon is down) is relaunched from an ecosystem file generated from its saved spec. The daemon itself comes back too.
- **Adjustable size**: `A−` / `A+` buttons in the header scale the whole interface (80%–200%) and remember your choice.
- For each process: status, cpu, memory, uptime, restarts (yellow if > 0), pid; single restart / stop / start; click a row for its `out` / `err` log (last 400 lines, available even while the daemon is down).

## Configuration
A `config.json` file in:
- Linux `~/.config/pm2-monitor/` (or `$XDG_CONFIG_HOME`)
- macOS `~/Library/Application Support/pm2-monitor/`
- Windows `%APPDATA%\pm2-monitor\`
- anywhere with `--config /path/config.json` (or a folder) or `PM2_MONITOR_CONFIG`; the command line wins.

It holds known daemons, domains, and for each process its domain / order / launch spec. Written atomically; if unreadable it is moved to `config.json.corrupt-<ts>` and a new one is created (a warning shows in the header). It can be edited by hand, including `pm2Path` (the pm2 to use) and `env` inside a spec.
A spec **does not save the process environment** (it is full of system variables, some sensitive): if a relaunch from scratch needs it, add it by hand as `"env": {...}` in the spec.

## Design choices
- **Never calls pm2 while the daemon is down**: `pm2 jlist` would start a new empty one. The daemon state is read from `PM2_HOME/pm2.pid`.
- **Portable pid check**: on Windows `os.kill(pid, 0)` terminates the process, so the system API (ctypes) is used there.
- **pm2 lookup**: PATH, then nvm, fnm, volta, asdf, Homebrew, global npm and, on Windows, `%APPDATA%\npm` and nvm-windows. Versions are sorted numerically (v18 > v9). pm2's folder is put on the PATH of subprocesses because pm2 is a node script. If it is not found, the interface says so.
- **Actions call pm2 directly**, not custom orchestration scripts: for a full restart with a fixed sequence, use a domain with the right order.
- **Security**: listens on 127.0.0.1 only, rejects non-local `Host` headers (DNS rebinding) and POSTs without `Content-Type: application/json` or with a foreign `Origin`, so a website open in your browser cannot stop your processes. Actions accept only already registered daemons, never arbitrary paths.
- **If the server stops answering** the header turns red ("NOT UPDATED for Ns") instead of showing stale data as good.
- One job per domain at a time; actions on the same daemon are serialized.
- The memory of processes started through `npm` is that of the npm wrapper, not of its children: pm2 does not add them up.

## Feedback and contributions
Report bugs and feature requests at <https://github.com/NotCRL/pm2-monitor/issues> (templates are provided; English or Italian are fine).
Versions and changes are in [CHANGELOG.md](CHANGELOG.md); versions follow Semantic Versioning.

## License
MIT, see [LICENSE](LICENSE).

## Layout
- `launch.py` and the `Start pm2-monitor.*` / `start-pm2-monitor.sh` files — double-click launchers
- `pm2monitor/control.py` — asks a running monitor if it is there and to stop
- `server.py` — HTTP (API: `/api/state`, `/api/logs`, `/api/job`, POST `/api/action`, `/api/domain-action`, `/api/config`)
- `pm2monitor/osenv.py` — OS differences
- `pm2monitor/discovery.py` — daemon discovery, dump reading, launch spec
- `pm2monitor/store.py` — persistent config
- `pm2monitor/service.py` — state, actions, per-domain jobs
- `pm2monitor/setup.py` — guided setup (diagnosis, pm2 install, first app)
- `pm2monitor/notifier.py` — notifications (watcher, per-domain preferences, history, desktop delivery)
- `index.html` — interface (English / Italian) with the "help" section
- `tests/` — `python3 -m unittest discover -s tests -t .`

## Known limits
- Tested on Linux only. On Windows running daemons are not discovered from `ps`: they are found through `PM2_HOME`, `%USERPROFILE%\.pm2*`, or added by hand.
- A process is identified as `daemon/name`: two processes with the same name in different daemons are distinct, in the same daemon they are not (as in pm2).
- Cluster mode is saved (`exec_mode`, `instances`) but only tested in fork mode.
- The server console output and `--help` are in English only.
- Links: only Linux has been tried (macOS uses `lsof`, Windows `netstat`). Apps that listen only on a LAN address, or inside a container, are not detected. To tell web pages from other services the monitor sends one `HEAD /` request to each listening port (once per process); it shows up in an app's access log, and the Settings menu can turn it off.
- Notifications are produced by the running monitor: nothing is reported while it is stopped, and what happened in the meantime is not reported afterwards. Desktop notifications use `notify-send` (Linux), `osascript` (macOS) and PowerShell (Windows); only the Linux one has been exercised, so use the "Send a test" button in the notification settings to check yours.
