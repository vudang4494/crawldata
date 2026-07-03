"""Packaging contract — pyproject.toml hợp lệ PEP 621 + workspace root có members.

Codify các blocking bug đã gặp: thiếu `[project]` table, thiếu `[tool.uv.workspace]`,
thiếu `py.typed` (khiến mypy strict bỏ qua type cross-package).
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def _member_pyprojects() -> list[Path]:
    return [
        *sorted((ROOT / "apps").glob("*/pyproject.toml")),
        *sorted((ROOT / "libs").glob("*/pyproject.toml")),
    ]


def _package_names() -> set[str]:
    return {
        tomllib.loads(p.read_text())["project"]["name"] for p in _member_pyprojects()
    }


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


# Backend nặng theo gated-backend pattern (CLAUDE.md) — chỉ được là extra.
HEAVY_OPTIONAL_BACKENDS = {
    "umap-learn",
    "hdbscan",
    "numba",
    "llvmlite",
    "sentence-transformers",
    "flagembedding",
    "torch",
    "playwright",
}


def _dep_name(spec: str) -> str:
    return re.split(r"[\s\[<>=!~;]", spec, maxsplit=1)[0].lower()


def test_heavy_backends_are_extras_not_base_deps() -> None:
    """Dep nặng phải nằm trong optional-dependencies, không phải base deps.

    Bắt bug: profiler khai umap-learn/hdbscan làm base dep → universal
    resolution kéo llvmlite 0.36 (sdist-only) → `uv sync`/`uv run` vỡ build
    trên Python 3.13 dù code không hề import chúng (clustering là P1 hook).
    """
    for p in _member_pyprojects():
        deps = tomllib.loads(p.read_text())["project"].get("dependencies", [])
        heavy = {_dep_name(d) for d in deps} & HEAVY_OPTIONAL_BACKENDS
        assert not heavy, f"{p}: {sorted(heavy)} phải là extra, không phải base dep"


def test_uv_run_package_refs_are_real_packages() -> None:
    """`uv run --package X` phải trỏ tên package thật (không phải tên thư mục).

    Bắt bug: dvc.yaml/Makefile dùng `--package probe` trong khi package tên
    `crawl-datasets-probe` → uv báo 'workspace does not have a member probe'.
    """
    names = _package_names()
    rx = re.compile(r"--package\s+(\S+)")
    for f in ["dvc.yaml", "Makefile"]:
        for pkg in rx.findall((ROOT / f).read_text()):
            assert pkg in names, f"{f}: --package {pkg} không phải package thật"
