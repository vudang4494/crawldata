"""Entrypoint smoke tests — mỗi stage CLI chạy được (skeleton), không crash.

Bắt các regression kiểu truy cập LicenseTag như Enum attribute (probe crash
runtime) trước khi merge,
và verify các fail-closed guard chạy đúng ở runtime (§2, §5.4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


def test_probe_runs_and_tags_unknown_license(tmp_path: Path) -> None:
    """§2 — probe tag license:unknown (giữ raw tier audit), KHÔNG được crash."""
    from crawl_datasets_probe.__main__ import main

    out = tmp_path / "probe"
    res = CliRunner().invoke(main, ["--url", "https://example.com", "--out", str(out)])
    assert res.exit_code == 0, res.output
    profile = json.loads((out / "source_profile.json").read_text())
    assert profile["license"] == "unknown"


def test_extractor_runs(tmp_path: Path) -> None:
    from crawl_datasets_extractor.__main__ import main

    res = CliRunner().invoke(
        main, ["--in", str(tmp_path / "raw"), "--out", str(tmp_path / "o")]
    )
    assert res.exit_code == 0, res.output


def test_cleaner_runs(tmp_path: Path) -> None:
    from crawl_datasets_cleaner.__main__ import main

    res = CliRunner().invoke(
        main, ["--in", str(tmp_path / "ex"), "--out", str(tmp_path / "o")]
    )
    assert res.exit_code == 0, res.output


def test_builder_runs(tmp_path: Path) -> None:
    from crawl_datasets_builder.__main__ import main

    res = CliRunner().invoke(
        main, ["--in", str(tmp_path / "cl"), "--out", str(tmp_path / "o")]
    )
    assert res.exit_code == 0, res.output


def test_profiler_runs(tmp_path: Path) -> None:
    from crawl_datasets_profiler.__main__ import main

    res = CliRunner().invoke(
        main, ["--in", str(tmp_path / "cl"), "--out", str(tmp_path / "o")]
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "o" / "profile_report.json").exists()


def test_integrator_runs(tmp_path: Path) -> None:
    from crawl_datasets_integrator.__main__ import main

    res = CliRunner().invoke(
        main,
        [
            "--base",
            str(tmp_path / "b"),
            "--new",
            str(tmp_path / "n"),
            "--out",
            str(tmp_path / "o"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "o" / "mix_manifest.json").exists()


def test_crawler_runs_with_default_config(tmp_path: Path) -> None:
    from crawl_datasets_crawler.__main__ import main

    res = CliRunner().invoke(
        main, ["--seeds", "https://example.com", "--out", str(tmp_path / "o")]
    )
    assert res.exit_code == 0, res.output


def test_crawler_fail_closed_when_robots_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2 fail-closed — crawler phải từ chối chạy khi respect_robots=false."""
    from crawl_datasets_crawler.__main__ import main

    cfg = tmp_path / "bad.yaml"
    cfg.write_text(yaml.safe_dump({"crawl": {"respect_robots": False}}))
    monkeypatch.setenv("CDS_CONFIG", str(cfg))

    res = CliRunner().invoke(
        main, ["--seeds", "https://x", "--out", str(tmp_path / "o")]
    )
    assert res.exit_code != 0  # SystemExit — fail-closed, không được PASS
