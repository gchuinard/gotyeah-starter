"""Client Nginx Proxy Manager (API port 81) : auth JWT, certificat Let's Encrypt, proxy host."""
from __future__ import annotations

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
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=120.0)

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

    async def request_certificate(self, domain: str, le_email: str) -> int:
        """Demande un certificat Let's Encrypt (challenge HTTP). Renvoie l'id."""
        resp = await self._client.post(
            "/api/nginx/certificates",
            json={
                "domain_names": [domain],
                "provider": "letsencrypt",
                "meta": {
                    "letsencrypt_email": le_email,
                    "letsencrypt_agree": True,
                    "dns_challenge": False,
                },
            },
        )
        data = await self._check(resp, "Demande de certificat Let's Encrypt")
        return int(data["id"])

    async def create_proxy_host(
        self,
        domain: str,
        forward_host: str,
        forward_port: int,
        forward_scheme: str,
        certificate_id: int,
    ) -> int:
        resp = await self._client.post(
            "/api/nginx/proxy-hosts",
            json={
                "domain_names": [domain],
                "forward_scheme": forward_scheme,
                "forward_host": forward_host,
                "forward_port": forward_port,
                "certificate_id": certificate_id,
                "ssl_forced": True,
                "http2_support": True,
                "hsts_enabled": True,
                "block_exploits": True,
                "allow_websocket_upgrade": True,
                "caching_enabled": False,
                "access_list_id": 0,
                "advanced_config": "",
                "locations": [],
                "meta": {"letsencrypt_agree": True, "dns_challenge": False},
            },
        )
        data = await self._check(resp, "Création du proxy host")
        return int(data["id"])

    async def delete_proxy_host(self, host_id: int) -> None:
        resp = await self._client.delete(f"/api/nginx/proxy-hosts/{host_id}")
        if resp.status_code not in (200, 404):
            raise NPMError(f"Suppression proxy host a échoué ({resp.status_code}): {resp.text}")

    async def delete_certificate(self, cert_id: int) -> None:
        resp = await self._client.delete(f"/api/nginx/certificates/{cert_id}")
        if resp.status_code not in (200, 404):
            raise NPMError(f"Suppression certificat a échoué ({resp.status_code}): {resp.text}")
