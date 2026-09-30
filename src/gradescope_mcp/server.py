from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from gradescopeapi import DEFAULT_GRADESCOPE_BASE_URL
from gradescopeapi.classes.connection import GSConnection
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("gradescope")

_connection: GSConnection | None = None


def _credentials() -> tuple[str, str]:
    email = os.getenv("GRADESCOPE_EMAIL", "").strip()
    password = os.getenv("GRADESCOPE_PASSWORD", "")
    if not email or not password:
        raise RuntimeError(
            "Missing GRADESCOPE_EMAIL or GRADESCOPE_PASSWORD environment variable."
        )
    return email, password


def _login() -> GSConnection:
    global _connection
    if _connection is not None and _connection.logged_in:
        return _connection

    email, password = _credentials()
    connection = GSConnection()
    connection.login(email, password)
    _connection = connection
    return connection


async def _connection_or_login() -> GSConnection:
    return await asyncio.to_thread(_login)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


_SUBMISSION_HREF_RE = re.compile(
    r"^/courses/(?P<course>\d+)/assignments/(?P<assignment>\d+)/submissions/(?P<submission>\d+)$"
)


def _course_submissions(connection: GSConnection, course_id: str) -> list[dict[str, Any]]:
    """Parse the student's own submission links from a Gradescope course page."""
    response = connection.session.get(f"{DEFAULT_GRADESCOPE_BASE_URL}/courses/{course_id}")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    submissions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in soup.find_all("tr", role="row"):
        anchor = row.find("a", href=_SUBMISSION_HREF_RE)
        if anchor is None:
            continue
        match = _SUBMISSION_HREF_RE.match(anchor.get("href", ""))
        if match is None:
            continue
        key = (match.group("assignment"), match.group("submission"))
        if key in seen:
            continue
        seen.add(key)

        status_cell = row.find("td", class_=lambda value: value and "submissionStatus" in str(value))
        status = " ".join(status_cell.stripped_strings) if status_cell else None
        submissions.append(
            {
                "course_id": course_id,
                "assignment_id": match.group("assignment"),
                "submission_id": match.group("submission"),
                "assignment": " ".join(anchor.stripped_strings),
                "status": status,
            }
        )
    return submissions


def _submission_payload(
    connection: GSConnection,
    course_id: str,
    assignment_id: str,
    submission_id: str,
) -> dict[str, Any]:
    """Fetch the student's own submission payload from Gradescope."""
    url = (
        f"{DEFAULT_GRADESCOPE_BASE_URL}/courses/{course_id}/assignments/"
        f"{assignment_id}/submissions/{submission_id}"
    )
    response = connection.session.get(url)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type:
        data = response.json()
        return data if isinstance(data, dict) else {}

    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup.find_all(attrs={"data-react-props": True}):
        raw = node.get("data-react-props")
        if not isinstance(raw, str):
            continue
        try:
            data = json.loads(html.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and (
            "assignment_submission" in data
            or "pdf_attachment" in data
            or "text_files" in data
        ):
            return data
    return {}


def _resolved_submission_files(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize downloadable file metadata while retaining URLs only internally."""
    files: list[dict[str, Any]] = []

    pdf = payload.get("pdf_attachment")
    if isinstance(pdf, dict) and pdf.get("url"):
        files.append(
            {
                "file_ref": "pdf",
                "kind": "pdf",
                "filename": pdf.get("filename") or "submission.pdf",
                "page_count": pdf.get("page_count"),
                "url": pdf.get("url"),
            }
        )

    text_files = payload.get("text_files") or []
    if isinstance(text_files, list):
        for index, item in enumerate(text_files):
            if not isinstance(item, dict):
                continue
            nested = item.get("file") if isinstance(item.get("file"), dict) else {}
            url = nested.get("url") or item.get("url")
            if not url:
                continue
            filename = (
                nested.get("filename")
                or nested.get("name")
                or item.get("filename")
                or item.get("name")
                or f"submitted_file_{index + 1}"
            )
            files.append(
                {
                    "file_ref": f"text:{index}",
                    "kind": "text",
                    "filename": filename,
                    "page_count": None,
                    "url": url,
                }
            )

    return files


@mcp.tool(
    name="gradescope_list_courses",
    annotations={
        "title": "List Gradescope courses",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def gradescope_list_courses() -> dict[str, Any]:
    """List Gradescope courses grouped by student/instructor role."""
    connection = await _connection_or_login()
    courses = await asyncio.to_thread(connection.account.get_courses)

    result: dict[str, dict[str, Any]] = {}
    for role, role_courses in courses.items():
        result[role] = {}
        for course_id, course in role_courses.items():
            result[role][course_id] = {
                "course_id": course_id,
                "name": course.name,
                "full_name": course.full_name,
                "semester": course.semester,
                "year": course.year,
                "num_assignments": course.num_assignments,
            }
    return result


@mcp.tool(
    name="gradescope_list_assignments",
    annotations={
        "title": "List Gradescope assignments",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def gradescope_list_assignments(course_id: str) -> list[dict[str, Any]]:
    """
    List assignments for one Gradescope course.

    `status` is the exact status parsed from Gradescope's student course table.
    It is intentionally not reinterpreted into a separate submitted/not-submitted flag.
    """
    course_id = course_id.strip()
    if not course_id:
        raise ValueError("course_id is required")

    connection = await _connection_or_login()
    assignments = await asyncio.to_thread(connection.account.get_assignments, course_id)

    return [
        {
            "assignment_id": assignment.assignment_id,
            "name": assignment.name,
            "release_at": _iso(assignment.release_date),
            "due_at": _iso(assignment.due_date),
            "late_due_at": _iso(assignment.late_due_date),
            "status": assignment.submissions_status,
            "grade": assignment.grade,
            "max_grade": assignment.max_grade,
        }
        for assignment in assignments
    ]


@mcp.tool(
    name="gradescope_upcoming_assignments",
    annotations={
        "title": "List upcoming Gradescope assignments",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def gradescope_upcoming_assignments(days: int = 14) -> list[dict[str, Any]]:
    """Return upcoming assignments across all student courses, sorted by due time."""
    if days < 1 or days > 365:
        raise ValueError("days must be between 1 and 365")

    connection = await _connection_or_login()
    courses = await asyncio.to_thread(connection.account.get_courses)
    student_courses = courses.get("student", {})

    now = datetime.now().astimezone()
    horizon = now + timedelta(days=days)
    upcoming: list[dict[str, Any]] = []

    for course_id, course in student_courses.items():
        assignments = await asyncio.to_thread(connection.account.get_assignments, course_id)
        for assignment in assignments:
            due = assignment.due_date
            if due is None:
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=now.tzinfo)
            if now <= due <= horizon:
                upcoming.append(
                    {
                        "course_id": course_id,
                        "course": course.full_name or course.name,
                        "assignment_id": assignment.assignment_id,
                        "name": assignment.name,
                        "due_at": _iso(due),
                        "late_due_at": _iso(assignment.late_due_date),
                        "status": assignment.submissions_status,
                        "grade": assignment.grade,
                        "max_grade": assignment.max_grade,
                    }
                )

    upcoming.sort(key=lambda item: item["due_at"] or "")
    return upcoming


@mcp.tool(
    name="gradescope_list_submissions",
    annotations={
        "title": "List my Gradescope submissions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def gradescope_list_submissions(course_id: str | None = None) -> list[dict[str, Any]]:
    """
    List the authenticated student's own submitted assignments.

    If course_id is omitted, submissions from all student courses are returned.
    This does not download submitted files.
    """
    connection = await _connection_or_login()
    courses = await asyncio.to_thread(connection.account.get_courses)
    student_courses = courses.get("student", {})

    if course_id is not None:
        course_id = course_id.strip()
        if not course_id:
            raise ValueError("course_id must not be empty")
        selected = {course_id: student_courses.get(course_id)}
    else:
        selected = student_courses

    result: list[dict[str, Any]] = []
    for cid, course in selected.items():
        submissions = await asyncio.to_thread(_course_submissions, connection, cid)
        course_name = (course.full_name or course.name) if course is not None else None
        for submission in submissions:
            result.append({"course": course_name, **submission})
    return result


@mcp.tool(
    name="gradescope_get_submission_files",
    annotations={
        "title": "Get my Gradescope submission files",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def gradescope_get_submission_files(
    course_id: str,
    assignment_id: str,
    submission_id: str,
) -> dict[str, Any]:
    """
    Return safe metadata for files in one of the authenticated student's submissions.

    Temporary signed Gradescope/S3 URLs are intentionally not returned. Use
    gradescope_download_submission_file to retrieve a file.
    """
    connection = await _connection_or_login()
    payload = await asyncio.to_thread(
        _submission_payload, connection, course_id, assignment_id, submission_id
    )
    files = _resolved_submission_files(payload)
    submission = payload.get("assignment_submission") or payload
    return {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "submission_id": submission_id,
        "created_at": submission.get("created_at") if isinstance(submission, dict) else None,
        "status": submission.get("status") if isinstance(submission, dict) else None,
        "files": [{k: v for k, v in item.items() if k != "url"} for item in files],
    }


@mcp.tool(
    name="gradescope_download_submission_file",
    annotations={
        "title": "Download my Gradescope submission file",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def gradescope_download_submission_file(
    course_id: str,
    assignment_id: str,
    submission_id: str,
    file_ref: str,
    destination_dir: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Download one of the authenticated student's own submitted files locally.

    This does not modify Gradescope. It creates a file on the machine running
    the MCP server. `file_ref` comes from gradescope_get_submission_files.
    """
    connection = await _connection_or_login()
    payload = await asyncio.to_thread(
        _submission_payload, connection, course_id, assignment_id, submission_id
    )
    files = _resolved_submission_files(payload)
    selected = next((item for item in files if item["file_ref"] == file_ref), None)
    if selected is None:
        raise ValueError(f"Unknown file_ref: {file_ref}")

    directory = Path(destination_dir).expanduser().resolve()
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    filename = Path(str(selected["filename"])).name
    output = directory / filename
    if output.exists() and not overwrite:
        raise FileExistsError(f"File already exists: {output}")

    response = await asyncio.to_thread(connection.session.get, selected["url"])
    response.raise_for_status()
    await asyncio.to_thread(output.write_bytes, response.content)
    return {
        "saved_to": str(output),
        "filename": filename,
        "bytes": len(response.content),
    }


def _load_environment(env_file: str | None) -> None:
    """Load credentials without overriding variables already supplied by the parent process."""
    if env_file:
        path = Path(env_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Environment file not found: {path}")
        load_dotenv(path, override=False)
        return

    # Convenience for a local clone. This intentionally checks only the current
    # working directory; it never searches the user's home directory.
    local_env = Path.cwd() / ".env"
    if local_env.is_file():
        load_dotenv(local_env, override=False)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--env-file",
        help="Optional path to a dotenv file containing GRADESCOPE_EMAIL and GRADESCOPE_PASSWORD.",
    )
    args = parser.parse_args()
    _load_environment(args.env_file)
    mcp.run()


if __name__ == "__main__":
    main()
