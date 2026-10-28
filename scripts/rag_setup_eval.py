"""
Set up the eval course for the T6 harness over the HTTP API
(docs/design-rag.md §11.1 step 3). Run it once, on a freshly seeded
database, after `python scripts/seed_demo.py`.

It creates the three ingestion profiles from the presets, uploads
eval/sample_data/ as three resources (syllabus, schedule, and the repository
as a zip), syncs every profile one at a time and waits for each to succeed,
then sets the course's live RAG settings. It stops at the first error.

Usage:
    python scripts/rag_setup_eval.py                       # the full setup
    python scripts/rag_setup_eval.py --settings-only       # only the live settings
    python scripts/rag_setup_eval.py --profiles sliding-window,type-tailored
    python scripts/rag_setup_eval.py --course 46   # a non-empty local database

`--profiles` limits which presets are created and synced; a laptop that
can't load gte-Qwen2 skips `embedding-alt` this way. The VM runs them all.

Settings are read like the harness reads them: a HARNESS_-prefixed variable
first (HARNESS_BASE_URL=http://<VM_IP>), then .env, then the default.
    BASE_URL        http://localhost:8000
    ADMIN_USERNAME  admin
    ADMIN_PASSWORD  change_me_admin
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "eval" / "sample_data"
CONFIGS_PATH = REPO_ROOT / "eval" / "configs.json"
EVAL_COURSE_NAME = "AI-Assisted Software Development"
PROFILES = ["sliding-window", "type-tailored", "embedding-alt"]
SYNC_TIMEOUT_S = 3600

OVERRIDES = {
    k[len("HARNESS_") :]: v for k, v in os.environ.items() if k.startswith("HARNESS_")
}


def env_value(key: str, default: str) -> str:
    if key in OVERRIDES:
        return OVERRIDES[key]
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    return os.environ.get(key, default)


BASE_URL = env_value("BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_USERNAME = env_value("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = env_value("ADMIN_PASSWORD", "change_me_admin")


def fail(message: str) -> None:
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(1)


def check(resp: httpx.Response, expected: int, what: str) -> dict | list:
    if resp.status_code != expected:
        fail(f"{what}: HTTP {resp.status_code} {resp.text[:500]}")
    return resp.json() if resp.content else {}


def repo_zip() -> bytes:
    """
    The §5.5 zip: entries relative to eval/sample_data/repo, so with the
    source path `eval/sample_data/repo/` every stored path is the one the
    ground truth names.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((SAMPLE / "repo").rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                zf.write(path, path.relative_to(SAMPLE / "repo").as_posix())
    return buf.getvalue()


def load_configs() -> dict | None:
    if not CONFIGS_PATH.exists():
        return None
    return json.loads(CONFIGS_PATH.read_text())


def wait_for_runs(client: httpx.Client, course: int, run_ids: list[int]) -> list[dict]:
    deadline = time.monotonic() + SYNC_TIMEOUT_S
    while True:
        runs = [
            check(client.get(f"/api/courses/{course}/ingestion-runs/{rid}"), 200, "run")
            for rid in run_ids
        ]
        if all(r["status"] in ("SUCCEEDED", "FAILED") for r in runs):
            return runs
        if time.monotonic() > deadline:
            fail(f"runs still active after {SYNC_TIMEOUT_S}s: {run_ids}")
        time.sleep(3)


def setup_resources(client: httpx.Client, course: int, profiles: list[str]) -> None:
    presets = {
        p["name"]: p
        for p in check(
            client.get(f"/api/courses/{course}/profiles/presets"), 200, "presets"
        )
    }
    for name in profiles:
        check(
            client.post(f"/api/courses/{course}/profiles", json=presets[name]),
            201,
            f"create profile {name}",
        )
        print(f"  ✓ profile {name} ({presets[name]['embedding_model']})")

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
        resource = check(
            client.post(
                f"/api/courses/{course}/resources/upload",
                data={
                    "resource_type": rtype,
                    "display_name": name,
                    "source_path": source_path,
                },
                files={"file": (filename, content)},
                timeout=60.0,
            ),
            201,
            f"upload {name}",
        )
        print(f"  ✓ uploaded {name}: {len(resource['files'])} file(s)")

    for name in profiles:
        start = time.monotonic()
        started = check(
            client.post(f"/api/courses/{course}/profiles/{name}/sync-all"),
            202,
            f"sync-all {name}",
        )
        runs = wait_for_runs(client, course, started["run_ids"])
        failed = [r for r in runs if r["status"] != "SUCCEEDED"]
        if failed:
            fail(f"sync-all {name}: {json.dumps(failed, indent=2)}")
        chunks = sum(r["chunk_count"] or 0 for r in runs)
        print(
            f"  ✓ synced {name}: {len(runs)} runs, {chunks} chunks, "
            f"{time.monotonic() - start:.0f}s"
        )


def set_settings(client: httpx.Client, course: int, configs: dict | None) -> None:
    url = f"/api/courses/{course}/rag/settings"
    current = check(client.get(url), 200, "get settings")
    if configs is None:
        threshold = current["similarity_threshold"]
        print(
            f"  ! eval/configs.json doesn't exist yet; using the default threshold "
            f"{threshold}. Run --settings-only after calibrating (§11.3)."
        )
    else:
        threshold = configs["baseline"]["similarity_threshold"]
    new = dict(
        current,
        enabled=True,
        active_profile="sliding-window",
        similarity_threshold=threshold,
        generation_model=env_value("RAG_DEFAULT_MODEL", "qwen2.5:1.5b"),
    )
    saved = check(client.put(url, json=new, timeout=30.0), 200, "put settings")
    print(
        f"  ✓ live settings: profile {saved['active_profile']}, threshold "
        f"{saved['similarity_threshold']}, model {saved['generation_model']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--settings-only", action="store_true")
    parser.add_argument("--profiles", default=",".join(PROFILES))
    parser.add_argument(
        "--course",
        type=int,
        help="the eval course's ID, when it isn't eval/configs.json's course_id "
        "(a local database that wasn't empty when it was seeded)",
    )
    args = parser.parse_args()
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    unknown = set(profiles) - set(PROFILES)
    if unknown:
        fail(f"unknown profiles: {sorted(unknown)}")

    configs = load_configs()
    course = args.course or (configs["course_id"] if configs else 1)
    print(f"→ {BASE_URL}, course {course}")
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        token = check(
            client.post(
                "/api/auth/login",
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            ),
            200,
            "login",
        )["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        found = check(client.get(f"/api/admin/courses/{course}"), 200, "get course")
        if found["name"] != EVAL_COURSE_NAME:
            fail(
                f"course {course} is {found['name']!r}, not {EVAL_COURSE_NAME!r}. "
                "Reset the database and seed it once (§11.1)."
            )
        if not args.settings_only:
            setup_resources(client, course, profiles)
        set_settings(client, course, configs)
    print("✓ done")


if __name__ == "__main__":
    main()
