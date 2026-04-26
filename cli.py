from __future__ import annotations

import json
import os
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import strftime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import typer
from rich.console import Console
from rich.table import Table

from app.services.auth import build_code_challenge, generate_code_verifier, generate_state

app = typer.Typer(help="Insighta Labs+ command line interface.")
profiles_app = typer.Typer(help="Profile management commands.")
app.add_typer(profiles_app, name="profiles")
console = Console()

DEFAULT_API_URL = os.getenv("INSIGHTA_API_URL") or os.getenv(
    "INSIGHTA_APP_BASE_URL",
    "http://127.0.0.1:8000",
)
CREDENTIALS_PATH = Path.home() / ".insighta" / "credentials.json"


@dataclass(slots=True)
class Credentials:
    access_token: str
    refresh_token: str
    user: dict


def _api_url(value: str | None) -> str:
    raw = (value or DEFAULT_API_URL).strip()
    if "://" not in raw:
        scheme = "http" if raw.startswith(("127.0.0.1", "localhost")) else "https"
        raw = f"{scheme}://{raw}"
    return raw.rstrip("/")


def _load_credentials() -> Credentials | None:
    if not CREDENTIALS_PATH.exists():
        return None
    body = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return Credentials(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        user=body.get("user", {}),
    )


def _save_credentials(payload: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(
        json.dumps(
            {
                "access_token": payload["access_token"],
                "refresh_token": payload["refresh_token"],
                "user": payload.get("user", {}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _delete_credentials() -> None:
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()


def _auth_headers(credentials: Credentials | None) -> dict[str, str]:
    headers = {"X-API-Version": "1"}
    if credentials:
        headers["Authorization"] = f"Bearer {credentials.access_token}"
    return headers


def _refresh(base_url: str, credentials: Credentials) -> Credentials:
    response = httpx.post(
        f"{base_url}/auth/refresh",
        json={"refresh_token": credentials.refresh_token},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    _save_credentials(payload)
    return _load_credentials()  # type: ignore[return-value]


def _request(
    method: str,
    base_url: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    auth: bool = True,
) -> httpx.Response:
    credentials = _load_credentials()
    clean_params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    response = httpx.request(
        method,
        f"{base_url}{path}",
        params=clean_params,
        json=json_body,
        headers=_auth_headers(credentials) if auth else None,
        timeout=30,
    )
    if response.status_code == 401 and auth and credentials:
        try:
            credentials = _refresh(base_url, credentials)
        except Exception:
            console.print("[red]Session expired. Run `insighta login` again.[/red]")
            raise typer.Exit(code=1)
        response = httpx.request(
            method,
            f"{base_url}{path}",
            params=clean_params,
            json=json_body,
            headers=_auth_headers(credentials),
            timeout=30,
        )
    return response


def _require_credentials() -> Credentials:
    credentials = _load_credentials()
    if not credentials:
        console.print("[red]No credentials found. Run `insighta login` first.[/red]")
        raise typer.Exit(code=1)
    return credentials


def _print_profile_table(rows: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold white")
    table.add_column("ID", overflow="fold")
    table.add_column("Name")
    table.add_column("Gender")
    table.add_column("Age")
    table.add_column("Age Group")
    table.add_column("Country")
    for row in rows:
        table.add_row(
            row["id"],
            row["name"],
            row["gender"],
            str(row["age"]),
            row["age_group"],
            row["country_id"],
        )
    console.print(table)


def _login_callback_server(port: int):
    event = threading.Event()
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            result["code"] = params.get("code", [""])[0]
            result["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Login captured.</h2><p>You can return to the terminal.</p></body></html>"
            )
            event.set()

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return server, event, result


@app.command()
def login(
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL."),
    port: int = typer.Option(8765, "--port", help="Local callback port."),
    provider: str = typer.Option("auto", "--provider", help="OAuth provider: auto, github, or mock."),
):
    base_url = _api_url(api_url)
    state = generate_state()
    code_verifier = generate_code_verifier()
    code_challenge = build_code_challenge(code_verifier)
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    query = urlencode(
        {
            "provider": provider,
            "mode": "cli",
            "state": state,
            "code_challenge": code_challenge,
            "redirect_uri": redirect_uri,
        }
    )
    login_url = f"{base_url}/auth/github?{query}"
    server, event, result = _login_callback_server(port)

    with console.status("Opening browser for OAuth login..."):
        opened = webbrowser.open(login_url)
    if not opened:
        console.print(f"[yellow]Open this URL manually:[/yellow] {login_url}")

    if not event.wait(timeout=180):
        server.server_close()
        console.print("[red]Timed out waiting for the OAuth callback.[/red]")
        raise typer.Exit(code=1)
    server.server_close()

    if result.get("state") != state or not result.get("code"):
        console.print("[red]OAuth callback validation failed.[/red]")
        raise typer.Exit(code=1)

    with console.status("Exchanging code for tokens..."):
        response = httpx.get(
            f"{base_url}/auth/github/callback",
            params={
                "mode": "cli",
                "code": result["code"],
                "state": result["state"],
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        _save_credentials(payload)
    console.print(f"[green]Logged in as @{payload['user']['username']}[/green]")


@app.command()
def logout(api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL.")):
    credentials = _require_credentials()
    base_url = _api_url(api_url)
    with console.status("Revoking session..."):
        _request(
            "POST",
            base_url,
            "/auth/logout",
            json_body={"refresh_token": credentials.refresh_token},
            auth=False,
        )
        _delete_credentials()
    console.print("[green]Logged out successfully.[/green]")


@app.command()
def whoami(api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL.")):
    base_url = _api_url(api_url)
    _require_credentials()
    response = _request("GET", base_url, "/api/users/me")
    if response.status_code != 200:
        console.print(f"[red]{response.text}[/red]")
        raise typer.Exit(code=1)
    user = response.json()["data"]
    table = Table(show_header=False)
    table.add_row("Username", user["username"])
    table.add_row("Role", user["role"])
    table.add_row("GitHub ID", str(user["github_id"]))
    table.add_row("User ID", user["id"])
    console.print(table)


@profiles_app.command("list")
def list_profiles(
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL."),
    gender: str | None = typer.Option(None, "--gender"),
    country: str | None = typer.Option(None, "--country"),
    age_group: str | None = typer.Option(None, "--age-group"),
    min_age: int | None = typer.Option(None, "--min-age"),
    max_age: int | None = typer.Option(None, "--max-age"),
    sort_by: str = typer.Option("created_at", "--sort-by"),
    order: str = typer.Option("desc", "--order"),
    page: int = typer.Option(1, "--page"),
    limit: int = typer.Option(20, "--limit"),
):
    base_url = _api_url(api_url)
    _require_credentials()
    with console.status("Loading profiles..."):
        response = _request(
            "GET",
            base_url,
            "/api/profiles",
            params={
                "gender": gender,
                "country": country,
                "age_group": age_group,
                "min_age": min_age,
                "max_age": max_age,
                "sort_by": sort_by,
                "order": order,
                "page": page,
                "limit": limit,
            },
        )
    if response.status_code != 200:
        console.print(f"[red]{response.text}[/red]")
        raise typer.Exit(code=1)
    body = response.json()
    _print_profile_table(body["data"])
    console.print(
        f"[cyan]Page {body['page']} | Limit {body['limit']} | Total {body['total']} | Pages {body['total_pages']}[/cyan]"
    )


@profiles_app.command("get")
def get_profile(
    profile_id: str,
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL."),
):
    base_url = _api_url(api_url)
    _require_credentials()
    response = _request("GET", base_url, f"/api/profiles/{profile_id}")
    if response.status_code != 200:
        console.print(f"[red]{response.text}[/red]")
        raise typer.Exit(code=1)
    profile = response.json()["data"]
    table = Table(show_header=False)
    for key, value in profile.items():
        table.add_row(key, str(value))
    console.print(table)


@profiles_app.command("search")
def search_profiles_cmd(
    query: str,
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL."),
):
    base_url = _api_url(api_url)
    _require_credentials()
    with console.status("Searching profiles..."):
        response = _request("GET", base_url, "/api/profiles/search", params={"q": query})
    if response.status_code != 200:
        console.print(f"[red]{response.text}[/red]")
        raise typer.Exit(code=1)
    _print_profile_table(response.json()["data"])


@profiles_app.command("create")
def create_profile(
    name: str = typer.Option(..., "--name"),
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL."),
):
    base_url = _api_url(api_url)
    _require_credentials()
    with console.status("Creating profile..."):
        response = _request("POST", base_url, "/api/profiles", json_body={"name": name})
    if response.status_code not in {200, 201}:
        console.print(f"[red]{response.text}[/red]")
        raise typer.Exit(code=1)
    profile = response.json()["data"]
    console.print(f"[green]{profile['name']} is available with ID {profile['id']}[/green]")


@profiles_app.command("export")
def export_profiles(
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Backend base URL."),
    format: str = typer.Option("csv", "--format"),
    gender: str | None = typer.Option(None, "--gender"),
    country: str | None = typer.Option(None, "--country"),
    age_group: str | None = typer.Option(None, "--age-group"),
    min_age: int | None = typer.Option(None, "--min-age"),
    max_age: int | None = typer.Option(None, "--max-age"),
    sort_by: str = typer.Option("created_at", "--sort-by"),
    order: str = typer.Option("desc", "--order"),
    output: Path | None = typer.Option(None, "--output"),
):
    base_url = _api_url(api_url)
    _require_credentials()
    if format != "csv":
        console.print("[red]Only csv export is supported.[/red]")
        raise typer.Exit(code=1)
    target = output or Path(f"profiles_{strftime('%Y%m%d_%H%M%S')}.csv")
    with console.status("Exporting profiles..."):
        response = _request(
            "GET",
            base_url,
            "/api/profiles/export",
            params={
                "format": format,
                "gender": gender,
                "country": country,
                "age_group": age_group,
                "min_age": min_age,
                "max_age": max_age,
                "sort_by": sort_by,
                "order": order,
            },
        )
    if response.status_code != 200:
        console.print(f"[red]{response.text}[/red]")
        raise typer.Exit(code=1)
    target.write_text(response.text, encoding="utf-8", newline="")
    console.print(f"[green]Exported profiles to {target}[/green]")
