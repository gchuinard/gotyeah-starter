"""Client Cloudflare : résolution de zone + gestion du record DNS A."""
from __future__ import annotations

import httpx

API = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    pass


class CloudflareClient:
    def __init__(self, token: str, zone_id: str = "") -> None:
        if not token:
            raise CloudflareError("CLOUDFLARE_TOKEN manquant")
        self._zone_id = zone_id
        self._client = httpx.AsyncClient(
            base_url=API,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _result(self, resp: httpx.Response, action: str):
        data = resp.json() if resp.content else {}
        if resp.status_code >= 300 or not data.get("success", False):
            errs = data.get("errors") if isinstance(data, dict) else resp.text
            raise CloudflareError(f"{action} a échoué ({resp.status_code}): {errs}")
        return data["result"]

    async def resolve_zone_id(self, domain: str) -> str:
        """Trouve la zone qui couvre `domain` en testant les suffixes successifs."""
        if self._zone_id:
            return self._zone_id
        labels = domain.split(".")
        # On part du suffixe le plus long (ex: a.b.exemple.com -> b.exemple.com -> exemple.com)
        for i in range(len(labels) - 1):
            candidate = ".".join(labels[i:])
            resp = await self._client.get("/zones", params={"name": candidate})
            result = await self._result(resp, "Recherche de zone")
            if result:
                self._zone_id = result[0]["id"]
                return self._zone_id
        raise CloudflareError(f"Aucune zone Cloudflare ne correspond à {domain}")

    async def create_a_record(self, domain: str, ip: str, proxied: bool) -> dict:
        zone_id = await self.resolve_zone_id(domain)
        resp = await self._client.post(
            f"/zones/{zone_id}/dns_records",
            json={"type": "A", "name": domain, "content": ip, "ttl": 1, "proxied": proxied},
        )
        return await self._result(resp, "Création du record DNS A")

    async def set_proxied(self, domain: str, record_id: str, proxied: bool) -> None:
        """Bascule le statut proxied d'un record A existant (gray ↔ orange cloud)."""
        zone_id = await self.resolve_zone_id(domain)
        resp = await self._client.patch(
            f"/zones/{zone_id}/dns_records/{record_id}",
            json={"proxied": proxied},
        )
        await self._result(resp, "Mise à jour du statut proxied")

    async def delete_record(self, record_id: str) -> None:
        """Rollback : supprime le record DNS."""
        if not self._zone_id:
            return
        resp = await self._client.delete(f"/zones/{self._zone_id}/dns_records/{record_id}")
        if resp.status_code not in (200, 404):
            raise CloudflareError(f"Suppression DNS a échoué ({resp.status_code}): {resp.text}")
