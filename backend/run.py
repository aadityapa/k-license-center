"""
Starts the Karnex License API.

    python run.py            serve on PORT from backend/.env (default 3001)
    python run.py --reload   development: restart when a .py file changes
"""
from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.config import config

    reload = "--reload" in sys.argv
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=config.port,
        reload=reload,
        reload_dirs=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")] if reload else None,
        server_header=False,
        proxy_headers=False,  # the API reads X-Forwarded-For itself (one trusted hop)
        log_level="warning",
        timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    main()
