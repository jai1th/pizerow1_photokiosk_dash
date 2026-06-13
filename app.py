import logging
from pathlib import Path

from flask import Flask
from waitress import serve

import config
from piframe.util import configure_logging
from piframe.routes_pages import pages_bp
from piframe.routes_api import api_bp
from piframe import photos


def create_app() -> Flask:
    _ensure_dirs()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)
    return app


def _ensure_dirs() -> None:
    for d in (config.ORIGINALS_DIR, config.DISPLAY_DIR, config.CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    configure_logging()
    log = logging.getLogger(__name__)
    _ensure_dirs()
    photos.start_repair_scan()
    app = create_app()
    log.info("PiFrame starting on port %d", config.PORT)
    serve(app, host="0.0.0.0", port=config.PORT, threads=config.WSGI_THREADS)
