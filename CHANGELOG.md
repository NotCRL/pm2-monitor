# Changelog

**English** · [Italiano](CHANGELOG.it.md)

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

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
