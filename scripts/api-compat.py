#!/usr/bin/env python3
"""Binary/source API compatibility check via japicmp.

Compares the freshly built jar (build/libs/*.jar) against the latest version
published on Maven Central. Writes japicmp.xml + a markdown report section
to stdout. First release (no published artifact) → prints a note, exits 0.

Usage: api-compat.py [--gate]   — --gate exits 1 if a binary-incompatible
change is detected (used by the release workflow; japicmp's semver check).
Env: none required. Stdlib only."""

import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

JAPICMP = ("https://repo1.maven.org/maven2/com/github/siom79/japicmp/japicmp/"
           "0.26.3/japicmp-0.26.3-jar-with-dependencies.jar")
CENTRAL = "https://repo1.maven.org/maven2"


def coords() -> tuple[str, str] | None:
    """Maven coords of the artifact this repo publishes — None for repos that
    don't publish (services etc.), in which case the check is skipped."""
    try:
        if os.path.exists("pom.xml"):
            ns = "{http://maven.apache.org/POM/4.0.0}"
            root = ET.parse("pom.xml").getroot()
            group = (root.findtext(f"{ns}groupId") or
                     root.findtext(f"{ns}parent/{ns}groupId"))

            return group, root.findtext(f"{ns}artifactId")

        kts = open("build.gradle.kts").read()
        props = open("gradle.properties").read()

        return (re.search(r'^group\s*=\s*"([^"]+)"', kts, re.M).group(1),
                re.search(r'^POM_ARTIFACT_ID\s*=\s*(\S+)', props, re.M).group(1))
    except (OSError, AttributeError):
        return None


def latest_published(group: str, artifact: str) -> str | None:
    url = f"{CENTRAL}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"

    try:
        root = ET.fromstring(urllib.request.urlopen(url, timeout=15).read())
        versions = [v.text for v in root.iter("version")]

        return max(versions, key=lambda v: tuple(map(int, v.split(".")))) if versions else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None

        raise


def download(url: str, dest: str) -> None:
    urllib.request.urlretrieve(url, dest)


def main() -> int:
    c = coords()
    if not c:
        print("No POM_ARTIFACT_ID — repo doesn't publish a library artifact, "
              "skipping API compat check.")
        return 0
    group, artifact = c
    new_jar = next((p for p in glob.glob("build/libs/*.jar") + glob.glob("target/*.jar")
                    if not p.endswith(("-sources.jar", "-javadoc.jar"))), None)

    if not new_jar:
        print("::error::No built jar found — run the package step first")

        return 1

    prev = latest_published(group, artifact)

    if not prev:
        print("No published artifact on Maven Central — first release, no API baseline.")

        return 0

    old_jar = f"{artifact}-{prev}.jar"
    download(f"{CENTRAL}/{group.replace('.', '/')}/{artifact}/{prev}/{old_jar}", old_jar)
    download(JAPICMP, "japicmp.jar")

    gate = "--gate" in sys.argv
    cmd = ["java", "-jar", "japicmp.jar", "-o", old_jar, "-n", new_jar,
           "-m", "-x", "japicmp.xml", "--ignore-missing-classes"]

    if gate:
        cmd.append("--error-on-semantic-incompatibility")

    result = subprocess.run(cmd)

    # report summary for ci-summary.py / job log
    root = ET.parse("japicmp.xml").getroot()
    breaks = []

    for cls in root.iter("class"):
        for elem in cls.iter("compatibilityChange"):
            breaks.append(f"{cls.get('fullyQualifiedName')}: {elem.text}")

    suggested = root.get("semanticVersioning", "?")

    print(f"Compared against `{group}:{artifact}:{prev}` — "
          f"suggested bump: `{suggested}`, binary-incompatible changes: {len(breaks)}")

    for b in breaks[:20]:
        print(f"  - {b}")

    if result.returncode != 0 and gate:
        print("::error::API change violates semantic versioning for the "
              "version being released — bump major/minor accordingly")
              
    return result.returncode if gate else 0


if __name__ == "__main__":
    sys.exit(main())
