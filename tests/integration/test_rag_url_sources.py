"""
Integration tests for URL resources against the live stack
(docs/design-rag.md §7.1, §9.4, §9.5).

These need no internet access: every URL here is refused at registration,
or by the SSRF guard when the sync fetches it. Fetching real pages and
cloning a real repository are checked by hand on the VM (§11.5).
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import wait_for_runs


@pytest.fixture()
def staff(staff_token: str) -> dict:
    return {"Authorization": f"Bearer {staff_token}"}


@pytest.fixture()
def baseline_profile(base_url, course_id, staff) -> str:
    r = httpx.get(
        f"{base_url}/api/courses/{course_id}/profiles/presets",
        headers=staff,
        timeout=10.0,
    )
    preset = next(p for p in r.json() if p["name"] == "sliding-window")
    r = httpx.post(
        f"{base_url}/api/courses/{course_id}/profiles",
        json=preset,
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    return preset["name"]


def register(base_url, course_id, staff, **body) -> httpx.Response:
    return httpx.post(
        f"{base_url}/api/courses/{course_id}/resources",
        json={"display_name": "Live source", **body},
        headers=staff,
        timeout=10.0,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/health",  # loopback
        "http://backend:8000/api/health",  # a compose service by name
        "http://169.254.169.254/latest/meta-data/",  # the cloud metadata server
        "http://10.0.0.1/",  # a private network
    ],
)
def test_a_page_on_a_disallowed_address_fails_its_sync(
    base_url, course_id, staff, baseline_profile, url
):
    r = register(base_url, course_id, staff, resource_type="SCHEDULE", url=url)
    assert r.status_code == 201, r.text  # registration checks syntax only (§9.4)
    rid = r.json()["id"]
    r = httpx.post(
        f"{base_url}/api/courses/{course_id}/resources/{rid}/sync",
        json={"profile": baseline_profile},
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 202, r.text
    (run,) = wait_for_runs(base_url, course_id, staff, [r.json()["run_id"]])
    assert run["status"] == "FAILED"
    assert "address not allowed" in run["error"]
    assert run["chunk_count"] is None


@pytest.mark.parametrize(
    "body, reason",
    [
        ({"resource_type": "REPOSITORY", "url": "https://github.com/a/b.git"}, "Repositories must be on"),
        ({"resource_type": "REPOSITORY", "url": "http://git.doit.wisc.edu/a/b.git"}, "https"),
        ({"resource_type": "REPOSITORY", "url": "https://u:p@git.doit.wisc.edu/a/b.git"}, "username or password"),
        ({"resource_type": "REPOSITORY", "url": "https://git.doit.wisc.edu/a/b.git", "repo_ref": "--upload-pack=x"}, "branch name"),
        ({"resource_type": "REPOSITORY", "url": "https://git.doit.wisc.edu/a/b.git", "repo_ref": "a/../b"}, "branch name"),
        ({"resource_type": "SYLLABUS", "url": "ftp://example.com/s.html"}, "http or https"),
        ({"resource_type": "SYLLABUS", "url": "https://example.com/s", "repo_ref": "main"}, "only applies to repositories"),
    ],
)  # fmt: skip
def test_registration_rejects_unsafe_urls(base_url, course_id, staff, body, reason):
    r = register(base_url, course_id, staff, **body)
    assert r.status_code == 422, r.text
    assert reason in r.text
