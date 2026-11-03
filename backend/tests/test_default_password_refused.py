"""In production the users API refuses the published default passwords (D22 incident, 03-Nov-2026):
an account set back to Pass@100% made the API refuse to start after the next restart."""
import pytest

from app.config import config
from app.errors import AppError
from app.routes.admin import users


def test_default_password_refused_in_production(monkeypatch):
    monkeypatch.setattr(config, "env", "production", raising=False)
    for pw in ("Pass@100%", "ChangeMe@123"):
        with pytest.raises(AppError, match="default password"):
            users._refuse_default_password(pw)
    users._refuse_default_password("Karnex#Strong2026!")  # any other password is fine


def test_default_password_allowed_outside_production(monkeypatch):
    monkeypatch.setattr(config, "env", "development", raising=False)
    users._refuse_default_password("Pass@100%")  # demo / local use keeps working
