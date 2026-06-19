"""Schémas Pydantic des requêtes/réponses et événements de log."""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SiteType(str, Enum):
    nextjs = "nextjs"
    static = "static"
    other = "other"


class ProvisionRequest(BaseModel):
    domain: str = Field(..., description="Nom de domaine complet, ex: app.exemple.com")
    site_type: SiteType
    target_port: int = Field(..., ge=1, le=65535, description="Port local cible sur le Pi")
    repo_name: str = Field(..., description="Nom du repo GitHub à créer")
    private: bool = True

    @field_validator("domain")
    @classmethod
    def _valid_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,}", v):
            raise ValueError("Domaine invalide")
        return v

    @field_validator("repo_name")
    @classmethod
    def _valid_repo(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", v):
            raise ValueError("Nom de repo invalide (alphanum, '.', '_', '-')")
        return v


class ProvisionStarted(BaseModel):
    job_id: str


LogLevel = Literal["info", "success", "warning", "error", "step"]


class LogEvent(BaseModel):
    """Un message poussé vers le frontend via SSE."""
    job_id: str
    level: LogLevel = "info"
    step: str | None = None
    message: str
    data: dict[str, Any] | None = None
    done: bool = False
    ok: bool | None = None  # résultat final quand done=True
