import os
import secrets
import time
from datetime import timedelta

from flask import Flask, flash, redirect, request, session, url_for

from .db import init_engine
from .routes import bp


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not app.secret_key:
        raise RuntimeError("FLASK_SECRET_KEYを環境変数に設定してください。")
    timeout_minutes = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=timeout_minutes),
        SESSION_REFRESH_EACH_REQUEST=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
        SESSION_TIMEOUT_SECONDS=timeout_minutes * 60,
        SESSION_STARTUP_ID=secrets.token_urlsafe(32),
    )
    init_engine()
    app.register_blueprint(bp)

    @app.before_request
    def validate_session():
        if request.endpoint in {"static", "main.login", "main.healthz"}:
            return None
        if "employee_id" not in session:
            return None

        if session.get("_startup_id") != app.config["SESSION_STARTUP_ID"]:
            session.clear()
            flash("アプリケーションが再起動されたため、再度ログインしてください。")
            return redirect(url_for("main.login"))

        now = int(time.time())
        last_activity = session.get("_last_activity", now)
        if now - last_activity >= app.config["SESSION_TIMEOUT_SECONDS"]:
            session.clear()
            flash("一定時間操作がなかったため、自動的にログアウトしました。")
            return redirect(url_for("main.login"))

        session["_last_activity"] = now
        session.modified = True
        return None

    return app
