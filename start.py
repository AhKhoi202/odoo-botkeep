#!/usr/bin/env python3
"""Odoo 20.0 Community launcher for a Botkeep Python 3.12 server.

First start (takes several minutes):
  1. Streams the Odoo 20.0 source from GitHub (fallback: nightly.odoo.com) and keeps
     only what is needed at runtime: Vietnamese translations only, no foreign
     l10n_* modules (l10n_vn* kept), no test folders.
  2. Creates ./venv and installs Odoo's Python requirements
     (psycopg2 -> psycopg2-binary, python-ldap skipped: no compiler in the container).
  3. Connects to the PostgreSQL server in PGHOST. If it cannot be reached from this
     container, runs PostgreSQL 16 inside the container instead (pgserver wheel,
     data in ./pgdata, listening on 127.0.0.1:5432).
  4. Initializes the database (module base + language vi_VN) and sets the admin password.
Every start: writes ./odoo.conf and runs Odoo on 0.0.0.0:$SERVER_PORT.

Environment variables (Botkeep > Environment; also read from ./.env):
  required  PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE  (from the PostgreSQL server's Database tab)
  optional  PGSSLMODE (default: prefer)
            ODOO_ADMIN_PASSWORD  password for login "admin" at first init;
                                 if empty a random one is written to ./ODOO_ADMIN_PASSWORD.txt
            ODOO_LANG            language loaded at init (default: vi_VN)
To reinstall: delete the folders odoo/ and venv/ in Files, then restart.
To reset the local database: stop the server, delete the folders pgdata/ and data/, then restart.
"""
import base64
import glob
import hashlib
import lzma
import os
import pwd
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request

BRANCH = "20.0"
HOME = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HOME, "odoo")
VENV = os.path.join(HOME, "venv")
VPY = os.path.join(VENV, "bin", "python")
DATA = os.path.join(HOME, "data")
CUSTOM = os.path.join(HOME, "custom_addons")
CONF = os.path.join(HOME, "odoo.conf")
STATE = os.path.join(HOME, ".odoo_setup")
PG_DATA = os.path.join(HOME, "pgdata")
PG_HOST = "127.0.0.1"
PG_PORT = "5432"
PG_SYSTEM_USER = "odoopg"  # PostgreSQL refuses to run as root; used only if this container runs as root
# LD_PRELOAD shim (source: pgshim.c, see pg_shim()): gives the container's uid a passwd entry,
# because initdb aborts with "could not look up effective user ID 998" when the uid has none.
PG_SHIM_SHA256 = "b337fc4b1278ee1b2541a9023f166e55e563632c6479b74012471f8519cf5c98"
PG_SHIM_XZ_B64 = "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"
URLS = [
    f"https://codeload.github.com/odoo/odoo/tar.gz/refs/heads/{BRANCH}",
    f"https://nightly.odoo.com/{BRANCH}/nightly/src/odoo_{BRANCH}.latest.tar.gz",
]
KEEP_PO = {"vi.po", "vi_VN.po"}
KEEP_L10N = ("l10n_vn",)
TOP_LEVEL = {"odoo", "addons", "odoo-bin", "requirements.txt", "LICENSE", "COPYRIGHT"}

PG_SETUP = """
import os
import psycopg2
from psycopg2 import sql

user = os.environ["PGUSER"]
password = os.environ["PGPASSWORD"]
dbname = os.environ["PGDATABASE"]
conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres", dbname="postgres")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,))
if cur.fetchone() is None:
    cur.execute(sql.SQL("CREATE ROLE {} LOGIN SUPERUSER PASSWORD %s").format(sql.Identifier(user)), (password,))
else:
    cur.execute(sql.SQL("ALTER ROLE {} LOGIN SUPERUSER PASSWORD %s").format(sql.Identifier(user)), (password,))
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
if cur.fetchone() is None:
    cur.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(dbname), sql.Identifier(user)))
conn.close()
print("PostgreSQL role and database ready")
"""


def log(msg):
    print(f"[odoo-setup] {msg}", flush=True)


def disk_usage(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total // (1024 * 1024)


def load_dotenv():
    """Botkeep writes the Environment tab to ./.env; the process does not read it by itself."""
    path = os.path.join(HOME, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


# ---------------------------------------------------------------- source
def keep(rel):
    parts = rel.split("/")
    if parts[0] not in TOP_LEVEL:
        return False
    if parts[0] == "addons":
        idx = 1
    elif parts[:2] == ["odoo", "addons"]:
        idx = 2
    else:
        return True
    if len(parts) <= idx:
        return True
    mod, sub = parts[idx], parts[idx + 1:]
    if mod.startswith("l10n_") and not mod.startswith(KEEP_L10N):
        return False
    if not sub:
        return True
    if sub[0] in ("i18n", "i18n_extra") and sub[-1].endswith(".pot"):
        return True  # templates are merged into .po files at load time
    if sub[0] in ("i18n", "i18n_extra") and len(sub) > 1 and sub[-1] not in KEEP_PO:
        return False
    if mod != "base" and sub[0] == "tests":
        return False
    if len(sub) > 1 and sub[0] == "static" and sub[1] == "tests":
        return False
    return True


def download_source():
    tmp = SRC + ".partial"
    for url in URLS:
        shutil.rmtree(tmp, ignore_errors=True)
        log(f"Downloading Odoo {BRANCH} source: {url}")
        started, count, skipped = time.time(), 0, 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "odoo-botkeep-setup"})
            with urllib.request.urlopen(req, timeout=180) as resp, \
                    tarfile.open(fileobj=resp, mode="r|gz") as tar:
                for member in tar:
                    parts = member.name.split("/", 1)
                    if len(parts) < 2 or not parts[1]:
                        continue
                    rel = parts[1].rstrip("/")
                    if not (member.isfile() or member.isdir() or member.issym()) or not keep(rel):
                        skipped += 1
                        continue
                    member.name = rel
                    try:
                        tar.extract(member, tmp, filter="data")
                    except Exception as err:  # unsafe link etc.
                        log(f"  skip {rel}: {err}")
                        continue
                    count += 1
                    if count % 5000 == 0:
                        log(f"  {count} files kept, {skipped} skipped, {int(time.time() - started)}s")
            if not os.path.isfile(os.path.join(tmp, "odoo", "release.py")):
                raise RuntimeError("unexpected archive layout (odoo/release.py missing)")
            os.replace(tmp, SRC)
            log(f"Source ready: {count} files kept, {skipped} skipped, {disk_usage(SRC)} MB")
            return
        except Exception as err:
            log(f"Download failed from {url}: {err}")
            shutil.rmtree(tmp, ignore_errors=True)
    log("ERROR: could not download the Odoo source. Check outbound network access, then restart.")
    sys.exit(1)


def download_pot_files():
    """Add the i18n/*.pot templates that earlier setups skipped (Odoo merges them into .po files)."""
    url = URLS[0]
    log(f"Downloading translation templates (*.pot): {url}")
    count = 0
    req = urllib.request.Request(url, headers={"User-Agent": "odoo-botkeep-setup"})
    with urllib.request.urlopen(req, timeout=180) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tar:
        for member in tar:
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not member.isfile() or not parts[1].endswith(".pot") or not keep(parts[1]):
                continue
            member.name = parts[1]
            tar.extract(member, SRC, filter="data")
            count += 1
    log(f"{count} .pot files added")


# ---------------------------------------------------------------- python deps
def build_requirements():
    lines = []
    with open(os.path.join(SRC, "requirements.txt"), encoding="utf-8") as fh:
        for raw in fh:
            spec = raw.split(" #")[0].strip()
            if not spec or spec.startswith("#"):
                continue
            name = re.split(r"[\s=<>!~;\[]", spec, maxsplit=1)[0].lower()
            if name == "python-ldap":          # needs libldap headers + compiler
                continue
            if name == "psycopg2":             # needs libpq headers + compiler
                spec = "psycopg2-binary" + spec[len(name):]
            if name == "rl-renderpm":          # reportlab bitmap renderer (barcodes); wheel on Linux too
                spec = spec.split(";")[0].strip()
            lines.append(spec)
    path = os.path.join(HOME, "requirements-botkeep.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def install_deps():
    if not os.path.isfile(VPY):
        log("Creating virtualenv ./venv")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
    req = build_requirements()
    log("Installing Python requirements (a few minutes)...")
    subprocess.run([VPY, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                    "--prefer-binary", "-r", req], check=True)
    log(f"Virtualenv ready: {disk_usage(VENV)} MB")


# ---------------------------------------------------------------- network
def own_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))  # no packet is sent for a UDP connect
            return sock.getsockname()[0]
    except OSError:
        return "?"


def default_gateway():
    try:
        with open("/proc/net/route", encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except (OSError, ValueError, StopIteration):
        pass
    return None


def choose_pg_host():
    """Return True when the PostgreSQL server at PGHOST:PGPORT accepts TCP connections.

    Botkeep's public endpoint was not reachable from other containers in the past,
    so the gateway and the public hostname are tried as well; the first one that
    answers becomes PGHOST.
    """
    port = int(os.environ.get("PGPORT", "5432"))
    gateway = default_gateway()
    log(f"This container: {own_ip()}, gateway: {gateway or '?'}")
    candidates = []
    for host in (os.environ.get("PGHOST"), "node6.botkeep.cloud", gateway):
        if host and host not in candidates:
            candidates.append(host)
    for host in candidates:
        try:
            with socket.create_connection((host, port), timeout=5):
                log(f"TCP to {host}:{port} OK")
                os.environ["PGHOST"] = host
                return True
        except OSError as err:
            log(f"TCP to {host}:{port} failed: {err}")
    return False


# ---------------------------------------------------------------- local postgres
def pg_run_as():
    """Account for PostgreSQL's tools: None when this container runs as a normal user."""
    if os.geteuid() != 0:
        return None
    try:
        return pwd.getpwnam(PG_SYSTEM_USER)
    except KeyError:
        log(f"Creating system account {PG_SYSTEM_USER} for PostgreSQL (it refuses to run as root)")
        subprocess.run(["useradd", "--system", "--create-home", "--shell", "/bin/sh", PG_SYSTEM_USER],
                       check=True)
        return pwd.getpwnam(PG_SYSTEM_USER)


def pg_shim():
    """Write the shim to ./pgshim/libpgshim.so and return its path.

    Built from a small C file: getpwuid_r/getpwuid return a synthetic passwd entry
    (name from PG_OS_USER) when the real lookup finds nothing. Used via LD_PRELOAD.
    """
    blob = lzma.decompress(base64.b64decode(PG_SHIM_XZ_B64))
    if hashlib.sha256(blob).hexdigest() != PG_SHIM_SHA256:
        log("ERROR: the built-in PostgreSQL shim is corrupt (checksum mismatch)")
        sys.exit(1)
    path = os.path.join(HOME, "pgshim", "libpgshim.so")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    os.chmod(path, 0o755)
    return path


def pg_env():
    env = dict(os.environ)
    shim = pg_shim()
    env["LD_PRELOAD"] = shim + (":" + env["LD_PRELOAD"] if env.get("LD_PRELOAD") else "")
    env.setdefault("PG_OS_USER", "odoo")
    return env


def run_pg(args, **kwargs):
    kwargs.setdefault("env", pg_env())
    owner = pg_run_as()
    if owner is None:
        return subprocess.run(args, **kwargs)

    def drop_privileges():
        os.setgid(owner.pw_gid)
        os.setuid(owner.pw_uid)

    return subprocess.run(args, preexec_fn=drop_privileges, **kwargs)


def pg_tool(name):
    """Path of a PostgreSQL binary shipped inside the pgserver wheel, or None."""
    hits = sorted(glob.glob(os.path.join(VENV, "lib", "python3*", "site-packages",
                                         "pgserver", "pginstall", "bin", name)))
    return hits[-1] if hits else None


def pg_is_ready(bindir):
    res = run_pg([os.path.join(bindir, "pg_isready"), "-h", PG_HOST, "-p", PG_PORT],
                 capture_output=True, text=True)
    return res.returncode == 0


def start_local_postgres():
    """Run PostgreSQL 16 inside this container (used when PGHOST is unreachable)."""
    log("Starting PostgreSQL inside this container")
    if pg_tool("initdb") is None:
        log("Installing PostgreSQL 16 binaries from the pgserver wheel (a few minutes)...")
        subprocess.run([VPY, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                        "--no-deps", "pgserver==0.1.4"], check=True)
    initdb = pg_tool("initdb")
    if initdb is None:
        log("ERROR: pgserver installed but its PostgreSQL binaries were not found")
        sys.exit(1)
    bindir = os.path.dirname(initdb)

    owner = pg_run_as()
    os.makedirs(PG_DATA, mode=0o700, exist_ok=True)
    if owner is not None:
        os.chown(PG_DATA, owner.pw_uid, owner.pw_gid)
    if not os.path.isfile(os.path.join(PG_DATA, "PG_VERSION")):
        log("Creating PostgreSQL cluster in ./pgdata")
        run_pg([initdb, "-D", PG_DATA, "-U", "postgres", "-A", "trust",
                "--encoding=UTF8", "--locale=C"], check=True)
    if not pg_is_ready(bindir):
        log(f"Starting PostgreSQL on {PG_HOST}:{PG_PORT}")
        run_pg([os.path.join(bindir, "pg_ctl"), "-D", PG_DATA,
                "-l", os.path.join(PG_DATA, "server.log"),
                "-o", f"-c listen_addresses={PG_HOST} -c port={PG_PORT} -k {PG_DATA}",
                "-t", "120", "-w", "start"], check=True)
    subprocess.run([VPY, "-c", PG_SETUP], env=dict(os.environ), check=True)
    os.environ["PGHOST"] = PG_HOST
    os.environ["PGPORT"] = PG_PORT
    log(f"Local PostgreSQL ready on {PG_HOST}:{PG_PORT}")


# ---------------------------------------------------------------- config / db
def master_password():
    path = os.path.join(HOME, ".odoo_master_password")
    if not os.path.isfile(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_urlsafe(24))
        os.chmod(path, 0o600)
    with open(path) as fh:
        return fh.read().strip()


def addons_paths():
    paths = [p for p in (os.path.join(SRC, "odoo", "addons"), os.path.join(SRC, "addons")) if os.path.isdir(p)]
    os.makedirs(CUSTOM, exist_ok=True)
    if any(os.path.isfile(os.path.join(CUSTOM, d, "__manifest__.py")) for d in os.listdir(CUSTOM)):
        paths.append(CUSTOM)
    return paths


def write_conf(db):
    port = os.environ.get("SERVER_PORT", "8069")
    conf = f"""[options]
addons_path = {",".join(addons_paths())}
data_dir = {DATA}
http_interface = 0.0.0.0
http_port = {port}
proxy_mode = True
list_db = False
dbfilter = ^{re.escape(db)}$
admin_passwd = {master_password()}
workers = 0
max_cron_threads = 1
db_maxconn = 16
log_level = info
"""
    with open(CONF, "w", encoding="utf-8") as fh:
        fh.write(conf)
    os.chmod(CONF, 0o600)
    log(f"odoo.conf written (port {port})")


def odoo_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env.setdefault("PGSSLMODE", "prefer")
    return env


def db_initialized():
    code = ("import psycopg2;c=psycopg2.connect('');cur=c.cursor();"
            "cur.execute(\"select to_regclass('public.ir_module_module')\");"
            "print('yes' if cur.fetchone()[0] else 'no')")
    out = subprocess.run([VPY, "-c", code], env=odoo_env(), capture_output=True, text=True)
    if out.returncode != 0:
        log("ERROR: cannot connect to PostgreSQL. Check the PG* variables in Environment.")
        log(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "no error output")
        sys.exit(1)
    return out.stdout.strip() == "yes"


def init_db(db):
    lang = os.environ.get("ODOO_LANG", "vi_VN")
    log(f"Initializing database {db} (base + {lang}), this takes a few minutes...")
    subprocess.run([VPY, "-m", "odoo", "-c", CONF, "-d", db, "-i", "base",
                    "--load-language", lang, "--stop-after-init"],
                   cwd=SRC, env=odoo_env(), check=True)
    password = os.environ.get("ODOO_ADMIN_PASSWORD", "").strip()
    pw_file = os.path.join(HOME, "ODOO_ADMIN_PASSWORD.txt")
    if not password:
        password = secrets.token_urlsafe(12)
        with open(pw_file, "w") as fh:
            fh.write(f"login: admin\npassword: {password}\n")
        os.chmod(pw_file, 0o600)
    script = ("import os\n"
              "u = env.ref('base.user_admin')\n"
              "u.write({'password': os.environ['ODOO_NEW_ADMIN_PW'], 'lang': os.environ['ODOO_NEW_LANG']})\n"
              "env.cr.commit()\n")
    env = odoo_env()
    env["ODOO_NEW_ADMIN_PW"] = password
    env["ODOO_NEW_LANG"] = lang
    subprocess.run([VPY, "-m", "odoo", "shell", "-c", CONF, "-d", db, "--no-http"],
                   input=script, text=True, cwd=SRC, env=env, check=True)
    if os.environ.get("ODOO_ADMIN_PASSWORD", "").strip():
        log("Admin password set from ODOO_ADMIN_PASSWORD (login: admin)")
    else:
        log("Admin password generated: open Files > ODOO_ADMIN_PASSWORD.txt (login: admin)")


# ---------------------------------------------------------------- main
def main():
    load_dotenv()
    missing = [v for v in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE") if not os.environ.get(v)]
    if missing:
        log("ERROR: missing environment variables: " + ", ".join(missing))
        log("Add them in Botkeep > Environment (values from the PostgreSQL server's Database tab).")
        sys.exit(1)
    db = os.environ["PGDATABASE"]
    use_local_pg = not choose_pg_host()
    if use_local_pg:
        log("The PostgreSQL server in PGHOST is not reachable from this container; using a local one")

    if not os.path.isfile(os.path.join(SRC, "odoo", "release.py")):
        download_source()
        if os.path.exists(STATE):
            os.remove(STATE)
    if not os.path.exists(STATE):
        install_deps()
        open(STATE, "w").close()

    pot_marker = os.path.join(HOME, ".odoo_pot")
    if not os.path.exists(pot_marker):
        download_pot_files()
        open(pot_marker, "w").close()

    os.makedirs(DATA, exist_ok=True)
    write_conf(db)
    if use_local_pg:
        start_local_postgres()
    if not db_initialized():
        init_db(db)
    # web.assets_frontend (login page) calls increase-contrast(), defined by html_editor
    marker = os.path.join(HOME, ".odoo_html_editor")
    if not os.path.exists(marker):
        log("Installing module html_editor (needed by the login page styles)...")
        subprocess.run([VPY, "-m", "odoo", "-c", CONF, "-d", db, "-i", "html_editor", "--stop-after-init"],
                       cwd=SRC, env=odoo_env(), check=True)
        open(marker, "w").close()

    log(f"Disk: source {disk_usage(SRC)} MB, venv {disk_usage(VENV)} MB, "
        f"data {disk_usage(DATA)} MB, pgdata {disk_usage(PG_DATA)} MB")
    log("Starting Odoo...")
    os.chdir(SRC)
    os.execve(VPY, [VPY, "-m", "odoo", "-c", CONF], odoo_env())


if __name__ == "__main__":
    main()
