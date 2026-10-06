#!/usr/bin/env python3
"""Release validation for a library repo. Exits 1 with ::error:: on failure.

Checks, in order:
  1. version readable from build.gradle.kts and strictly X.Y.Z (semver)
  2. not a SNAPSHOT
  3. tag does not exist yet (git ls-remote)
  4. version not already published on Maven Central (lib kind only)
  5. version strictly greater than the latest tag AND the latest
     published version (monotonic)

Usage: validate-release.py [--kind lib|app] — `--kind app` (alias: api) skips the Maven
Central checks (APIs publish Docker images, not Maven artifacts).

Env: GITHUB_REF_NAME (must be main), GITHUB_OUTPUT. Stdlib only."""

import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

CENTRAL = "https://repo1.maven.org/maven2"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def fail(msg: str) -> None:
    print(f"::error::{msg}")
    sys.exit(1)


def pom() -> ET.Element | None:
    return ET.parse("pom.xml").getroot() if os.path.exists("pom.xml") else None


def pom_text(root: ET.Element, tag: str) -> str:
    # top-level only; falls back to <parent> for groupId/version inheritance
    ns = "{http://maven.apache.org/POM/4.0.0}"

    return (root.findtext(f"{ns}{tag}") or
            root.findtext(f"{ns}parent/{ns}{tag}") or "")


def read_version() -> str:
    root = pom()

    if root is not None:
        return pom_text(root, "version")

    if os.path.exists("package.json"):
        return json.load(open("package.json")).get("version", "")

    m = re.search(r'^version\s*=\s*"([^"]+)"',
                  open("build.gradle.kts").read(), re.M)

    return m.group(1) if m else ""


def read_group() -> str:
    root = pom()

    if root is not None:
        return pom_text(root, "groupId")

    if not os.path.exists("build.gradle.kts"):
        return ""

    m = re.search(r'^group\s*=\s*"([^"]+)"',
                  open("build.gradle.kts").read(), re.M)

    return m.group(1) if m else ""


def read_artifact() -> str:
    root = pom()

    if root is not None:
        return pom_text(root, "artifactId")

    if not os.path.exists("gradle.properties"):
        return ""

    for line in open("gradle.properties"):
        if line.startswith("POM_ARTIFACT_ID="):
            return line.split("=", 1)[1].strip()

    return ""


def remote_tags() -> list[str]:
    out = subprocess.run(["git", "ls-remote", "--tags", "origin"],
                         capture_output=True, text=True).stdout

    return [line.rsplit("refs/tags/", 1)[-1].strip() for line in out.splitlines()
            if "refs/tags/" in line]


def central_versions(group: str, artifact: str) -> list[str]:
    url = f"{CENTRAL}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"

    try:
        root = ET.fromstring(urllib.request.urlopen(url, timeout=15).read())

        return [v.text for v in root.iter("version")]
    except urllib.error.HTTPError as e:
        return [] if e.code == 404 else fail(f"Central metadata check failed: {e}")
    except Exception as e:
        fail(f"Central metadata check failed: {e}")


def main() -> None:
    kind = sys.argv[sys.argv.index("--kind") + 1] if "--kind" in sys.argv else "lib"
    kind = "app" if kind == "api" else kind  # legacy alias

    if os.environ.get("GITHUB_REF_NAME") != "main":
        fail("The Release workflow must run on main")

    version = read_version()

    if not version:
        fail("Could not read version from pom.xml / build.gradle.kts / package.json")

    if not SEMVER.match(version):
        fail(f"Not a semver X.Y.Z version: {version}")

    if "SNAPSHOT" in version:
        fail(f"Cannot release a SNAPSHOT version: {version}")

    tags = remote_tags()

    if version in tags:
        fail(f"Tag {version} already exists — bump the version")

    group, artifact = read_group(), read_artifact()
    published = (central_versions(group, artifact)
                 if kind == "lib" and group and artifact else [])

    if version in published:
        fail(f"{group}:{artifact}:{version} is already on Maven Central")

    previous = [v for v in tags + published if SEMVER.match(v)]

    if previous:
        latest = max(previous, key=lambda v: tuple(map(int, v.split("."))))

        if tuple(map(int, version.split("."))) <= tuple(map(int, latest.split("."))):
            fail(f"Version {version} must be greater than the latest release {latest}")

    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"version={version}\n")
        
    print(f"Releasing {version}")


if __name__ == "__main__":
    main()
