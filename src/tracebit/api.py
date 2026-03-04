import requests

from .config import get_base_url


class TracebitError(Exception):
    pass


class TracebitClient:
    def __init__(self, token, base_url=None):
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Content-Type"] = "application/json"

    def _url(self, path):
        return f"{self.base_url}/api/v1/credentials/{path}"

    def _check(self, resp, context="API request"):
        if resp.status_code == 401:
            raise TracebitError(
                "Authentication failed (401). Check your API token."
            )
        if resp.status_code == 400:
            raise TracebitError(f"{context} failed: {resp.text}")
        resp.raise_for_status()

    def generate_metadata(self):
        resp = self.session.get(self._url("generate-metadata"))
        self._check(resp, "Generate metadata")
        return resp.json()

    def issue_credentials(self, name, types, source="tracebit-python",
                          source_type="endpoint", labels=None):
        body = {
            "name": name,
            "types": types,
            "source": source,
            "sourceType": source_type,
        }
        if labels:
            body["labels"] = [{"name": k, "value": v} for k, v in labels.items()]
        resp = self.session.post(self._url("issue-credentials"), json=body)
        self._check(resp, "Issue credentials")
        return resp.json()

    def confirm_credentials(self, confirmation_id):
        resp = self.session.post(
            self._url("confirm-credentials"),
            json={"id": confirmation_id},
        )
        if resp.status_code == 404:
            raise TracebitError(
                f"Confirmation ID {confirmation_id} not found."
            )
        self._check(resp, "Confirm credentials")

    def remove_credentials(self, name, cred_type="aws"):
        """Notify Tracebit to expire credentials server-side."""
        resp = self.session.post(
            f"{self.base_url}/api/_internal/v1/cli/remove",
            json={"name": name, "type": cred_type},
        )
        self._check(resp, "Remove credentials")
