"""Client Nginx Proxy Manager (API port 81) : auth JWT + proxy host avec cert Let's Encrypt.

Note : sur certaines versions de NPM, POST /api/nginx/certificates échoue (validation de
schéma renvoyée en « Permission Denied »). La voie fiable, utilisée ici, reproduit l'UI :
créer le proxy host sans SSL, puis le mettre à jour avec certificate_id="new" pour que NPM
émette le certificat et l'attache. On laisse advanced_config vide (le SSE est géré par la
conf custom globale de NPM).
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import httpx


class NPMError(RuntimeError):
    pass


class NPMClient:
    def __init__(self, base_url: str, email: str, password: str) -> None:
        if not email or not password:
            raise NPMError("NPM_EMAIL / NPM_PASSWORD manquants")
        self._email = email
        self._password = password
        # La demande de cert Let's Encrypt peut être longue.
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=180.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _check(self, resp: httpx.Response, action: str) -> dict:
        if resp.status_code >= 300:
            raise NPMError(f"{action} a échoué ({resp.status_code}): {resp.text}")
        return resp.json() if resp.content else {}

    async def login(self) -> None:
        resp = await self._client.post(
            "/api/tokens", json={"identity": self._email, "secret": self._password}
        )
        data = await self._check(resp, "Authentification NPM")
        token = data.get("token")
        if not token:
            raise NPMError("NPM n'a pas renvoyé de token")
        self._client.headers["Authorization"] = f"Bearer {token}"

    def _proxy_payload(self, domain: str, forward_host: str, forward_port: int, forward_scheme: str) -> dict:
        return {
            "domain_names": [domain],
            "forward_scheme": forward_scheme,
            "forward_host": forward_host,
            "forward_port": forward_port,
            "block_exploits": True,
            "allow_websocket_upgrade": True,
            "caching_enabled": False,
            "http2_support": True,
            "hsts_enabled": True,
            "hsts_subdomains": False,
            "access_list_id": 0,
            # Vide volontairement : la conf custom globale gère déjà le buffering/SSE.
            "advanced_config": "",
            "locations": [],
        }

    # Délais (s) avant chaque tentative d'émission du cert. Le 1er est immédiat ;
    # les suivants laissent le temps à Cloudflare d'activer un record fraîchement créé.
    _CERT_RETRY_DELAYS = (0, 12, 20)

    async def create_proxy_host_with_cert(
        self,
        domain: str,
        forward_host: str,
        forward_port: int,
        forward_scheme: str,
        le_email: str,
        on_log: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[int, int]:
        """Crée le proxy host puis fait émettre un cert Let's Encrypt. Renvoie (host_id, cert_id).

        Atomique : si l'émission du cert échoue après tous les essais, le host créé est
        supprimé avant de propager l'erreur (pas de host orphelin).
        """
        # 1) host sans SSL
        body = self._proxy_payload(domain, forward_host, forward_port, forward_scheme)
        body |= {"certificate_id": 0, "ssl_forced": False,
                 "meta": {"letsencrypt_agree": False, "dns_challenge": False}}
        resp = await self._client.post("/api/nginx/proxy-hosts", json=body)
        host = await self._check(resp, f"Création du proxy host {domain}")
        host_id = int(host["id"])

        # 2) demande du certificat via mise à jour (certificate_id="new"), avec retries
        upd = self._proxy_payload(domain, forward_host, forward_port, forward_scheme)
        upd |= {
            "certificate_id": "new",
            "ssl_forced": True,
            "meta": {"letsencrypt_email": le_email, "letsencrypt_agree": True, "dns_challenge": False},
        }
        last_err: Exception | None = None
        for attempt, delay in enumerate(self._CERT_RETRY_DELAYS, start=1):
            if delay:
                if on_log:
                    await on_log(f"… cert {domain} : nouvel essai dans {delay}s (essai {attempt})")
                await asyncio.sleep(delay)
            try:
                resp = await self._client.put(f"/api/nginx/proxy-hosts/{host_id}", json=upd)
                data = await self._check(resp, f"Émission du certificat pour {domain}")
                meta = data.get("meta") or {}
                if meta.get("nginx_online") is False:
                    raise NPMError(f"NGINX a rejeté la conf de {domain} : {meta.get('nginx_err')}")
                return host_id, int(data.get("certificate_id") or 0)
            except NPMError as exc:
                last_err = exc

        # tous les essais ont échoué : on retire le host pour ne rien laisser traîner
        try:
            await self.delete_proxy_host(host_id)
        except Exception:  # noqa: BLE001
            pass
        raise NPMError(f"Émission du certificat pour {domain} échouée après "
                       f"{len(self._CERT_RETRY_DELAYS)} essais : {last_err}")

    async def delete_proxy_host(self, host_id: int) -> None:
        resp = await self._client.delete(f"/api/nginx/proxy-hosts/{host_id}")
        if resp.status_code not in (200, 404):
            raise NPMError(f"Suppression proxy host a échoué ({resp.status_code}): {resp.text}")

    async def delete_certificate(self, cert_id: int) -> None:
        if not cert_id:
            return
        resp = await self._client.delete(f"/api/nginx/certificates/{cert_id}")
        if resp.status_code not in (200, 404):
            raise NPMError(f"Suppression certificat a échoué ({resp.status_code}): {resp.text}")
