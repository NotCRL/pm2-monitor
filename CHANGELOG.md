# Changelog

**English** · [Italiano](CHANGELOG.it.md)

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [1.8.0] - 2026-11-04

### Added
- **You can always tell the program is working.** A slim bar at the top slides while something takes more than a moment (an action, a scan, loading a log, reading a folder). A row shows a small spinner while its start/stop/restart is running, the Scan button spins until it is done, a log dims while it reloads, and the guided setup says "Looking inside the folder…" while it reads one.
- Windows, menus and messages now open with a short, quiet animation. Everything stops moving if your system is set to reduce motion.

### Fixed
- **The guided setup opened late and looked frozen.** It waited for the computer check (Node, npm, pm2) before showing anything. It now opens at once and says "Checking what is installed on this computer… a few seconds."

## [1.7.0] - 2026-11-04

### Added
- **A much smarter folder scan.** Besides npm, node and Python scripts it now recognises: the project's own **Maven/Gradle wrapper** (`mvnw`, `gradlew`; `mvnw.cmd` on Windows) before a global `mvn`; **Spring** projects with their development profiles (`dev`, plus `swagger` for JHipster); **FastAPI/Flask** apps (`python -m uvicorn module:app --app-dir src`), including the `app = create_app()` style; packages with a `__main__.py` (`python -m name`); **Makefile** start targets (`start`, `run`, `dev`, `serve`, `avvia`...); and it uses the project's own **virtual environment** (`.venv`, `venv`).
- **The right Java.** It reads the Java version a project asks for (pom.xml, Gradle, `.java-version`, or the build info inside the `.jar`/`.war`), looks for installed Javas where each system keeps them (JAVA_HOME, PATH, `~/.jdks`, SDKMAN, `/usr/lib/jvm`, Program Files, Adoptium, Corretto, Zulu, macOS...) and starts the program with the matching `JAVA_HOME`. If only a newer Java exists it says so; if none exists it tells you to install it.
- Commands whose tool is not installed on the computer go last, are marked, and are never tried automatically.
- When a project uses Docker services (a database...), the guide shows the command to start them first (`docker compose up -d`) and does not start the program by itself; it never starts the services.

### Fixed
- Programs such as `java`, `npm`, `mvnw` or `make` were handed to pm2 as if they were JavaScript files and failed. They now run as programs.
- On Windows, `.cmd`/`.bat` files, `npm` and `mvn` are started through `cmd /c` (written from pm2's documented behaviour, not tried on Windows).

## [1.6.0] - 2026-11-04

### Added
- **It starts the program by itself.** As soon as you pick the folder, the monitor scans it, tries the likely commands one after the other until one stays up, and keeps it running under pm2. A name already in use gets a number. If nothing works you see every command it tried with its log, and can choose or type one yourself.

## [1.5.0] - 2026-11-04

### Added
- **Folder of each process.** A "folder" column shows where a process runs (the end of the path always stays visible). A click opens the folder in the system's file manager: the monitor asks the system to do it, because a web page cannot, and it only ever opens the folder of a process it knows, never a path coming from a request. A small button copies the path. Linux needs `xdg-open` (package `xdg-utils`); macOS uses `open` and Windows the Explorer (only Linux has been tried).
- **Guided setup rewritten for beginners (step 3).** It now says plainly that you are adding ONE program (a site, an API...) to keep running; it looks in the folder and offers every way it found to start it (npm, node, Python, Django, Java archives, Maven, Gradle, start scripts) as radio buttons instead of a blank command box; and it spells out what it is about to do ("I will run ... in the folder ... and call it ...") before the Start button. File names with spaces are handled.
- **"Next time" box** after the first program starts: how to open the monitor again (the file to double-click, or the command to type, and the address).
- **Choose your columns:** Settings > Columns hides the columns you do not need (remembered).

## [1.4.0] - 2026-11-04

### Added
- **Type column (backend / frontend / your own).** The type is guessed from what the process runs (a `java` program or an Express project is a backend; a `react-scripts`, `vite` or Angular project is a frontend) and shown as "auto: …" until you choose one. Change it from the column, or pick "+ new type…" to create your own (database, worker, ...).
- **Labels.** Any number of coloured labels per process, shown next to its name. Assign or create them from the "+" button, rename, recolour or delete them (and your types) in "Types and labels…" (Settings menu, or the bar above the list), and **filter the list** by type and by labels.

### Changed
- Dropdown menus now stay on the screen wherever their button is: they line up with the button's left edge when it is on the left side, and open upwards when there is little room below.

## [1.3.0] - 2026-10-30

### Added
- **Notifications per domain.** A background watcher tells you when an app crashes, stops, is removed, restarts by itself or uses too much memory, when a daemon stops or comes back, and when a start / stop of a whole domain finishes. Each domain (and the processes without domain) chooses which severities (errors, warnings, good news) and which kinds of event it wants, an optional memory limit, and how to be told: the bell menu (alerts are listed there, never as popups over the page; the bell shakes and shows a counter), browser notifications, a sound, and operating-system notifications that also work while the page is closed. A bell in the header opens the history and the settings; changes made through the monitor itself are not reported as surprises, and a crash loop produces one notice a minute.
- The language of the interface is remembered by the server, so desktop notifications speak the same language.
- Logs can be shown on the right or below the list (button in the logs header, remembered).
- Dialogs opened from inside another one (help, notifications) now stack on top of it with a "Back to …" link, instead of closing it: the guided setup keeps its step and the domain settings keep what you typed.
- **Turn pm2 monitor off** from the page (power button in the header) or with `python3 server.py --stop`. Your apps keep running under pm2.
- **Double-click launchers for every system:** `Start pm2-monitor.bat` (Windows), `Start pm2-monitor.command` (macOS) and `start-pm2-monitor.sh` (Linux) all run `launch.py`, which starts the monitor detached (no console window, log in the configuration folder), recognises when it is already running or when the port is taken, and opens the browser. `launch.py --stop` turns it off; `launch.py --install-shortcut` adds it to the Linux applications menu.
- **Two logs side by side** (⧉ in a log panel, at most two), and **resizable logs**: drag the bar between the list and the logs and the bar between the two logs; sizes are remembered, double-click resets.
- **A tidier header:** grouped actions, status pills for each daemon, a "Settings" menu (gear) with size and language, labels that collapse into icons on narrow windows.
- **Links to the running apps:** a "links" column shows the address each app answers on (`localhost:3000`, ...), clickable, also for the program an app starts (the server behind `npm start`). Only ports that answer like a web page are listed: pm2 monitor sends one harmless `HEAD /` request (user agent `pm2-monitor-link-check`) to each listening port, once per process, so databases and internal ports do not become dead links. The check can be turned off in Settings, which then lists every listening port. Linux reads `/proc`; macOS uses `lsof` and Windows `netstat` (only Linux has been tried).
- **Collapse and expand** the groups of the list (remembered; "Collapse all" / "Expand all"); a collapsed group still shows how many of its processes are online.
- **Browse for a pm2 folder** instead of typing its path, in the daemons window and in the guided setup: the folder picker can show hidden folders, tags the ones that are pm2 data folders, offers them as quick places, and only accepts a real pm2 folder.
- **Text size inside the logs** (A− / A+ in the log toolbar), separate from the zoom of the whole page.
- **Log filters:** search (not case-sensitive, matches highlighted), ERROR / WARN / INFO / DEBUG level buttons with colours (stack traces stay with their error), 0 / ±2 / ±5 lines of context around each result, a choice of 200 / 400 / 1000 / 2000 lines, folding of repeated lines with a counter (timestamps ignored), and Copy / Save of exactly the visible lines.
- Buttons in the logs panel to jump to the first line and to the last one (which also resumes following new lines).

### Changed
- **Notifications open as a dropdown menu under the bell** instead of a modal window, so the page stays usable; the settings of a domain are also inside that domain's own settings window.
- **The guided setup was redesigned for complete beginners:** a clear stepper with checkmarks and "Step N of 3", a plain-words explanation for every step, one big button per step, automatic detection (no need to click "check": it notices a new Node.js or pm2 by itself), a folder browser with quick places, live validation, a "I do not know the command" help, a celebration screen when the first app runs, and optional extras (domains, notifications). "Next" stays disabled until a required step is really done.
- The monitor shares one reading of pm2 between the page and the watcher, so the extra watching does not add load.

## [1.2.0] - 2026-10-30

### Added
- Buttons in the header to make the whole interface smaller or larger (80% to 200%) and to go back to 100%. Text, tables, dialogs, logs and the guided setup all scale together, and the chosen size is remembered in the browser.

### Changed
- All sizes are now relative (`rem`), so they follow the chosen size; at large sizes the header wraps and the table scrolls sideways instead of being squeezed. The "status" column is wider.

## [1.1.0] - 2026-10-30

### Added
- Guided setup for beginners: a wizard checks Node.js and pm2, can install pm2 for you (falling back to your own folder when the system one is protected), lets you pick your project folder with a built-in folder browser, suggests the start command, starts your first app and saves the list. It also explains how to keep apps after a reboot and how to create domains.
- When no pm2 or no daemon is found, the wizard opens by itself once per browser session, the "guided setup" button pulses, and a highlighted card replaces the empty list.
- Tools (Node.js, npm, pm2) are searched again on demand, so a fresh installation is found without restarting the monitor.

### Fixed
- Error details that carry a field named `status` (such as a first app that stops right away) now reach the interface correctly.

## [1.0.0] - 2026-10-29

### Added
- Automatic discovery of pm2 daemons (`PM2_HOME`, `~/.pm2*`, running daemons, folders added by hand).
- Configuration recovery from `pm2 jlist` and from `dump.pm2` while the daemon is down, and relaunch of processes from the saved spec.
- Domains to group processes, with configurable start order and start / restart / stop actions per domain.
- Persistent configuration with a location chosen by `--config` or `PM2_MONITOR_CONFIG`.
- "Help" section in the interface and `--version` option.
- Interface and documentation in English and Italian (language selector in the header).
- Installation and configuration guide for Linux, macOS and Windows (`docs/INSTALL.md`).
- Intended support for Linux, macOS and Windows (tested on Linux only).
- `Host`, `Origin` and `Content-Type` checks to protect the local server.

### Changed
- The code is split into modules (`pm2monitor/`); the interface shows processes grouped by domain.
