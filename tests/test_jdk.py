"""Finding the Java a project needs. Fake JDK folders only: no real Java is run."""
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pm2monitor import jdk


def fake_jdk(root, name, release=None, compiler=True):
    home = Path(root, name)
    (home / "bin").mkdir(parents=True)
    (home / "bin" / jdk.JAVA_FILE).write_text("")
    if compiler:
        (home / "bin" / ("javac.exe" if jdk.IS_WINDOWS else "javac")).write_text("")
    if release:
        (home / "release").write_text(f'JAVA_VERSION="{release}"\n')
    return home


class MajorTest(unittest.TestCase):
    def test_old_and_new_version_styles(self):
        for text, expected in (("1.8.0_504", 8), ("8", 8), ("1.8", 8), ("17.0.2", 17), ("11", 11), ("21", 21), ("", None), (None, None), ("x", None)):
            self.assertEqual(jdk.major_of(text), expected, text)


class InstalledJdksTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        patch = mock.patch.object(jdk, "search_roots", return_value=[Path(self.root)])
        patch.start()
        self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"JAVA_HOME": ""})
        env.start()
        self.addCleanup(env.stop)
        which = mock.patch.object(jdk.shutil, "which", return_value=None)
        which.start()
        self.addCleanup(which.stop)

    def test_the_version_comes_from_the_release_file_or_else_from_the_folder_name(self):
        fake_jdk(self.root, "anything", release="17.0.9")
        fake_jdk(self.root, "corretto-1.8.0_504")                 # JDK 8 has no release file
        fake_jdk(self.root, "temurin-21-jdk")
        self.assertEqual([j["major"] for j in jdk.installed_jdks()], [21, 17, 8])

    def test_folders_without_java_or_version_are_ignored(self):
        (Path(self.root) / "empty").mkdir()
        fake_jdk(self.root, "no-number-here")
        self.assertEqual(jdk.installed_jdks(), [])

    def test_a_macos_bundle_keeps_java_under_contents_home(self):
        bundle = Path(self.root, "zulu-11.jdk", "Contents", "Home", "bin")
        bundle.mkdir(parents=True)
        (bundle / jdk.JAVA_FILE).write_text("")
        self.assertEqual(jdk.installed_jdks()[0]["major"], 11)

    def test_the_same_installation_found_twice_is_listed_once(self):
        home = fake_jdk(self.root, "temurin-17-jdk")
        with mock.patch.dict(os.environ, {"JAVA_HOME": str(home)}):
            self.assertEqual(len(jdk.installed_jdks()), 1)


class PickTest(unittest.TestCase):
    JDKS = [{"home": "/j25", "major": 25, "jdk": True}, {"home": "/j17", "major": 17, "jdk": True}, {"home": "/j8", "major": 8, "jdk": True}]

    def test_exact_version_first_then_the_closest_newer_one(self):
        self.assertEqual(jdk.pick(8, self.JDKS)["home"], "/j8")
        self.assertEqual(jdk.pick(11, self.JDKS)["home"], "/j17")

    def test_nothing_when_unknown_or_too_old(self):
        self.assertIsNone(jdk.pick(None, self.JDKS))
        self.assertIsNone(jdk.pick(30, self.JDKS))


class RequiredJavaTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_maven_properties(self):
        (self.dir / "pom.xml").write_text("<project><properties><java.version>1.8</java.version></properties></project>")
        self.assertEqual(jdk.required_java(self.dir), 8)
        (self.dir / "pom.xml").write_text("<project><properties><maven.compiler.release>17</maven.compiler.release></properties></project>")
        self.assertEqual(jdk.required_java(self.dir), 17)

    def test_gradle_styles(self):
        for text, expected in (("sourceCompatibility = '1.8'", 8), ("sourceCompatibility = JavaVersion.VERSION_11", 11),
                               ("java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }", 21)):
            (self.dir / "build.gradle").write_text(text)
            self.assertEqual(jdk.required_java(self.dir), expected, text)

    def test_the_archive_manifest_is_the_last_resort(self):
        archive = self.dir / "app.war"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nBuild-Jdk: 1.8.0_301\n")
        self.assertEqual(jdk.required_java(self.dir, ["java", "-jar", "app.war"]), 8)
        self.assertIsNone(jdk.required_java(self.dir, ["java", "-jar", "missing.war"]))

    def test_nothing_known_gives_none(self):
        self.assertIsNone(jdk.required_java(self.dir))


class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "pom.xml").write_text("<java.version>1.8</java.version>")
        patch = mock.patch.object(jdk, "installed_jdks", return_value=[{"home": "/opt/j8", "major": 8, "jdk": True}])
        patch.start()
        self.addCleanup(patch.stop)

    def test_java_based_commands_get_the_matching_java_first_on_the_path(self):
        env = jdk.environment_for(self.dir, ["./mvnw"])
        self.assertEqual(env["JAVA_HOME"], "/opt/j8")
        self.assertTrue(env["PATH"].startswith(str(Path("/opt/j8/bin"))))

    def test_other_commands_are_left_alone(self):
        self.assertEqual(jdk.environment_for(self.dir, ["npm", "start"]), {})
        self.assertEqual(jdk.environment_for(self.dir, []), {})

    def test_unknown_requirement_changes_nothing(self):
        (self.dir / "pom.xml").write_text("<project/>")
        self.assertEqual(jdk.environment_for(self.dir, ["java", "-jar", "x.war"]), {})


if __name__ == "__main__":
    unittest.main()
