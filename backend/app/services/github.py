"""Client GitHub : création de repo (depuis template ou vierge) et injection de fichiers."""
from __future__ import annotations

import asyncio
import base64

import httpx2

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, owner: str) -> None:
        if not token or not owner:
            raise GitHubError("GITHUB_TOKEN / GITHUB_OWNER manquants")
        self.owner = owner
        self._client = httpx2.AsyncClient(
            base_url=API,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _check(self, resp: httpx2.Response, action: str) -> dict:
        if resp.status_code >= 300:
            raise GitHubError(f"{action} a échoué ({resp.status_code}): {resp.text}")
        return resp.json() if resp.content else {}

    async def create_repo(self, name: str, template: str | None, private: bool) -> dict:
        """Crée le repo depuis un template `owner/repo` si fourni, sinon un repo vierge."""
        if template:
            t_owner, _, t_repo = template.partition("/")
            resp = await self._client.post(
                f"/repos/{t_owner}/{t_repo}/generate",
                json={"owner": self.owner, "name": name, "private": private},
            )
            return await self._check(resp, f"Génération depuis le template {template}")
        # Repo vierge — on tente d'abord en tant qu'organisation, fallback user.
        resp = await self._client.post(
            f"/orgs/{self.owner}/repos",
            json={"name": name, "private": private, "auto_init": True},
        )
        if resp.status_code == 404:
            resp = await self._client.post(
                "/user/repos",
                json={"name": name, "private": private, "auto_init": True},
            )
        return await self._check(resp, "Création du repo")

    async def put_file(self, repo: str, path: str, content: str, message: str) -> dict:
        """Crée/écrase un fichier via l'API contents (base64).

        Juste après création d'un repo (auto_init), la branche par défaut peut ne pas
        être encore disponible → l'API contents renvoie 404 fugacement. On réessaie.
        """
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        delays = (0, 2, 4, 6)
        last: httpx2.Response | None = None
        for delay in delays:
            if delay:
                await asyncio.sleep(delay)
            # Si le fichier existe déjà (template), il faut son sha pour le mettre à jour.
            sha: str | None = None
            head = await self._client.get(f"/repos/{self.owner}/{repo}/contents/{path}")
            if head.status_code == 200:
                sha = head.json().get("sha")
            body = {"message": message, "content": b64}
            if sha:
                body["sha"] = sha
            resp = await self._client.put(f"/repos/{self.owner}/{repo}/contents/{path}", json=body)
            if resp.status_code < 300:
                return resp.json() if resp.content else {}
            last = resp
            if resp.status_code != 404:  # 404 = repo pas encore prêt → on retente
                break
        return await self._check(last, f"Injection de {path}")  # lève l'erreur finale

    async def delete_repo(self, repo: str) -> None:
        """Rollback : supprime le repo (nécessite le scope delete_repo)."""
        resp = await self._client.delete(f"/repos/{self.owner}/{repo}")
        if resp.status_code not in (204, 404):
            raise GitHubError(f"Suppression du repo a échoué ({resp.status_code}): {resp.text}")
