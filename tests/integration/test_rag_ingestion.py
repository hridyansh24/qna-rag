"""
Integration tests for resources, profiles and ingestion runs
(docs/design-rag.md §5.5, §7.5, §9.5, §13), against the running stack with
Infinity and ChromaDB.

One module-scoped course (the `rag_course` fixture in conftest.py) gets the eval sample data uploaded as in §11.1,
one accepted Q&A thread, and a `sliding-window` profile synced with
sync-all.

Run with:
    cd tests/integration && pytest test_rag_ingestion.py -v
"""

from __future__ import annotations

import uuid

import httpx

from .conftest import admin_headers, login_as_netid, upload, wait_for_runs


def test_upload_stores_the_source_paths(rag_course):
    repo = rag_course["uploaded"]["REPOSITORY"]
    assert "eval/sample_data/repo/p2-buzzer/instructions.md" in repo["files"]
    assert "eval/sample_data/repo/lecture-10/slides.pdf" in repo["files"]
    assert repo["skipped"] == []
    assert rag_course["uploaded"]["SYLLABUS"]["files"] == [
        "eval/sample_data/web/syllabus.html"
    ]


def test_sync_all_ingests_every_resource_including_qa(base_url, rag_course):
    runs = rag_course["runs"]
    assert len(runs) == 4  # three uploads plus QA_HISTORY
    assert all(r["status"] == "SUCCEEDED" for r in runs), runs
    assert all(r["chunk_count"] > 0 for r in runs)
    r = httpx.get(
        f"{base_url}/api/courses/{rag_course['id']}/resources",
        headers=rag_course["staff"],
        timeout=10.0,
    )
    by_type = {res["resource_type"]: res for res in r.json()}
    assert by_type["QA_HISTORY"]["source_kind"] == "BOARD"
    qa_run = by_type["QA_HISTORY"]["latest_runs"]["sliding-window"]
    assert qa_run["chunk_count"] == 1 and qa_run["status"] == "SUCCEEDED"


def test_resync_while_active_is_409_and_resync_does_not_duplicate(base_url, rag_course):
    course, staff = rag_course["id"], rag_course["staff"]
    rid = rag_course["uploaded"]["SCHEDULE"]["id"]
    before = next(r for r in rag_course["runs"] if r["resource_id"] == rid)[
        "chunk_count"
    ]
    url = f"{base_url}/api/courses/{course}/resources/{rid}/sync"
    r = httpx.post(url, json={"profile": "sliding-window"}, headers=staff, timeout=10.0)
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    again = httpx.post(
        url, json={"profile": "sliding-window"}, headers=staff, timeout=10.0
    )
    delete = httpx.delete(
        f"{base_url}/api/courses/{course}/resources/{rid}", headers=staff
    )
    sync_all = httpx.post(
        f"{base_url}/api/courses/{course}/profiles/sliding-window/sync-all",
        headers=staff,
    )
    (run,) = wait_for_runs(base_url, course, staff, [run_id])
    assert again.status_code == 409
    assert delete.status_code == 409
    assert sync_all.status_code == 409
    assert run["status"] == "SUCCEEDED" and run["chunk_count"] == before


def test_file_endpoint_serves_members_as_plain_text(base_url, admin_token, rag_course):
    course = rag_course["id"]
    student = {
        "Authorization": f"Bearer {login_as_netid(base_url, admin_token, course, 'STUDENT')}"
    }
    syllabus = rag_course["uploaded"]["SYLLABUS"]
    url = f"{base_url}/api/courses/{course}/resources/{syllabus['id']}/files/eval/sample_data/web/syllabus.html"
    r = httpx.get(url, headers=student, timeout=10.0)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<html" in r.text.lower()
    text = httpx.get(url, params={"format": "text"}, headers=student, timeout=10.0)
    assert text.status_code == 200 and "<html" not in text.text.lower()
    assert (
        httpx.get(
            url.replace("syllabus.html", "../../../etc/passwd"), headers=student
        ).status_code
        == 404
    )

    other = httpx.post(
        f"{base_url}/api/admin/courses",
        json={"name": f"Other {uuid.uuid4().hex[:8]}", "semester": "Test"},
        headers=admin_headers(admin_token),
    ).json()["id"]
    outsider = {
        "Authorization": f"Bearer {login_as_netid(base_url, admin_token, other, 'STUDENT')}"
    }
    assert httpx.get(url, headers=outsider, timeout=10.0).status_code == 404
    assert (
        httpx.get(
            url.replace(f"/courses/{course}/", f"/courses/{other}/"), headers=outsider
        ).status_code
        == 404
    )


def test_resource_validation(base_url, rag_course):
    course, staff = rag_course["id"], rag_course["staff"]
    r = upload(base_url, course, staff, "QA_HISTORY", "Q&A", "x.md", b"# x", "x.md")
    assert r.status_code == 422
    r = upload(base_url, course, staff, "SYLLABUS", "S", "s.pdf", b"%PDF", "s.pdf")
    assert r.status_code == 422
    r = upload(base_url, course, staff, "REPOSITORY", "R", "r.md", b"# r", "../r.md")
    assert r.status_code == 422

    def register(**body):
        return httpx.post(
            f"{base_url}/api/courses/{course}/resources",
            json=body,
            headers=staff,
            timeout=10.0,
        )

    # Registration checks syntax only; addresses are checked at fetch (§9.4).
    assert (
        register(
            resource_type="SYLLABUS", display_name="S", url="http://chromadb:8000/"
        ).status_code
        == 201
    )
    assert (
        register(
            resource_type="REPOSITORY",
            display_name="R",
            url="https://github.com/a/b.git",
        ).status_code
        == 422
    )
    assert (
        register(
            resource_type="REPOSITORY",
            display_name="R",
            url="https://git.doit.wisc.edu/g/p.git",
            repo_ref="--upload-pack=x",
        ).status_code
        == 422
    )
    assert (
        register(
            resource_type="SYLLABUS",
            display_name="S",
            url="https://x.edu/",
            repo_ref="main",
        ).status_code
        == 422
    )

    qa = next(
        res
        for res in httpx.get(
            f"{base_url}/api/courses/{course}/resources", headers=staff
        ).json()
        if res["resource_type"] == "QA_HISTORY"
    )
    replace = httpx.put(
        f"{base_url}/api/courses/{course}/resources/{qa['id']}/upload",
        headers=staff,
        data={"source_path": "x.md"},
        files={"file": ("x.md", b"# x")},
    )
    assert replace.status_code == 409
    assert (
        httpx.delete(
            f"{base_url}/api/courses/{course}/resources/{qa['id']}", headers=staff
        ).status_code
        == 409
    )


def test_profiles_are_validated_and_immutable(base_url, rag_course):
    course, staff = rag_course["id"], rag_course["staff"]
    url = f"{base_url}/api/courses/{course}/profiles"
    window = {"strategy": "sliding_window", "chunk_size": 200, "chunk_overlap": 40}
    dup = {
        "name": "sliding-window",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "chunking": {"default": window},
    }
    assert httpx.post(url, json=dup, headers=staff).status_code == 409
    bad_size = {
        **dup,
        "name": "too-big",
        "chunking": {"default": {**window, "chunk_size": 300}},
    }
    assert httpx.post(url, json=bad_size, headers=staff).status_code == 422
    bad_model = {**dup, "name": "other-model", "embedding_model": "not/a-model"}
    assert httpx.post(url, json=bad_model, headers=staff).status_code == 422
    assert (
        httpx.post(url, json={**dup, "name": "Bad_Name"}, headers=staff).status_code
        == 422
    )


def test_delete_resource(base_url, rag_course):
    course, staff = rag_course["id"], rag_course["staff"]
    r = upload(
        base_url,
        course,
        staff,
        "REPOSITORY",
        "Scratch",
        "n.md",
        b"# Notes\nSlip days.\n",
        "scratch/n.md",
    )
    rid = r.json()["id"]
    run = httpx.post(
        f"{base_url}/api/courses/{course}/resources/{rid}/sync",
        json={"profile": "sliding-window"},
        headers=staff,
    ).json()["run_id"]
    wait_for_runs(base_url, course, staff, [run])
    assert (
        httpx.delete(
            f"{base_url}/api/courses/{course}/resources/{rid}", headers=staff
        ).status_code
        == 204
    )
    ids = [
        res["id"]
        for res in httpx.get(
            f"{base_url}/api/courses/{course}/resources", headers=staff
        ).json()
    ]
    assert rid not in ids
