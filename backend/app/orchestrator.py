"""Orchestration en cascade des 4 étapes avec rollback compensatoire.

Chaque étape exécutée enregistre une action de compensation (undo). En cas d'échec,
on rejoue les compensations dans l'ordre inverse pour laisser le système propre.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from .config import settings
from .events import bus
from .models import LogEvent, ProvisionRequest
from .services.cloudflare import CloudflareClient
from .services.github import GitHubClient
from .services.npm import NPMClient
from .workflows import render_deploy_workflow


class Orchestrator:
    def __init__(self, job_id: str, req: ProvisionRequest) -> None:
        self.job_id = job_id
        self.req = req
        self._undos: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self._dns_record_id: str | None = None

    async def _log(self, message: str, level: str = "info", step: str | None = None, **data) -> None:
        await bus.publish(
            LogEvent(
                job_id=self.job_id, level=level, step=step, message=message,
                data=data or None,
            )
        )

    def _register_undo(self, label: str, fn: Callable[[], Awaitable[None]]) -> None:
        self._undos.append((label, fn))

    async def _rollback(self) -> None:
        if not self._undos:
            return
        await self._log("Rollback : annulation des étapes déjà effectuées…", level="warning")
        for label, fn in reversed(self._undos):
            try:
                await fn()
                await self._log(f"↩︎ Annulé : {label}", level="warning")
            except Exception as exc:  # noqa: BLE001
                await self._log(f"⚠︎ Rollback partiel — {label} : {exc}", level="error")

    async def run(self) -> None:
        gh = cf = npm = None
        try:
            gh = GitHubClient(settings.github_token, settings.github_owner)
            cf = CloudflareClient(settings.cloudflare_token, settings.cloudflare_zone_id)
            npm = NPMClient(settings.npm_base_url, settings.npm_email, settings.npm_password)

            await self._step_github(gh)
            await self._step_cloudflare(cf)
            await self._step_npm(npm)
            await self._step_inject_workflow(gh)
            await self._step_reproxy(cf)

            await bus.publish(
                LogEvent(
                    job_id=self.job_id, level="success",
                    message=f"✅ Site {self.req.domain} provisionné avec succès.",
                    done=True, ok=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            await self._log(f"Échec : {exc}", level="error")
            await self._rollback()
            await bus.publish(
                LogEvent(
                    job_id=self.job_id, level="error",
                    message="❌ Provisionnement interrompu, rollback effectué.",
                    done=True, ok=False,
                )
            )
        finally:
            for c in (gh, cf, npm):
                if c is not None:
                    try:
                        await c.aclose()
                    except Exception:  # noqa: BLE001
                        pass

    # --- Étapes ---------------------------------------------------------------

    async def _step_github(self, gh: GitHubClient) -> None:
        step = "github"
        template = settings.template_for.get(self.req.site_type.value) or None
        src = f"template {template}" if template else "repo vierge"
        await self._log(f"Création du repo « {self.req.repo_name} » ({src})…", level="step", step=step)
        repo = await gh.create_repo(self.req.repo_name, template, self.req.private)
        self._register_undo(
            f"repo GitHub {settings.github_owner}/{self.req.repo_name}",
            lambda: gh.delete_repo(self.req.repo_name),
        )
        await self._log(
            f"Repo créé : {repo.get('html_url', self.req.repo_name)}",
            level="success", step=step,
        )

    async def _step_cloudflare(self, cf: CloudflareClient) -> None:
        step = "cloudflare"
        if not settings.pi_public_ip:
            raise RuntimeError("PI_PUBLIC_IP non configurée")
        # DNS-only pendant l'émission du cert si demandé, sinon directement l'état final.
        create_proxied = settings.cloudflare_proxied and not settings.cloudflare_dns_only_during_ssl
        mode = "proxied" if create_proxied else "DNS-only"
        await self._log(
            f"Ajout du record A {self.req.domain} → {settings.pi_public_ip} ({mode})…",
            level="step", step=step,
        )
        record = await cf.create_a_record(
            self.req.domain, settings.pi_public_ip, create_proxied
        )
        rec_id = record["id"]
        self._dns_record_id = rec_id
        self._register_undo(
            f"record DNS {self.req.domain}", lambda: cf.delete_record(rec_id)
        )
        await self._log(f"Record DNS créé (id={rec_id}, {mode}).", level="success", step=step)

    async def _step_npm(self, npm: NPMClient) -> None:
        step = "npm"
        await self._log("Authentification sur Nginx Proxy Manager…", level="step", step=step)
        await npm.login()

        await self._log(
            f"Demande du certificat Let's Encrypt pour {self.req.domain} (peut prendre ~30s)…",
            level="step", step=step,
        )
        cert_id = await npm.request_certificate(
            self.req.domain, settings.letsencrypt_email or settings.npm_email
        )
        self._register_undo(f"certificat NPM #{cert_id}", lambda: npm.delete_certificate(cert_id))
        await self._log(f"Certificat émis (id={cert_id}).", level="success", step=step)

        await self._log(
            f"Création du proxy host → {settings.forward_host}:{self.req.target_port}…",
            level="step", step=step,
        )
        host_id = await npm.create_proxy_host(
            self.req.domain,
            settings.forward_host,
            self.req.target_port,
            settings.npm_forward_scheme,
            cert_id,
        )
        self._register_undo(f"proxy host NPM #{host_id}", lambda: npm.delete_proxy_host(host_id))
        await self._log(
            f"Proxy host créé (id={host_id}) avec SSL forcé.", level="success", step=step
        )

    async def _step_inject_workflow(self, gh: GitHubClient) -> None:
        step = "workflow"
        await self._log("Injection de .github/workflows/deploy.yml…", level="step", step=step)
        content = render_deploy_workflow(
            self.req.site_type, self.req.domain, self.req.target_port, self.req.repo_name
        )
        await gh.put_file(
            self.req.repo_name,
            ".github/workflows/deploy.yml",
            content,
            "ci: add deploy workflow (gotyeah-starter)",
        )
        # Pas d'undo dédié : le rollback du repo entier suffit.
        await self._log("Workflow CI/CD injecté.", level="success", step=step)

    async def _step_reproxy(self, cf: CloudflareClient) -> None:
        step = "cloudflare"
        # Rien à faire si on ne veut pas de proxy final, ou si le record a déjà été
        # créé directement en proxied.
        if not (settings.cloudflare_proxied and settings.cloudflare_dns_only_during_ssl):
            return
        if not self._dns_record_id:
            return
        await self._log(
            f"NPM OK → bascule du record {self.req.domain} en proxied (orange cloud)…",
            level="step", step=step,
        )
        await cf.set_proxied(self.req.domain, self._dns_record_id, True)
        await self._log("Record repassé en proxied.", level="success", step=step)
