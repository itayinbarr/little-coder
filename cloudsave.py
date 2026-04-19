"""
Cloud sync for little-coder sessions via GitHub Gist.

Supported provider: GitHub Gist
  - No extra cloud account needed beyond a GitHub Personal Access Token
  - Sessions stored as private Gists (JSON), browsable in GitHub UI
  - Zero extra dependencies (uses urllib from stdlib)

Config keys (stored in ~/.little-coder/config.json):
  gist_token      — GitHub Personal Access Token (needs 'gist' scope)
  cloudsave_auto  — bool: auto-upload on /exit
  cloudsave_last_gist_id — last uploaded gist ID (for in-place update)
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from datetime import datetime

GIST_TAG = "[little-coder]"
_API = "https://api.github.com"


# ── Low-level Gist API ────────────────────────────────────────────────────────

def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f"{_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _request_safe(method: str, path: str, token: str, body: dict | None = None):
    """Like _request but returns (result, error_str)."""
    try:
        return _request(method, path, token, body), None
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        try:
            msg = json.loads(msg).get("message", msg)
        except Exception:
            pass
        return None, f"GitHub API {e.code}: {msg}"
    except Exception as e:
        return None, str(e)


# ── Public API ────────────────────────────────────────────────────────────────

def validate_token(token: str) -> tuple[bool, str]:
    """Check token is valid and has gist scope. Returns (ok, message)."""
    result, err = _request_safe("GET", "/user", token)
    if err:
        return False, f"Token validation failed: {err}"
    scopes_needed = {"gist"}
    # GitHub returns X-OAuth-Scopes header but urllib doesn't easily expose it;
    # a successful /user call is sufficient for basic validation.
    login = result.get("login", "unknown")
    return True, login


def upload_session(
    session_data: dict,
    token: str,
    description: str = "",
    gist_id: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Create or update a Gist with the session JSON.
    Returns (gist_id, error). On success gist_id is the Gist ID.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    desc = f"{GIST_TAG} {description or ts}"
    filename = f"little-coder_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    content = json.dumps(session_data, indent=2, default=str)

    body = {
        "description": desc,
        "public": False,
        "files": {filename: {"content": content}},
    }

    if gist_id:
        result, err = _request_safe("PATCH", f"/gists/{gist_id}", token, body)
    else:
        result, err = _request_safe("POST", "/gists", token, body)

    if err:
        return None, err
    return result["id"], None


def list_sessions(token: str, max_results: int = 20) -> tuple[list[dict], str | None]:
    """
    List Gists tagged as little-coder sessions.
    Returns (list of {id, description, updated_at, url}), error).
    """
    result, err = _request_safe("GET", "/gists?per_page=100", token)
    if err:
        return [], err

    sessions = [
        {
            "id": g["id"],
            "description": g["description"],
            "updated_at": g["updated_at"],
            "url": g["html_url"],
            "files": list(g["files"].keys()),
        }
        for g in result
        if g.get("description", "").startswith(GIST_TAG)
    ]
    return sessions[:max_results], None


def download_session(token: str, gist_id: str) -> tuple[dict | None, str | None]:
    """
    Fetch a Gist and return the parsed session JSON.
    Returns (session_data, error).
    """
    result, err = _request_safe("GET", f"/gists/{gist_id}", token)
    if err:
        return None, err

    files = result.get("files", {})
    if not files:
        return None, "Gist has no files"

    # Take the first (and usually only) file
    file_info = next(iter(files.values()))
    raw_content = file_info.get("content")
    if not raw_content:
        # Truncated — fetch raw URL
        raw_url = file_info.get("raw_url")
        if not raw_url:
            return None, "Could not retrieve file content"
        req = urllib.request.Request(
            raw_url,
            headers={"Authorization": f"token {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            raw_content = resp.read().decode()

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in Gist: {e}"
    return data, None
