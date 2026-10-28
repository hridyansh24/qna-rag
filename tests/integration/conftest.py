"""
Session-level fixtures for the QnA integration test suite.

Stack lifecycle
---------------
The `docker_stack` fixture detects whether the stack is already running
(by calling /api/health). If it is, nothing is started or stopped — the
dev stack is used as-is. If it is not, `docker compose up -d --build` is
run from the repo root and `docker compose down` is called on teardown.

Test isolation
--------------
Every test gets a freshly-created course (via the `course_id` fixture), so
category-name collisions and question lists don't leak between tests.
Courses have no DELETE endpoint, so they're left as inert records — same
convention as the rest of this course's projects.
"""

from __future__ import annotations

import io
import logging
import pathlib
import subprocess
import time
import uuid
import zipfile

import httpx
import pytest

logger = logging.getLogger(__name__)

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# pytest options
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )


@pytest.fixture(scope="session")
def base_url(request) -> str:
    return request.config.getoption("--base-url").rstrip("/")


# ---------------------------------------------------------------------------
# Docker stack lifecycle
# ---------------------------------------------------------------------------


def _is_healthy(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/api/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _wait_healthy(url: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_healthy(url):
            return
        time.sleep(2)
    raise RuntimeError(
        f"Stack at {url} did not become healthy within {timeout}s. "
        "Check `docker compose logs backend`."
    )


@pytest.fixture(scope="session")
def docker_stack(base_url: str):
    already_running = _is_healthy(base_url)

    if not already_running:
        logger.info("Stack not detected — running docker compose up --build")
        subprocess.run(
            ["docker", "compose", "up", "-d", "--build"], check=True, cwd=_REPO_ROOT
        )
        logger.info("Waiting for stack to become healthy…")
        _wait_healthy(base_url)
        logger.info("Stack is healthy")

    yield

    if not already_running:
        logger.info("Tearing down stack started by this session")
        subprocess.run(["docker", "compose", "down"], check=True, cwd=_REPO_ROOT)


# ---------------------------------------------------------------------------
# Admin token (session-scoped — one login for the whole session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def admin_token(docker_stack, base_url: str) -> str:
    """Log in as the bootstrap admin. Credentials come from .env / environment."""
    import os

    env_path = _REPO_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    username = env_vars.get("ADMIN_USERNAME") or os.environ.get(
        "ADMIN_USERNAME", "admin"
    )
    password = env_vars.get("ADMIN_PASSWORD") or os.environ.get(
        "ADMIN_PASSWORD", "change_me_admin"
    )

    r = httpx.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10.0,
    )
    assert r.status_code == 200, (
        f"Admin login failed ({r.status_code}): {r.text}\n"
        f"Set ADMIN_USERNAME / ADMIN_PASSWORD in .env or environment."
    )
    token = r.json().get("access_token")
    assert token, "Login response missing access_token"
    return token


def admin_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Dev-only netid login helper — mints a distinct STUDENT or STAFF identity
# and grants it course access, using the same dev fallback the frontend uses.
# ---------------------------------------------------------------------------


def login_as_netid(base_url: str, admin_token: str, course_id: int, role: str) -> str:
    netid = f"test-{role.lower()}-{uuid.uuid4().hex[:8]}"

    r = httpx.post(f"{base_url}/api/auth/login", json={"netid": netid}, timeout=10.0)
    assert r.status_code == 200, f"netid login failed: {r.text}"
    temp_token = r.json()["temp_token"]

    r = httpx.post(
        f"{base_url}/api/auth/exchange-temp",
        headers={"Authorization": f"Bearer {temp_token}"},
        timeout=10.0,
    )
    assert r.status_code == 200, f"exchange-temp failed: {r.text}"
    access_token = r.json()["access_token"]

    r = httpx.get(
        f"{base_url}/api/admin/users", headers=admin_headers(admin_token), timeout=10.0
    )
    assert r.status_code == 200
    user = next(u for u in r.json() if u["netid"] == netid)

    r = httpx.post(
        f"{base_url}/api/admin/users/{user['id']}/course-access",
        json={"course_id": course_id, "role": role},
        headers=admin_headers(admin_token),
        timeout=10.0,
    )
    assert r.status_code == 204, f"grant course-access failed: {r.text}"

    return access_token


@pytest.fixture()
def course_id(docker_stack, base_url: str, admin_token: str) -> int:
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(
        f"{base_url}/api/admin/courses",
        json={"name": f"Test Course {tag}", "semester": "Test"},
        headers=admin_headers(admin_token),
        timeout=10.0,
    )
    assert r.status_code == 201, f"Create course failed: {r.text}"
    return r.json()["id"]


@pytest.fixture()
def student_token(base_url: str, admin_token: str, course_id: int) -> str:
    return login_as_netid(base_url, admin_token, course_id, "STUDENT")


@pytest.fixture()
def staff_token(base_url: str, admin_token: str, course_id: int) -> str:
    return login_as_netid(base_url, admin_token, course_id, "STAFF")


@pytest.fixture()
def category_id(base_url: str, course_id: int, staff_token: str) -> int:
    """A default category for tests that need one to post a question but
    aren't themselves testing category behavior (every question requires
    at least one category — see QuestionCreate.category_ids)."""
    r = httpx.post(
        f"{base_url}/api/courses/{course_id}/categories",
        json={"name": "General", "description": "Default test category"},
        headers={"Authorization": f"Bearer {staff_token}"},
        timeout=10.0,
    )
    assert r.status_code == 201, f"Create category failed: {r.text}"
    return r.json()["id"]


# ---------------------------------------------------------------------------
# RAG: a course with the eval sample data ingested (docs/design-rag.md §11.1)
# ---------------------------------------------------------------------------

SAMPLE = pathlib.Path(__file__).parents[2] / "eval" / "sample_data"
SYNC_TIMEOUT_S = 300


def repo_zip() -> bytes:
    """The §5.5 command's zip: entries relative to eval/sample_data/repo."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted((SAMPLE / "repo").rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                zf.write(path, path.relative_to(SAMPLE / "repo").as_posix())
    return buf.getvalue()


def upload(base_url, course, headers, rtype, name, filename, content, source_path):
    return httpx.post(
        f"{base_url}/api/courses/{course}/resources/upload",
        headers=headers,
        data={"resource_type": rtype, "display_name": name, "source_path": source_path},
        files={"file": (filename, content)},
        timeout=60.0,
    )


def wait_for_runs(base_url, course, headers, run_ids) -> list[dict]:
    deadline = time.monotonic() + SYNC_TIMEOUT_S
    while True:
        runs = [
            httpx.get(
                f"{base_url}/api/courses/{course}/ingestion-runs/{rid}",
                headers=headers,
                timeout=10.0,
            ).json()
            for rid in run_ids
        ]
        if all(r["status"] in ("SUCCEEDED", "FAILED") for r in runs):
            return runs
        assert time.monotonic() < deadline, f"runs still active: {runs}"
        time.sleep(2)


@pytest.fixture(scope="module")
def rag_course(docker_stack, base_url, admin_token):
    """A course with the eval uploads, one accepted thread, and a synced profile."""
    admin = admin_headers(admin_token)
    r = httpx.post(
        f"{base_url}/api/admin/courses",
        json={"name": f"RAG ingestion {uuid.uuid4().hex[:8]}", "semester": "Test"},
        headers=admin,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    course = r.json()["id"]
    staff = {
        "Authorization": f"Bearer {login_as_netid(base_url, admin_token, course, 'STAFF')}"
    }

    uploaded = {}
    for rtype, name, filename, content, source_path in [
        (
            "SYLLABUS",
            "Syllabus",
            "syllabus.html",
            (SAMPLE / "web" / "syllabus.html").read_bytes(),
            "eval/sample_data/web/syllabus.html",
        ),
        (
            "SCHEDULE",
            "Schedule",
            "schedule.html",
            (SAMPLE / "web" / "schedule.html").read_bytes(),
            "eval/sample_data/web/schedule.html",
        ),
        (
            "REPOSITORY",
            "Course repository",
            "repo.zip",
            repo_zip(),
            "eval/sample_data/repo/",
        ),
    ]:
        r = upload(base_url, course, staff, rtype, name, filename, content, source_path)
        assert r.status_code == 201, r.text
        uploaded[rtype] = r.json()

    # One thread with an accepted staff answer, for QA_HISTORY.
    r = httpx.post(
        f"{base_url}/api/courses/{course}/categories",
        json={"name": "General"},
        headers=staff,
        timeout=10.0,
    )
    category = r.json()["id"]
    r = httpx.post(
        f"{base_url}/api/courses/{course}/questions",
        json={
            "title": "How many slip days do we get?",
            "body": "Asking for P2.",
            "category_ids": [category],
        },
        headers=staff,
        timeout=10.0,
    )
    question = r.json()["id"]
    r = httpx.post(
        f"{base_url}/api/courses/{course}/questions/{question}/posts",
        json={"kind": "ANSWER", "body": "Five per semester, P1–P4 only."},
        headers=staff,
        timeout=10.0,
    )
    post = next(p for p in r.json()["posts"] if p["kind"] == "ANSWER")["id"]
    r = httpx.patch(
        f"{base_url}/api/courses/{course}/questions/{question}/posts/{post}/accept",
        json={"is_accepted": True},
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 200, r.text

    r = httpx.get(
        f"{base_url}/api/courses/{course}/profiles/presets", headers=staff, timeout=10.0
    )
    preset = next(p for p in r.json() if p["name"] == "sliding-window")
    r = httpx.post(
        f"{base_url}/api/courses/{course}/profiles",
        json=preset,
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text

    r = httpx.post(
        f"{base_url}/api/courses/{course}/profiles/sliding-window/sync-all",
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 202, r.text
    runs = wait_for_runs(base_url, course, staff, r.json()["run_ids"])
    return {"id": course, "staff": staff, "uploaded": uploaded, "runs": runs}
