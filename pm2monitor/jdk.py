"""Finding the Java a project needs among the ones installed. Standard library only.

A project built for Java 8 often fails on a newer Java, and the computer's default Java is whatever was
installed last. So the scanner reads which version the project asks for and looks for a matching JDK in the
places each system keeps them, instead of trusting the PATH."""
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

from .osenv import HOME, IS_WINDOWS

JAVA_FILE = "java.exe" if IS_WINDOWS else "java"
WINDOWS_VENDORS = ("Java", "Eclipse Adoptium", "Microsoft", "Amazon Corretto", "Zulu", "BellSoft", "Semeru",
                   "AdoptOpenJDK", "Eclipse Foundation")
VERSION_IN_RELEASE = re.compile(r'^JAVA_VERSION="?([^"\s]+)', re.M)
VERSION_IN_NAME = re.compile(r"(?:^|[^\d])(1\.)?(\d{1,2})(?:[._-]|$)")


def major_of(text):
    """'1.8.0_504' and '8' give 8, '17.0.2' gives 17; None when there is no version in the text."""
    match = re.match(r"\s*(\d+)(?:\.(\d+))?", str(text or ""))
    if not match:
        return None
    first = int(match.group(1))
    return int(match.group(2)) if first == 1 and match.group(2) else first


def search_roots():
    """Folders whose sub-folders are Java installations, for this operating system."""
    roots = [HOME / ".jdks", HOME / ".sdkman" / "candidates" / "java", HOME / ".asdf" / "installs" / "java"]
    if IS_WINDOWS:
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            roots += [Path(base) / vendor for vendor in WINDOWS_VENDORS] if base else []
    elif sys.platform == "darwin":
        roots += [Path("/Library/Java/JavaVirtualMachines"), HOME / "Library" / "Java" / "JavaVirtualMachines"]
    else:
        roots += [Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt/java")]
    return roots


def _as_home(folder):
    """The folder that holds bin/java: a macOS .jdk bundle keeps it under Contents/Home."""
    for candidate in (folder, folder / "Contents" / "Home"):
        if (candidate / "bin" / JAVA_FILE).is_file():
            return candidate
    return None


def _major_of_home(home):
    release = home / "release"
    try:
        match = VERSION_IN_RELEASE.search(release.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        match = None
    if match and major_of(match.group(1)):
        return major_of(match.group(1))
    bundle = home.parent.parent.name if home.name == "Home" else home.name      # macOS: x.jdk/Contents/Home
    named = VERSION_IN_NAME.search(bundle)
    return int(named.group(2)) if named else None


def installed_jdks():
    """[{home, major, jdk}] without duplicates, newest first. `jdk` is False for a runtime that cannot compile."""
    folders = []
    for root in search_roots():
        try:
            folders += sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            continue
    configured = os.environ.get("JAVA_HOME")
    if configured:
        folders.append(Path(configured))
    on_path = shutil.which("java")
    if on_path:
        folders.append(Path(os.path.realpath(on_path)).parent.parent)
    found = {}
    for folder in folders:
        home = _as_home(folder)
        major = _major_of_home(home) if home else None
        if home and major:
            real = os.path.realpath(home)
            has_compiler = (home / "bin" / ("javac.exe" if IS_WINDOWS else "javac")).is_file()
            if real not in found or (has_compiler and not found[real]["jdk"]):
                found[real] = {"home": str(home), "major": major, "jdk": has_compiler}
    return sorted(found.values(), key=lambda j: (-j["major"], not j["jdk"]))


def pick(required, jdks):
    """The installed Java for a required version: the exact one, otherwise the closest newer one. None if unknown."""
    if not required:
        return None
    exact = [j for j in jdks if j["major"] == required]
    if exact:
        return exact[0]
    newer = [j for j in jdks if j["major"] > required]
    return min(newer, key=lambda j: j["major"]) if newer else None


POM_VERSIONS = (re.compile(r"<java\.version>\s*([\d.]+)\s*<"), re.compile(r"<maven\.compiler\.(?:source|target|release)>\s*([\d.]+)\s*<"),
                re.compile(r"<release>\s*([\d.]+)\s*<"), re.compile(r"<(?:source|target)>\s*([\d.]+)\s*<"))
GRADLE_VERSIONS = (re.compile(r"(?:source|target)Compatibility\s*=?\s*['\"]?(?:JavaVersion\.VERSION_)?([\d_.]+)"),
                   re.compile(r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)"), re.compile(r"jvmToolchain\(\s*(\d+)\s*\)"))
MANIFEST_VERSION = re.compile(r"^Build-Jdk(?:-Spec)?:\s*([\d._]+)", re.M)


def _search(patterns, text):
    for pattern in patterns:
        match = pattern.search(text)
        if match and major_of(match.group(1).replace("_", ".")):
            return major_of(match.group(1).replace("_", "."))
    return None


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def archive_java(archive):
    """The Java an executable .jar/.war was built with, from its manifest. None when it says nothing."""
    try:
        with zipfile.ZipFile(archive) as zipped:
            manifest = zipped.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    match = MANIFEST_VERSION.search(manifest)
    return major_of(match.group(1).replace("_", ".")) if match else None


def required_java(folder, command_tokens=()):
    """Java version a project asks for: its build files first, then the archive it is about to run."""
    folder = Path(folder)
    found = (_search(POM_VERSIONS, _read(folder / "pom.xml"))
             or _search(GRADLE_VERSIONS, _read(folder / "build.gradle") + _read(folder / "build.gradle.kts"))
             or major_of(_read(folder / ".java-version").strip()))
    if found:
        return found
    tokens = list(command_tokens)
    for index, token in enumerate(tokens[:-1]):
        if token == "-jar":
            return archive_java(folder / tokens[index + 1])
    return None


def environment_for(folder, command_tokens):
    """Extra environment so a Java-based command runs on the Java the project needs ({} when not needed or unknown)."""
    program = Path(command_tokens[0]).stem.lower() if command_tokens else ""
    if program not in ("java", "mvn", "mvnw", "gradle", "gradlew"):
        return {}
    chosen = pick(required_java(folder, command_tokens), installed_jdks())
    if not chosen:
        return {}
    return {"JAVA_HOME": chosen["home"], "PATH": os.pathsep.join([str(Path(chosen["home"]) / "bin"), os.environ.get("PATH", "")])}
