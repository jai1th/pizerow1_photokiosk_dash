from flask import Blueprint, render_template
import config

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def slideshow():
    return render_template(
        "slideshow.html",
        slide_seconds=config.SLIDE_SECONDS,
        fade_ms=config.FADE_MS,
    )


@pages_bp.route("/upload")
def upload():
    return render_template("upload.html")
