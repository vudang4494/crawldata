"""Bộ verify tường minh cho verify-design-spec — mỗi rule 1 case PASS/FAIL.

Fail-closed cho chính verifier (§0): fixture sạch → exit 0, fixture chứa
anti-pattern → exit 2, `.venv`/cache bị walker skip, verifier không tự flag
chính nó. Fixture "xấu" được ghép chuỗi runtime để file test này không chứa
nguyên văn pattern (verifier scan cả tests/).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / ".claude" / "skills" / "verify-design-spec" / "verify.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="cần node để chạy verify.mjs")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(  # noqa: S603
        [NODE, str(VERIFY), *args], capture_output=True, text=True, timeout=60
    )


def test_spec_audit_passes() -> None:
    """V2 — spec là source of truth, audit no-arg phải sạch."""
    res = _run()
    assert res.returncode == 0, res.stdout + res.stderr


def test_repo_wide_scan_is_clean() -> None:
    """V3 — toàn repo không vi phạm rule nào (0 false positive)."""
    res = _run("--target", str(ROOT))
    assert res.returncode == 0, res.stdout


def test_clean_target_passes(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "from crawl_datasets_common.schema import UNKNOWN_LICENSE\n"
        "license_tag = UNKNOWN_LICENSE\n"
    )
    res = _run("--target", str(tmp_path))
    assert res.returncode == 0, res.stdout


# Mỗi entry = 1 rule trong bảng `violations` của verify.mjs (file .py).
BAD_CODE_CASES = {
    "load_all": 'rows = load_dataset("x")' + ".to_list()\n",
    "beautifulsoup": "from bs4 import Beautiful" + "Soup\n",
    "bare_except_pass": "try:\n    x()\nexcept Exce" + "ption:\n    pass\n",
    "license_unknown_literal": 'rec = {"license": "unk' + 'nown"}\n',
    "nfkd": 'normalize = "NF' + 'KD"\n',
    "cld3": 'lang_id = "cl' + 'd3"\n',
    "licensetag_attr": "tag = LicenseTag" + ".unknown\n",
}


@pytest.mark.parametrize("name", sorted(BAD_CODE_CASES))
def test_bad_code_fails(tmp_path: Path, name: str) -> None:
    (tmp_path / f"{name}.py").write_text(BAD_CODE_CASES[name])
    res = _run("--target", str(tmp_path))
    assert res.returncode == 2, f"{name}: verifier phải exit 2\n{res.stdout}"


# Mỗi entry = 1 rule trong bảng `cfgViolations` (file .yaml/.toml).
BAD_CFG_CASES = {
    "minhash_scope_global": "minhash:\n  scope: glo" + "bal\n",
    "robots_off": "crawl:\n  respect_robots: fal" + "se\n",
}


@pytest.mark.parametrize("name", sorted(BAD_CFG_CASES))
def test_bad_config_fails(tmp_path: Path, name: str) -> None:
    (tmp_path / f"{name}.yaml").write_text(BAD_CFG_CASES[name])
    res = _run("--target", str(tmp_path))
    assert res.returncode == 2, f"{name}: verifier phải exit 2\n{res.stdout}"


def test_pyproject_missing_project_table_fails(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n')
    res = _run("--target", str(tmp_path))
    assert res.returncode == 2, res.stdout


def test_venv_and_caches_are_skipped(tmp_path: Path) -> None:
    """Walker bỏ qua env/cache — nguồn false positive khi scan repo-wide."""
    bad = "try:\n    x()\nexcept Exce" + "ption:\n    pass\n"
    for d in (".venv/lib", "venv", "__pycache__", ".mypy_cache", "build", "data"):
        p = tmp_path / d
        p.mkdir(parents=True)
        (p / "bad.py").write_text(bad)
    res = _run("--target", str(tmp_path))
    assert res.returncode == 0, res.stdout


def test_verifier_does_not_flag_itself() -> None:
    """Bảng rule của verify.mjs chứa anti-pattern mẫu — phải self-exclude."""
    res = _run("--target", str(VERIFY.parent))
    assert res.returncode == 0, res.stdout
