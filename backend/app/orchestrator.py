"""Orchestration en cascade avec rollback compensatoire.

Pour chaque endpoint (frontend, puis backend si présent) : record DNS Cloudflare +
proxy host NPM avec certificat Let's Encrypt. En cas d'échec, les compensations sont
rejouées dans l'ordre inverse.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from .config import settings
from .events import bus
from .models import Endpoint, LogEvent, ProvisionRequest
from .services.cloudflare import CloudflareClient
from .services.github import GitHubClient
from .services.npm import NPMClient
from .workflows import render_deploy_workflow


class Orchestrator:
    def __init__(self, job_id: str, req: ProvisionRequest) -> None:
        self.job_id = job_id
        self.req = req
        self._undos: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        # (label endpoint, record_id) pour le re-proxy final éventuel.
        self._dns_records: list[tuple[str, str]] = []

    async def _log(self, message: str, level: str = "info", step: str | None = None, **data) -> None:
        await bus.publish(
            LogEvent(job_id=self.job_id, level=level, step=step, message=message, data=data or None)
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
                    message=f"✅ {self.req.frontend.domain} provisionné avec succès.",
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
            f"Repo créé : {repo.get('html_url', self.req.repo_name)}", level="success", step=step
        )

    async def _step_cloudflare(self, cf: CloudflareClient) -> None:
        step = "cloudflare"
        if not settings.pi_public_ip:
            raise RuntimeError("PI_PUBLIC_IP non configurée")
        create_proxied = settings.cloudflare_proxied and not settings.cloudflare_dns_only_during_ssl
        mode = "proxied" if create_proxied else "DNS-only"
        for label, ep in self.req.endpoints:
            await self._log(
                f"[{label}] record A {ep.domain} → {settings.pi_public_ip} ({mode})…",
                level="step", step=step,
            )
            record = await cf.create_a_record(ep.domain, settings.pi_public_ip, create_proxied)
            rec_id = record["id"]
            self._dns_records.append((label, rec_id))
            self._register_undo(f"record DNS {ep.domain}", lambda rid=rec_id: cf.delete_record(rid))
            await self._log(f"[{label}] record créé (id={rec_id}).", level="success", step=step)

    async def _step_npm(self, npm: NPMClient) -> None:
        step = "npm"
        await self._log("Authentification sur Nginx Proxy Manager…", level="step", step=step)
        await npm.login()
        le_email = settings.letsencrypt_email or settings.npm_email
        for label, ep in self.req.endpoints:
            await self._log(
                f"[{label}] proxy host {ep.domain} → {ep.container}:{ep.port} + cert Let's Encrypt…",
                level="step", step=step,
            )
            host_id, cert_id = await npm.create_proxy_host_with_cert(
                ep.domain, ep.container, ep.port, settings.npm_forward_scheme, le_email
            )
            self._register_undo(f"proxy host NPM #{host_id} ({ep.domain})",
                                lambda hid=host_id: npm.delete_proxy_host(hid))
            self._register_undo(f"certificat NPM #{cert_id} ({ep.domain})",
                                lambda cid=cert_id: npm.delete_certificate(cid))
            await self._log(
                f"[{label}] proxy host #{host_id} créé, SSL forcé (cert #{cert_id}).",
                level="success", step=step,
            )

    async def _step_inject_workflow(self, gh: GitHubClient) -> None:
        step = "workflow"
        await self._log("Injection de .github/workflows/deploy.yml…", level="step", step=step)
        content = render_deploy_workflow(self.req)
        await gh.put_file(
            self.req.repo_name, ".github/workflows/deploy.yml", content,
            "ci: add deploy workflow (gotyeah-starter)",
        )
        await self._log("Workflow CI/CD injecté.", level="success", step=step)

    async def _step_reproxy(self, cf: CloudflareClient) -> None:
        step = "cloudflare"
        if not (settings.cloudflare_proxied and settings.cloudflare_dns_only_during_ssl):
            return
        for label, ep in self.req.endpoints:
            rec_id = next((r for lbl, r in self._dns_records if lbl == label), None)
            if not rec_id:
                continue
            await self._log(f"[{label}] bascule {ep.domain} en proxied (orange cloud)…",
                            level="step", step=step)
            await cf.set_proxied(ep.domain, rec_id, True)
            await self._log(f"[{label}] record repassé en proxied.", level="success", step=step)
