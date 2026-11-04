"""Guesses whether a process is a backend or a frontend from what it runs. The user can always correct it."""
import json
import re
from pathlib import Path

FRONTEND_PACKAGES = frozenset({"react", "react-dom", "react-scripts", "vue", "@vue/cli-service", "@angular/core", "@angular/cli",
                               "svelte", "@sveltejs/kit", "next", "nuxt", "vite", "webpack-dev-server", "parcel", "gatsby",
                               "preact", "solid-js", "astro", "@vitejs/plugin-react", "ember-source"})
BACKEND_PACKAGES = frozenset({"express", "koa", "fastify", "@nestjs/core", "@hapi/hapi", "hapi", "restify", "apollo-server",
                              "json-server", "mongoose", "sequelize", "typeorm", "@prisma/client", "socket.io", "pg", "mysql2"})
# a dev server in the start script: this is a frontend even if the project also lists server packages
FRONTEND_COMMAND = re.compile(r"\b(ng serve|vite|webpack serve|webpack-dev-server|react-scripts|next dev|vue-cli-service serve|"
                              r"parcel|gatsby develop|nuxt dev|astro dev)\b")
BACKEND_PROGRAMS = frozenset({"java", "javaw", "dotnet", "go", "php", "ruby", "uvicorn", "gunicorn", "flask", "cargo", "rails", "mvn", "gradle"})
_cache = {}


def _package_json(folder):
    """Parsed package.json of a folder, remembered until the file changes."""
    path = Path(folder) / "package.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else None
    except (OSError, ValueError):
        data = None
    _cache[path] = (stamp, data)
    return data


def guess_kind(spec):
    """'backend', 'frontend' or None when there is no good guess. `spec` is the saved launch spec of a process."""
    if not spec:
        return None
    program = Path(str(spec.get("script") or "")).name.lower()
    arguments = " ".join(str(a) for a in (spec.get("args") or [])).lower()
    interpreter = Path(str(spec.get("interpreter") or "")).name.lower()
    if (program in BACKEND_PROGRAMS or program.startswith("python") or interpreter.startswith("python")
            or program.endswith((".jar", ".war", ".py")) or re.search(r"\.(jar|war)\b", arguments)):
        return "backend"
    package = _package_json(spec.get("cwd")) if spec.get("cwd") else None
    if not package:
        return None
    packages = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    start = " ".join(str(scripts.get(name, "")) for name in ("start", "dev", "serve"))
    if FRONTEND_COMMAND.search(start):
        return "frontend"
    frontend, backend = bool(FRONTEND_PACKAGES & set(packages)), bool(BACKEND_PACKAGES & set(packages))
    if frontend and not backend:
        return "frontend"
    if backend and not frontend:
        return "backend"
    return None
