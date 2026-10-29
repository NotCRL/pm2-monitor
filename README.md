# pm2-monitor

**English** · [Italiano](README.it.md)

> **In italiano:** pm2-monitor è una UI web locale per vedere e gestire i processi pm2: scopre da sola i demoni, raggruppa i processi in domini con ordine di avvio e funziona su Linux, macOS e Windows. L'interfaccia, il README, la guida di installazione e il CHANGELOG sono disponibili **sia in inglese sia in italiano**: leggi il [README in italiano](README.it.md) e la [guida di installazione](docs/INSTALL.it.md).

Local web UI to view and manage the pm2 processes of any daemon on your computer.
Linux, macOS and Windows; Python standard library only (3.8+), no dependencies.

Start it with `python3 server.py [--port N] [--config PATH] [--version]` and open http://127.0.0.1:8440. The "help" button in the interface collects guides and troubleshooting. The interface is available in English and Italian (selector in the header).

Step-by-step guide (Node.js, pm2, monitor, autostart, for Linux / macOS / Windows): [docs/INSTALL.md](docs/INSTALL.md).

## What it does
- **Discovers pm2 daemons** by itself: the `PM2_HOME` of the environment, the `~/.pm2*` folders, running daemons (their process title contains the `PM2_HOME`; not on Windows) and folders added by hand from the "daemons" button. Each daemon gets a stable id (`.pm2` → `default`, `.pm2-work` → `work`) and an editable label; it can be hidden.
- **Recovers pm2's configuration**: from `pm2 jlist` while the daemon is up, from `dump.pm2` while it is down. For every process it saves how to relaunch it (script, cwd, args, interpreter, mode).
- **Domains** group processes, even from different daemons (e.g. `backend`). A process belongs to one domain.
- **Start order** per process within a domain. "start all" begins with the lowest number and, for each process, waits until it is online and stays so for 2 s before moving on; if one does not start within the domain timeout (default 30 s, editable from ⚙) the sequence stops and says so. "stop all" goes in reverse; "restart" stops, then starts.
- **Start from config**: a saved process that is no longer in the daemon (or whose daemon is down) is relaunched from an ecosystem file generated from its saved spec. The daemon itself comes back too.
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
- `server.py` — HTTP (API: `/api/state`, `/api/logs`, `/api/job`, POST `/api/action`, `/api/domain-action`, `/api/config`)
- `pm2monitor/osenv.py` — OS differences
- `pm2monitor/discovery.py` — daemon discovery, dump reading, launch spec
- `pm2monitor/store.py` — persistent config
- `pm2monitor/service.py` — state, actions, per-domain jobs
- `index.html` — interface (English / Italian) with the "help" section
- `tests/` — `python3 -m unittest discover -s tests -t .`

## Known limits
- Tested on Linux only. On Windows running daemons are not discovered from `ps`: they are found through `PM2_HOME`, `%USERPROFILE%\.pm2*`, or added by hand.
- A process is identified as `daemon/name`: two processes with the same name in different daemons are distinct, in the same daemon they are not (as in pm2).
- Cluster mode is saved (`exec_mode`, `instances`) but only tested in fork mode.
- The server console output and `--help` are in English only.
