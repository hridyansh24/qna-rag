"""
Preflight for the graded T6 harness run (docs/design-rag.md §11.1 step 5,
§11.2). One HTTP error, one call over 180 s, or a run past the harness's
2-hour token leaves no report at all, so every failure the harness could hit
is made to happen here first.

It reads eval/configs.json, logs in as admin, and fails loudly unless:
  - course_id is the "AI-Assisted Software Development" eval course;
  - for every profile the configs name, every resource in the course has a
    SUCCEEDED latest run;
  - for every (profile, model) pair, a /rag/compare call at threshold 1.0
    returns 200 (profile ingested, collection present, model pulled,
    services reachable; nothing generates);
  - for every distinct model, one generating call (baseline profile,
    threshold 0, q01's question) returns 200 within 120 s, untruncated;
  - the course's live similarity_threshold equals the baseline's.

Usage:
    python scripts/rag_preflight.py
    python scripts/rag_preflight.py --write-fingerprint   # after the report run
    python scripts/rag_preflight.py --check-fingerprint   # before grading

The fingerprint (eval/corpus-fingerprint.json) records each profile's
latest SUCCEEDED run per resource, every question's accepted post, and the
last origin/production commit touching each path that shapes answers. A
re-run of the harness reproduces the committed report only while all of
these are unchanged.

Settings are read like the harness reads them: HARNESS_<KEY>, then .env,
then the default (BASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import httpx
from rag_setup_eval import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    BASE_URL,
    CONFIGS_PATH,
    EVAL_COURSE_NAME,
    REPO_ROOT,
)

GROUND_TRUTH_PATH = REPO_ROOT / "eval" / "ground_truth.json"
FINGERPRINT_PATH = REPO_ROOT / "eval" / "corpus-fingerprint.json"
TRUNCATION_MARKER = "[truncated: time budget reached]"
GENERATION_LIMIT_S = 120
FINGERPRINT_PATHS = [
    "backend/app/services/rag/",
    "backend/app/config.py",
    "docker-compose.prod.yml",
    "scripts/pull_models.sh",
    "eval/configs.json",
]

failures: list[str] = []


def ok(message: str) -> None:
    print(f"  ✓ {message}")


def bad(message: str) -> None:
    print(f"  ✗ {message}")
    failures.append(message)


def configurations(configs: dict) -> list[dict]:
    base = configs["baseline"]
    return [base] + [
        {**base, **{k: v for k, v in c.items() if k in base}}
        for c in configs["comparisons"]
    ]


def compare(client: httpx.Client, course: int, config: dict, question: str, **over):
    body = {
        "question": question,
        "ingestion_profile": config["ingestion_profile"],
        "similarity_threshold": config["similarity_threshold"],
        "system_prompt": config["system_prompt"],
        "generation_model": config["generation_model"],
        **over,
    }
    start = time.monotonic()
    resp = client.post(f"/api/courses/{course}/rag/compare", json=body, timeout=180.0)
    return resp, time.monotonic() - start


def fingerprint(client: httpx.Client, course: int, profiles: list[str]) -> dict:
    resources = client.get(f"/api/courses/{course}/resources").json()
    runs = {
        profile: {
            str(r["id"]): (r["latest_runs"].get(profile) or {}).get("id")
            for r in sorted(resources, key=lambda r: r["id"])
        }
        for profile in profiles
    }
    accepted = {}
    for q in client.get(f"/api/courses/{course}/questions").json():
        detail = client.get(f"/api/courses/{course}/questions/{q['id']}").json()
        accepted[str(q["id"])] = next(
            (p["id"] for p in detail["posts"] if p.get("is_accepted")), None
        )
    commits = {}
    for path in FINGERPRINT_PATHS:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H", "origin/production", "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        commits[path] = out.stdout.strip() or None
    return {
        "course_id": course,
        "runs": runs,
        "accepted_posts": accepted,
        "commits": commits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write-fingerprint", action="store_true")
    group.add_argument("--check-fingerprint", action="store_true")
    args = parser.parse_args()

    configs = json.loads(CONFIGS_PATH.read_text())
    course = configs["course_id"]
    runs = configurations(configs)
    profiles = sorted({c["ingestion_profile"] for c in runs})
    models = sorted({c["generation_model"] for c in runs})
    q01 = json.loads(GROUND_TRUTH_PATH.read_text())["questions"][0]["question"]
    print(f"→ {BASE_URL}, course {course}: {len(runs)} configurations")

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        resp = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        if resp.status_code != 200:
            print(
                f"✗ login: HTTP {resp.status_code} {resp.text[:300]}", file=sys.stderr
            )
            sys.exit(1)
        client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

        found = client.get(f"/api/admin/courses/{course}")
        name = found.json().get("name") if found.status_code == 200 else None
        if name == EVAL_COURSE_NAME:
            ok(f"course {course} is {EVAL_COURSE_NAME!r}")
        else:
            bad(f"course {course} is {name!r}, not {EVAL_COURSE_NAME!r}")

        resources = client.get(f"/api/courses/{course}/resources").json()
        for profile in profiles:
            missing = [
                r["display_name"]
                for r in resources
                if (r["latest_runs"].get(profile) or {}).get("status") != "SUCCEEDED"
            ]
            if missing:
                bad(f"{profile}: no SUCCEEDED latest run for {missing}")
            else:
                ok(f"{profile}: all {len(resources)} resources ingested")

        for profile, model in sorted(
            {(c["ingestion_profile"], c["generation_model"]) for c in runs}
        ):
            config = next(
                c
                for c in runs
                if (c["ingestion_profile"], c["generation_model"]) == (profile, model)
            )
            resp, _ = compare(client, course, config, q01, similarity_threshold=1.0)
            if resp.status_code == 200:
                ok(f"compare {profile} × {model}: 200")
            else:
                bad(
                    f"compare {profile} × {model}: HTTP {resp.status_code} {resp.text[:200]}"
                )

        base = configs["baseline"]
        for model in models:
            resp, took = compare(
                client,
                course,
                base,
                q01,
                similarity_threshold=0.0,
                generation_model=model,
            )
            answer = (
                (resp.json().get("answer") or "") if resp.status_code == 200 else ""
            )
            if resp.status_code != 200:
                bad(
                    f"generation with {model}: HTTP {resp.status_code} {resp.text[:200]}"
                )
            elif took > GENERATION_LIMIT_S or TRUNCATION_MARKER in answer:
                bad(
                    f"generation with {model}: {took:.0f}s, truncated={TRUNCATION_MARKER in answer}"
                )
            else:
                ok(f"generation with {model}: {took:.0f}s")

        live = client.get(f"/api/courses/{course}/rag/settings").json()
        if live.get("similarity_threshold") == base["similarity_threshold"]:
            ok(f"live threshold {live['similarity_threshold']} matches the baseline")
        else:
            bad(
                f"live threshold {live.get('similarity_threshold')} != baseline "
                f"{base['similarity_threshold']} (run rag_setup_eval.py --settings-only)"
            )

        if args.write_fingerprint or args.check_fingerprint:
            subprocess.run(
                ["git", "fetch", "-q", "origin", "production"], cwd=REPO_ROOT
            )
            current = fingerprint(client, course, profiles)
            if args.write_fingerprint:
                FINGERPRINT_PATH.write_text(json.dumps(current, indent=2) + "\n")
                ok(f"wrote {FINGERPRINT_PATH.relative_to(REPO_ROOT)}")
            elif not FINGERPRINT_PATH.exists():
                bad("no eval/corpus-fingerprint.json to check against")
            else:
                saved = json.loads(FINGERPRINT_PATH.read_text())
                for key in ("runs", "accepted_posts", "commits"):
                    if saved.get(key) == current[key]:
                        ok(f"fingerprint {key} unchanged")
                    else:
                        bad(f"fingerprint {key} changed: regenerate the report (§11.2)")

    if failures:
        print(f"\n✗ {len(failures)} check(s) failed", file=sys.stderr)
        sys.exit(1)
    print("\n✓ preflight passed")


if __name__ == "__main__":
    main()
