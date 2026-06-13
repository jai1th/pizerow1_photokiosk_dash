import hashlib
import logging
import sys


def configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Enable waitress HTTP access log
    logging.getLogger("waitress.access").setLevel(logging.INFO)


def sha256_fileobj(f) -> str:
    """Return first 32 hex chars of SHA-256, reading in 64 KB chunks."""
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(65536), b""):
        h.update(chunk)
    return h.hexdigest()[:32]
