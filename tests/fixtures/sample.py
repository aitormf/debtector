"""
Módulo de ejemplo para testing del parser.
Simula un servicio de usuarios típico.
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import Flask

from .database import Database


@dataclass
class User:
    """Modelo de datos de usuario."""

    id: int
    name: str
    email: str
    active: bool = True


class UserService:
    """Servicio para gestionar usuarios."""

    def __init__(self, db: Database):
        """Inicializa el servicio con una conexión a la base de datos."""
        self.db = db

    def get_user(self, user_id: int) -> User | None:
        """Obtiene un usuario por su ID."""
        data = self.db.find_one("users", {"id": user_id})
        if data:
            return User(**data)
        return None

    def create_user(self, name: str, email: str) -> User:
        """Crea un nuevo usuario."""
        user_data = {"name": name, "email": email, "active": True}
        result = self.db.insert("users", user_data)
        return User(id=result["id"], **user_data)

    @staticmethod
    def validate_email(email: str) -> bool:
        """Valida el formato del email."""
        return "@" in email and "." in email.split("@")[1]


class AdminService(UserService):
    """Servicio extendido con permisos de administrador."""

    def deactivate_user(self, user_id: int) -> bool:
        """Desactiva un usuario."""
        return self.db.update("users", {"id": user_id}, {"active": False})


def create_app(config: dict | None = None) -> Flask:
    """Factory function para crear la aplicación Flask."""
    app = Flask(__name__)
    if config:
        app.config.update(config)
    return app


def health_check() -> dict:
    """Endpoint de health check."""
    return {"status": "ok", "version": "1.0"}
