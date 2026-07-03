"""Packaging contract — pyproject.toml hợp lệ PEP 621 + workspace root có members.

Codify các blocking bug đã gặp: thiếu `[project]` table, thiếu `[tool.uv.workspace]`,
thiếu `py.typed` (khiến mypy strict bỏ qua type cross-package).
"""

from __future__ import annotations

from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def _member_pyprojects() -> list[Path]:
    return [
        *sorted((ROOT / "apps").glob("*/pyproject.toml")),
        *sorted((ROOT / "libs").glob("*/pyproject.toml")),
    ]


def test_all_members_have_project_table() -> None:
    for p in _member_pyprojects():
        data = tomllib.loads(p.read_text())
        assert "project" in data, f"{p} thiếu [project] table (PEP 621)"
        assert data["project"].get("name"), f"{p} thiếu project.name"
        assert data["project"].get("version"), f"{p} thiếu project.version"


def test_root_declares_uv_workspace() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    members = data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members")
    assert members, "root pyproject.toml thiếu [tool.uv.workspace] members"
    assert "apps/*" in members and "libs/*" in members


def test_each_pipeline_app_declares_console_script() -> None:
    # `service` là ASGI app (chạy qua uvicorn), không có console-script — loại trừ.
    for p in sorted((ROOT / "apps").glob("*/pyproject.toml")):
        if p.parent.name == "service":
            continue
        data = tomllib.loads(p.read_text())
        assert data["project"].get("scripts"), (
            f"{p} (pipeline app) thiếu [project.scripts] entrypoint"
        )


def test_common_ships_py_typed() -> None:
    marker = ROOT / "libs" / "common" / "src" / "crawl_datasets_common" / "py.typed"
    assert marker.exists(), (
        "libs/common thiếu py.typed → mypy strict bỏ qua type cross-package"
    )
