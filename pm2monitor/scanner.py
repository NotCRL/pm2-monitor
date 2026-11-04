"""Looking inside a folder to find how its program starts, so nobody has to know the command.

The result is a list of candidates, most likely first. A candidate whose tool is missing on this computer
goes last and says so (`available`). Nothing here starts anything: it only reads files."""
import json
import re
import shutil
from pathlib import Path

from . import jdk
from .osenv import IS_WINDOWS, find_node, find_npm
from .service import ActionError

MAX_CANDIDATES = 8
START_TARGETS = ("start", "run", "dev", "serve", "server", "web", "avvia", "avvio", "esegui")
NPM_SCRIPTS = ("start", "dev", "serve")
PYTHON_ENTRIES = ("main.py", "app.py", "server.py", "run.py")
NOT_PACKAGES = {"tests", "test", "docs", "venv", "env", "node_modules", "build", "dist", "alembic", "migrations"}
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
PYTHON_APP = re.compile(r"^(\w+)\s*(?::[^=\n]+)?=\s*(FastAPI|Starlette|Flask)\(", re.M)
PYTHON_APP_FACTORY = re.compile(r"^(app|application)\s*=\s*\w+\(", re.M)     # app = create_app()
PYTHON_FRAMEWORK = re.compile(r"\b(FastAPI|Starlette|Flask)\(")
MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", re.M)
DEFAULT_GOAL = re.compile(r"<defaultGoal>\s*\S+\s*</defaultGoal>")


def sanitize_name(text):
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", text or "").strip("-.")[:60]


def quote(token):
    """A file name with spaces must stay one argument: double quotes are understood on every system."""
    return f'"{token}"' if " " in token else token


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def tool_available(token, folder, java_home=None):
    """Whether the program a command starts with can be found on this computer."""
    token = token.strip('"')
    name = Path(token).name.lower()
    if name in ("npm", "npx", "npm.cmd"):
        return bool(find_npm())
    if name in ("node", "node.exe"):
        return bool(find_node())
    if "/" in token or "\\" in token or Path(token).suffix.lower() in (".cmd", ".bat", ".sh"):
        return (Path(folder) / token).is_file() or Path(token).is_file()
    if name == "java" and java_home:
        return True
    return bool(shutil.which(token))


def venv_python(folder):
    """The project's own Python (.venv, venv, env) when it has one."""
    bin_folder, exe = ("Scripts", "python.exe") if IS_WINDOWS else ("bin", "python")
    for name in (".venv", "venv", "env"):
        candidate = Path(folder) / name / bin_folder / exe
        if candidate.is_file():
            return str(candidate)
    return None


def spring_profiles(folder):
    """Profiles a Spring project is meant to run with while developing (dev, plus swagger when it has one)."""
    names = set()
    for place in (folder / "src" / "main" / "resources", folder / "src" / "main" / "resources" / "config", folder / "config", folder):
        for file in place.glob("application-*.*") if place.is_dir() else ():
            if file.suffix in (".yml", ".yaml", ".properties"):
                names.add(file.stem[len("application-"):])
    if "dev" in names:
        jhipster = (folder / ".yo-rc.json").is_file()      # JHipster adds its API documentation with the swagger profile
        return ["dev"] + (["swagger"] if "swagger" in names or jhipster else [])
    return ["local"] if "local" in names else []


def _archives(folder):
    """Runnable archives of a project, in the places build tools leave them."""
    found = []
    for place in (folder, folder / "target", folder / "build" / "libs"):
        for pattern in ("*.jar", "*.war"):
            found += [f for f in sorted(place.glob(pattern)) if not f.name.endswith(("-sources.jar", "-javadoc.jar", "-plain.jar"))]
    return [f.relative_to(folder).as_posix() for f in found][:2]


def _wrapper(folder, posix_name, windows_name):
    """The project's own build tool (mvnw, gradlew) in the form that works on this system, or None."""
    if IS_WINDOWS and (folder / windows_name).is_file():
        return windows_name
    if (folder / posix_name).is_file():
        return windows_name if IS_WINDOWS and (folder / windows_name).is_file() else f"./{posix_name}"
    return None


class _Collector:
    def __init__(self, folder):
        self.folder, self.items = folder, []

    def add(self, kind, command, detail="", java=None, tool=None):
        if command in [c["command"] for c in self.items]:
            return
        first = tool or command.split()[0]
        available = tool_available(first, self.folder, java and java.get("home"))
        item = {"kind": kind, "command": command, "detail": detail, "available": available}
        if java:
            item["java"] = java
        self.items.append(item)


def _java_info(folder, command, jdks):
    tokens = command.replace('"', "").split()
    required = jdk.required_java(folder, tokens)
    chosen = jdk.pick(required, jdks)
    return {"required": required, "major": chosen["major"] if chosen else None, "home": chosen["home"] if chosen else None,
            "exact": bool(chosen) and chosen["major"] == required}


def _jvm_candidates(folder, collect, jdks):
    pom, profiles = _read(folder / "pom.xml"), spring_profiles(folder)
    defines = f"-Dspring.profiles.active={','.join(profiles)} " if profiles else ""
    for archive in _archives(folder):
        command = f"java {defines}-Dfile.encoding=UTF-8 -jar {quote(archive)}"
        collect.add("java", command, archive, _java_info(folder, command, jdks))
    if pom and ("spring-boot" in pom or "quarkus" in pom):
        wrapper = _wrapper(folder, "mvnw", "mvnw.cmd") or "mvn"
        goal = "quarkus:dev" if "quarkus" in pom else "spring-boot:run"
        arguments = "" if DEFAULT_GOAL.search(pom) else f" {goal}"
        if profiles and goal == "spring-boot:run" and not DEFAULT_GOAL.search(pom):    # a default goal comes with its own profile choice
            arguments += f" -Dspring-boot.run.profiles={','.join(profiles)}"
        command = f"{wrapper}{arguments}"
        collect.add("maven", command, "pom.xml", _java_info(folder, command, jdks))
    if (folder / "gradlew").is_file() or (folder / "gradlew.bat").is_file() or (folder / "build.gradle").is_file() or (folder / "build.gradle.kts").is_file():
        wrapper = _wrapper(folder, "gradlew", "gradlew.bat") or "gradle"
        command = f"{wrapper} bootRun"
        collect.add("gradle", command, "gradlew", _java_info(folder, command, jdks))


def _node_candidates(folder, collect):
    package = folder / "package.json"
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
    for script in NPM_SCRIPTS:
        if script in scripts:
            collect.add("npm", "npm start" if script == "start" else f"npm run {script}", script)
    for entry in (data.get("main"), "server.js", "app.js", "index.js"):
        if isinstance(entry, str) and (folder / entry).is_file():
            collect.add("node", f"node {quote(entry)}", entry)
    return sanitize_name(str(data.get("name") or ""))


def _python_apps(folder):
    """[(module, directory the module is found in or None, framework)] for web apps declared in the code."""
    apps = []
    for base in (folder / "src", folder):
        if not base.is_dir():
            continue
        files = [base / "main.py", base / "app.py"] + [d / n for d in sorted(base.iterdir()) if d.is_dir() and d.name not in NOT_PACKAGES
                                                     and not d.name.startswith(".") for n in ("main.py", "app.py")]
        for file in files:
            text = _read(file) if file.is_file() else ""
            direct, factory, framework = PYTHON_APP.search(text), PYTHON_APP_FACTORY.search(text), PYTHON_FRAMEWORK.search(text)
            if direct:
                variable, name = direct.group(1), direct.group(2)
            elif factory and framework:
                variable, name = factory.group(1), framework.group(1)
            else:
                continue
            module = ".".join(file.relative_to(base).with_suffix("").parts)
            apps.append((f"{module}:{variable}", "src" if base.name == "src" and base != folder else None, name))
    return apps


def _python_candidates(folder, collect):
    python = venv_python(folder) or ("python" if IS_WINDOWS else "python3")
    shown = quote(python)
    if (folder / "manage.py").is_file():
        collect.add("django", f"{shown} manage.py runserver", "manage.py")
    for target, source, framework in _python_apps(folder):
        if framework == "Flask":
            collect.add("flask", f"{shown} -m flask --app {target.split(':')[0]} run", target)
        else:
            collect.add("fastapi", f"{shown} -m uvicorn {target}" + (f" --app-dir {source}" if source else ""), target)
    for entry in sorted(folder.iterdir()):
        if entry.is_dir() and entry.name not in NOT_PACKAGES and not entry.name.startswith(".") \
                and (entry / "__main__.py").is_file() and (entry / "__init__.py").is_file():
            collect.add("python", f"{shown} -m {entry.name}", f"{entry.name}/__main__.py")
    for entry in PYTHON_ENTRIES:
        if (folder / entry).is_file():
            collect.add("python", f"{shown} {entry}", entry)


def _other_candidates(folder, collect):
    targets = MAKE_TARGET.findall(_read(folder / "Makefile"))
    for target in START_TARGETS:
        if target in targets:
            collect.add("make", f"make {target}", f"Makefile: {target}")
    for stem in ("start", "run", "serve"):
        for extension in ((".bat", ".cmd") if IS_WINDOWS else (".sh",)):
            if (folder / f"{stem}{extension}").is_file():
                collect.add("script", f".\\{stem}{extension}" if IS_WINDOWS else f"./{stem}{extension}", f"{stem}{extension}")


def suggest_command(folder):
    """What the project in a folder looks like and the commands that could start it, most likely first.

    Returns name, the first candidate's command and kind (empty when nothing is recognised), `candidates`
    [{kind, command, detail, available, java?}] and `notes` [{note, params}] for things the user must know
    (a Java version that is not installed, services to start first)."""
    path = Path(str(folder or "")).expanduser()
    if not path.is_dir():
        raise ActionError("folder_not_found", path=str(folder))
    collect, jdks = _Collector(path), jdk.installed_jdks()
    is_jvm_app = (path / "pom.xml").is_file() and (path / "src" / "main" / "java").is_dir()
    node_name = ""
    if is_jvm_app:                      # a Java server often has a package.json only for its web tooling
        _jvm_candidates(path, collect, jdks)
        node_name = _node_candidates(path, collect)
    else:
        node_name = _node_candidates(path, collect)
        _jvm_candidates(path, collect, jdks)
    _python_candidates(path, collect)
    _other_candidates(path, collect)
    items = sorted(collect.items[:MAX_CANDIDATES * 2], key=lambda c: not c["available"])[:MAX_CANDIDATES]
    notes = []
    for version in sorted({c["java"]["required"] for c in items if c.get("java") and c["java"]["required"] and not c["java"]["home"]}):
        notes.append({"note": "java_missing", "params": {"version": version}})
    if any((path / name).is_file() for name in COMPOSE_FILES):
        notes.append({"note": "services", "params": {"command": "docker compose up -d"}})
    first = items[0] if items else None
    return {"name": node_name or sanitize_name(path.name) or "my-app", "command": first["command"] if first else "",
            "kind": first["kind"] if first else None, "candidates": items, "notes": notes}
