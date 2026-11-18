"""Server-only Supabase persistence for the application workspace state."""
import json
import os

import requests


class SupabaseStoreError(RuntimeError):
    pass


class SupabaseStore:
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self.key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
        self.token = os.environ.get("IA_DATABASE_TOKEN", "")
        self.workspace = os.environ.get("IA_WORKSPACE_KEY", "default")
        missing = [name for name, value in (
            ("SUPABASE_URL", self.url),
            ("SUPABASE_PUBLISHABLE_KEY", self.key),
            ("IA_DATABASE_TOKEN", self.token),
        ) if not value]
        if missing:
            raise SupabaseStoreError("Missing server environment variables: " + ", ".join(missing))

    def _headers(self, write=False):
        headers = {
            "apikey": self.key,
            "Authorization": "Bearer " + self.key,
            "X-IA-Token": self.token,
            "Content-Type": "application/json",
        }
        if write:
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        return headers

    def read(self, default_factory):
        try:
            response = requests.get(
                self.url + "/rest/v1/ia_workspace_state",
                params={"workspace_key": "eq." + self.workspace, "select": "data"},
                headers=self._headers(), timeout=(10, 30),
            )
            response.raise_for_status()
            rows = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SupabaseStoreError("Supabase read failed.") from exc
        if not rows:
            return default_factory()
        data = rows[0].get("data")
        if not isinstance(data, dict):
            raise SupabaseStoreError("Supabase workspace data is not a JSON object.")
        return data

    def write(self, data):
        if not isinstance(data, dict):
            raise SupabaseStoreError("Workspace data must be a JSON object.")
        payload = {"workspace_key": self.workspace, "data": data}
        try:
            response = requests.post(
                self.url + "/rest/v1/ia_workspace_state",
                params={"on_conflict": "workspace_key"},
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers=self._headers(write=True), timeout=(10, 60),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SupabaseStoreError("Supabase write failed.") from exc
