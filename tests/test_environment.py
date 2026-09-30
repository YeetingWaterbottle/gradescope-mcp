from pathlib import Path

from gradescope_mcp.server import _load_environment, _resolved_submission_files


def test_load_environment_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GRADESCOPE_EMAIL", raising=False)
    monkeypatch.delenv("GRADESCOPE_PASSWORD", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GRADESCOPE_EMAIL="student@example.com"\n'
        'GRADESCOPE_PASSWORD="abc\'123"\n',
        encoding="utf-8",
    )

    _load_environment(str(env_file))

    import os

    assert os.environ["GRADESCOPE_EMAIL"] == "student@example.com"
    assert os.environ["GRADESCOPE_PASSWORD"] == "abc'123"


def test_resolved_submission_files_hides_nothing_internally() -> None:
    payload = {
        "pdf_attachment": {
            "filename": "homework.pdf",
            "page_count": 4,
            "url": "https://example.invalid/signed-pdf",
        },
        "text_files": [
            {
                "file": {
                    "filename": "main.py",
                    "url": "https://example.invalid/signed-source",
                }
            }
        ],
    }

    files = _resolved_submission_files(payload)

    assert files[0]["file_ref"] == "pdf"
    assert files[0]["filename"] == "homework.pdf"
    assert files[1]["file_ref"] == "text:0"
    assert files[1]["filename"] == "main.py"
