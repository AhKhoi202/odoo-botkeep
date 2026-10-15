# odoo-botkeep

Launcher for Odoo 20.0 Community on a Botkeep Python 3.12 server.

- start.py: startup file. On first run it downloads the Odoo source, installs the Python requirements, starts PostgreSQL inside the container when the server in PGHOST cannot be reached, initializes the database (base + vi_VN), then runs Odoo on $SERVER_PORT.
- pgshim.c: source of the small LD_PRELOAD library embedded in start.py. It gives the container uid a passwd entry so initdb can run.

Botkeep setup: GitHub tab → Public repository → this repo, branch main, import mode **Merge files**, enable **Pull before Start / Restart**.
Environment: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE (optional ODOO_ADMIN_PASSWORD, ODOO_LANG).
