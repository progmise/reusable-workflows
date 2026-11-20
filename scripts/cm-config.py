#!/usr/bin/env python3
"""ConfigMap-component config files — strict stdlib parser + validator.

Layout (per environment, mirroring the Gluon -cm repos):

  config/
    pre/application-pre.yaml      # flat KEY: value pairs (env-var mode)
    pro/application-pro.yaml

Subcommands:

  validate [config-dir]   PR gate — every env file parses, keys are env-var
                          style, the same keys exist in every env, and no
                          secret-looking keys are present.
  env <environment> [config-dir]
                          Print KEY=value lines for that environment's file
                          (consumed by vercel-env-sync.py).
"""
import os
import re
import sys

KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
FILE_RE = re.compile(r"^application-[\w-]+\.ya?ml$")
# Keys that must live in the secrets repo / credential store, never in a CM.
SECRET_RE = re.compile(r"(PASSWORD|PASSWD|SECRET|PRIVATE_KEY|_TOKEN)$", re.I)


def fail(msg, code=1):
    print(f"::error::{msg}")
    sys.exit(code)


def parse_file(path):
    """Strict flat-KV parser — 'KEY: value' lines, comments and blanks skipped.
    Anything else (nested YAML, lists) is rejected: CMs are env-var only."""
    pairs = {}
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line.strip())
        if not m:
            fail(f"{path}:{n}: expected 'KEY: value', got: {raw.rstrip()}")
        key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
        pairs[key] = val
    return pairs


def env_files(config_dir):
    """{env: path} for every config/<env>/application-<env>.y*ml file."""
    found = {}
    if not os.path.isdir(config_dir):
        return found
    for env in sorted(os.listdir(config_dir)):
        d = os.path.join(config_dir, env)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if FILE_RE.match(f):
                found[env] = os.path.join(d, f)
    return found


def validate(config_dir):
    files = env_files(config_dir)
    if not files:
        fail(f"no config/<env>/application-<env>.y*ml files under {config_dir}")
    errors = []
    keysets = {}
    for env, path in files.items():
        pairs = parse_file(path)
        if not pairs:
            errors.append(f"{path}: no KEY: value entries")
        keysets[env] = set(pairs)
        bad = [k for k in pairs if not KEY_RE.match(k)]
        if bad:
            errors.append(f"{path}: non env-var keys: {', '.join(bad)}")
        leaks = [k for k in pairs if SECRET_RE.search(k)]
        if leaks:
            errors.append(f"{path}: secret-looking keys must live in the "
                          f"credential store, not a ConfigMap: {', '.join(leaks)}")
    envs = sorted(keysets)
    for env in envs[1:]:
        missing = keysets[envs[0]] - keysets[env]
        extra = keysets[env] - keysets[envs[0]]
        if missing:
            errors.append(f"{env}: missing keys present in {envs[0]}: "
                          f"{', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{env}: keys not present in {envs[0]}: "
                          f"{', '.join(sorted(extra))}")
    for e in errors:
        print(f"::error::{e}")
    if errors:
        sys.exit(1)
    print(f"ConfigMap config OK — {len(files)} env(s): "
          + ", ".join(f"{e} ({len(keysets[e])} keys)" for e in envs))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "validate":
        validate(sys.argv[2] if len(sys.argv) > 2 else "config")
    elif cmd == "env":
        if len(sys.argv) < 3:
            fail("usage: cm-config.py env <environment> [config-dir]")
        env, config_dir = sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "config")
        path = env_files(config_dir).get(env)
        if not path:
            fail(f"no config file for environment '{env}' under {config_dir}")
        for k, v in parse_file(path).items():
            print(f"{k}={v}")
    else:
        fail(__doc__)


main()
