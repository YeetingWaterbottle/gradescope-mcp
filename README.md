# Gradescope MCP

A lightweight, read-only MCP server for Gradescope. It provides student-focused
access to courses, assignments, deadlines, submission history, and uploaded
submission files through a small set of MCP tools.

The server is built on
[`gradescopeapi`](https://github.com/nyuoss/gradescope-api) and does not expose
Gradescope write operations. Downloading a submitted file only creates a local
copy; it does not modify anything on Gradescope.

## Features

- `gradescope_list_courses` — courses visible to the account
- `gradescope_list_assignments` — exact assignment dates, status, and grades for one course
- `gradescope_upcoming_assignments` — upcoming work across student courses, sorted by due time
- `gradescope_list_submissions` — the authenticated student's submitted assignments
- `gradescope_get_submission_files` — filenames and metadata for the student's own uploaded files
- `gradescope_download_submission_file` — download one of those files to the local machine

The server does not upload submissions or expose grading, roster management,
extension management, or other Gradescope write operations.

> Gradescope does not provide an official public student API. `gradescopeapi`
> works by parsing Gradescope pages, so site changes can occasionally require
> a library update.

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- A Gradescope email/password login

If you normally enter Gradescope only through university SSO, create a native
Gradescope password using Gradescope's password-reset flow. Do not store your
university SSO password here.

## Setup

```bash
git clone https://github.com/YeetingWaterbottle/gradescope-mcp.git
cd gradescope-mcp
uv sync --no-dev
```

Create a local credential file from the example:

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```env
GRADESCOPE_EMAIL="student@example.com"
GRADESCOPE_PASSWORD="your-native-gradescope-password"
```

`.env` is ignored by Git.

Run the server:

```bash
uv run gradescope-mcp
```

When `.env` is in the current working directory it is loaded automatically.
You can instead keep credentials elsewhere:

```bash
uv run gradescope-mcp --env-file /absolute/path/to/gradescope.env
```

PowerShell example:

```powershell
uv run gradescope-mcp --env-file C:\Users\you\.config\gradescope.env
```

Environment variables supplied by the parent process take precedence over
values in the dotenv file.

## Run directly from GitHub

Run the server directly from GitHub with `uvx`:

```bash
uvx --from git+https://github.com/YeetingWaterbottle/gradescope-mcp.git gradescope-mcp --env-file /absolute/path/to/gradescope.env
```

## MCP client configuration

The exact UI varies by client. A generic stdio configuration using the public
GitHub repository is:

```json
{
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/YeetingWaterbottle/gradescope-mcp.git",
    "gradescope-mcp",
    "--env-file",
    "/absolute/path/to/gradescope.env"
  ]
}
```

On Windows, use normal JSON escaping for the credential path, for example
`"C:\\Users\\you\\.config\\gradescope.env"`.

`examples/chat-on-steroids.json` contains the same configuration as a reusable
template. Replace the credential-file path with an absolute path on your
machine.

## Tools

### `gradescope_list_courses`

Returns courses grouped by role (`student` / `instructor`) with Gradescope
course IDs and term information.

### `gradescope_list_assignments`

Input:

```json
{"course_id": "123456"}
```

Returns assignment ID, name, release time, due time, late due time, status,
grade, and maximum grade.

The `status` field is **Gradescope's own displayed status**. The MCP does not
reinterpret it. If Gradescope displays `Submitted`, the tool returns
`Submitted`.

### `gradescope_upcoming_assignments`

Input:

```json
{"days": 14}
```

Aggregates assignments from all student courses and returns those due within
the requested window, sorted by exact due timestamp. The accepted range is
1–365 days.

### `gradescope_list_submissions`

Optionally accepts a `course_id`. If omitted, it lists the authenticated
student's submissions across all student courses. The result includes the
assignment and submission IDs needed to inspect attached files.

### `gradescope_get_submission_files`

Given a course, assignment, and submission ID, returns safe file metadata such
as filename, type, page count, and a short `file_ref`.

Gradescope's temporary signed storage URLs are deliberately kept inside the MCP
server rather than exposed in model context.

PDF/image-style homework submissions and Gradescope text/source-file
submissions are supported when Gradescope exposes them to the authenticated
student. Online-form assignments naturally return an empty file list.

### `gradescope_download_submission_file`

Downloads one file identified by `file_ref` to a directory on the machine
running the MCP server. It never changes Gradescope. By default it refuses to
overwrite an existing local file.

## Read-only design

The project exposes only student-focused read operations against Gradescope.
Instructor-oriented and write operations such as roster management, grading,
extensions, assignment configuration, and submission uploads are not included.

## Development

```bash
uv sync --all-groups
uv run pytest
```

CI runs on Linux, macOS, and Windows with Python 3.11–3.13.

## Security

- Never commit `.env`.
- Prefer a Gradescope-specific/native password rather than reusing an important password.
- Keep credential files readable only by your user where your OS supports that.
- The MCP exposes only read operations against Gradescope, but the credentials still represent your account and should be protected accordingly.

## License

MIT. See `LICENSE`.
