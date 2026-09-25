#!/usr/bin/env python3
"""Start everything: database, background scanner, dashboard.

    python run.py            → http://localhost:3000
    python run.py --no-scan  → dashboard only (no automatic scanning)
"""
import os
import sys

import uvicorn

from app import config, db
from app.logging_setup import setup
from app.scheduler import Scanner
from app.web.server import create_app


def main():
    config.load_dotenv()
    log = setup()
    conn = db.connect()
    scanner = None if "--no-scan" in sys.argv else Scanner(conn)
    if scanner:
        scanner.start()
    port = int(os.environ.get("PORT", 3000))
    log.info(f"Apartment Hunter → http://localhost:{port}")
    uvicorn.run(create_app(conn, scanner), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
