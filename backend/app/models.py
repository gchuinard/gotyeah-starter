"""Schémas Pydantic des requêtes/réponses et événements de log."""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_DOMAIN_RE = re.compile(r"(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,}")
# Nom d'hôte/conteneur Docker résoluble sur le réseau NPM.
_HOST_RE = re.compile(r"[a-zA-Z0-9]([a-zA-Z0-9_.-]{0,61}[a-zA-Z0-9])?")


class SiteType(str, Enum):
    nextjs = "nextjs"
    static = "static"
    other = "other"


class Endpoint(BaseModel):
    """Un domaine exposé via NPM, forwardé vers un conteneur:port."""
    domain: str = Field(..., description="FQDN, ex: mon-site.gautierchuinard.com")
    container: str = Field(..., description="Nom du conteneur cible (forward host)")
    port: int = Field(..., ge=1, le=65535, description="Port du conteneur")

    @field_validator("domain")
    @classmethod
    def _valid_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not _DOMAIN_RE.fullmatch(v):
            raise ValueError(f"Domaine invalide : {v}")
        return v

    @field_validator("container")
    @classmethod
    def _valid_container(cls, v: str) -> str:
        v = v.strip()
        if not _HOST_RE.fullmatch(v):
            raise ValueError(f"Nom de conteneur invalide : {v}")
        return v


class ProvisionRequest(BaseModel):
    repo_name: str = Field(..., description="Nom du repo GitHub à créer")
    site_type: SiteType
    private: bool = True
    frontend: Endpoint
    backend: Endpoint | None = None

    @field_validator("repo_name")
    @classmethod
    def _valid_repo(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", v):
            raise ValueError("Nom de repo invalide (alphanum, '.', '_', '-')")
        return v

    @property
    def endpoints(self) -> list[tuple[str, Endpoint]]:
        """Liste ordonnée (libellé, endpoint) — frontend puis backend si présent."""
        eps = [("frontend", self.frontend)]
        if self.backend is not None:
            eps.append(("backend", self.backend))
        return eps


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
