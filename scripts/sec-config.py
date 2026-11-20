#!/usr/bin/env python3
"""Secret-component declaration files — strict stdlib parser + validator.

Layout (per environment, mirroring the Gluon -secrets repos):

  secrets/
    cert/secrets-cert.yaml    # declared secret env-var names for 'cert'
    pre/secrets-pre.yaml
    pro/secrets-pro.yaml

File format — NAMES ONLY, never values:

  secrets:
    - name: APIGEE_TOKEN_CLIENT_SECRET
    - name: REDIS_PASSWORD

Values live in the platform credential store (Supabase Vault) under the key
`<NAME>__<ENV>` (env uppercased) and are loaded through the dashboard's
Seguridad view — this repo only declares WHICH secrets exist per env.

Subcommands:

  validate [secrets-dir]  PR gate — every env file parses, names are env-var
                          style, `value:`/`key:` entries are rejected, and
                          the same names exist in every env.
  names <environment> [secrets-dir]
                          Print the declared names for that environment.
  env <environment> [secrets-dir]
                          Resolve each declared name to `NAME=value` on
                          stdout by reading `<NAME>__<ENV>` from the
                          credential store (SUPABASE_URL +
                          SUPABASE_SERVICE_ROLE_KEY env vars required).
                          Consumed by vercel-env-sync.py — values are never
                          printed anywhere else; a missing store entry fails
                          the deploy (load it in Seguridad first).
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
DIR_RE = re.compile(r"^[\w-]+$")
FILE_RE = re.compile(r"^secrets-[\w-]+\.ya?ml$")


def fail(msg, code=1):
    print(f"::error::{msg}")
    sys.exit(code)


def parse_file(path):
    """Strict parser — a `secrets:` list of `- name: NAME` maps.
    Anything carrying a value (`value:`/`key:` entries, nested YAML, bare
    strings with a colon) is rejected: declarations are names only."""
    names = []
    in_secrets = False
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            if line.strip() == "secrets:":
                in_secrets = True
                continue
            fail(f"{path}:{n}: unexpected top-level key: {raw.rstrip()}")
        if not in_secrets:
            fail(f"{path}:{n}: entry outside the 'secrets:' list: {raw.rstrip()}")
        m = re.match(r"^\s+-\s+name:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
        if m:
            names.append(m.group(1))
            continue
        m = re.match(r"^\s+-\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
        if m:  # scalar shorthand also accepted
            names.append(m.group(1))
            continue
        fail(f"{path}:{n}: expected '- name: NAME' (names only, no "
             f"values), got: {raw.rstrip()}")
    return names


def env_files(secrets_dir):
    """{env: path} for every secrets/<env>/secrets-<env>.y*ml file."""
    found = {}
    if not os.path.isdir(secrets_dir):
        return found
    for env in sorted(os.listdir(secrets_dir)):
        d = os.path.join(secrets_dir, env)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if FILE_RE.match(f):
                found[env] = os.path.join(d, f)
    return found


def validate(secrets_dir):
    files = env_files(secrets_dir)
    if not files:
        fail(f"no secrets/<env>/secrets-<env>.y*ml files under {secrets_dir}")
    errors = []
    keysets = {}
    for env, path in files.items():
        names = parse_file(path)
        if not names:
            errors.append(f"{path}: no secret names declared")
        if len(names) != len(set(names)):
            errors.append(f"{path}: duplicate secret names")
        keysets[env] = set(names)
        bad = [k for k in names if not KEY_RE.match(k)]
        if bad:
            errors.append(f"{path}: non env-var secret names: "
                          f"{', '.join(bad)}")
    envs = sorted(keysets)
    for env in envs[1:]:
        missing = keysets[envs[0]] - keysets[env]
        extra = keysets[env] - keysets[envs[0]]
        if missing:
            errors.append(f"{env}: missing secrets present in {envs[0]}: "
                          f"{', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{env}: secrets not present in {envs[0]}: "
                          f"{', '.join(sorted(extra))}")
    for e in errors:
        print(f"::error::{e}")
    if errors:
        sys.exit(1)
    print(f"Secrets config OK — {len(files)} env(s): "
          + ", ".join(f"{e} ({len(keysets[e])} secrets)" for e in envs))


def store_key(name, env):
    return f"{name}__{env.upper()}"


def fetch_values(names, env):
    """Resolve declared names to values from the credential store.
    One PostgREST request, values straight to stdout-pipe — never logged."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        fail("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required to "
             "resolve secret values from the credential store")
    wanted = {store_key(n, env): n for n in names}
    q = urllib.parse.urlencode({
        "select": "name,value",
        "name": "in.(" + ",".join(sorted(wanted)) + ")",
    })
    req = urllib.request.Request(f"{url}/rest/v1/platform_secrets?{q}",
                                 headers={"apikey": key,
                                          "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.load(r)
    except urllib.error.HTTPError as e:
        fail(f"credential store lookup failed: HTTP {e.code}")
    found = {row["name"]: row["value"] for row in rows}
    missing = [n for n in names if store_key(n, env) not in found]
    if missing:
        fail(f"no stored value for env '{env}': {', '.join(missing)} — "
             f"load them in the dashboard Seguridad view first")
    return [(n, found[store_key(n, env)]) for n in names]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "validate":
        validate(sys.argv[2] if len(sys.argv) > 2 else "secrets")
    elif cmd == "names":
        if len(sys.argv) < 3:
            fail("usage: sec-config.py names <environment> [secrets-dir]")
        env, secrets_dir = sys.argv[2], (sys.argv[3] if len(sys.argv) > 3
                                         else "secrets")
        path = env_files(secrets_dir).get(env)
        if not path:
            fail(f"no secrets file for environment '{env}' under "
                 f"{secrets_dir}")
        for name in parse_file(path):
            print(name)
    elif cmd == "env":
        if len(sys.argv) < 3:
            fail("usage: sec-config.py env <environment> [secrets-dir]")
        env, secrets_dir = sys.argv[2], (sys.argv[3] if len(sys.argv) > 3
                                         else "secrets")
        path = env_files(secrets_dir).get(env)
        if not path:
            fail(f"no secrets file for environment '{env}' under "
                 f"{secrets_dir}")
        for name, value in fetch_values(parse_file(path), env):
            print(f"{name}={value}")
    else:
        fail(__doc__)


main()
