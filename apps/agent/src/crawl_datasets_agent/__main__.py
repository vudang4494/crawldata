"""Agent intake CLI (§14) — URL + nhu cầu → hỏi-đáp → DatasetPlan → S1→S5.

Logic thật ở `intake.py`/`run_plan.py`; file này chỉ wiring CLI + vòng
hỏi-đáp terminal + human-in-the-loop confirm trước khi chạy pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings
from crawl_datasets_probe.pipeline import run as probe_run

from .intake import IntakeSession
from .llm import ChatLLM
from .run_plan import execute_plan

log = get_logger("agent")


@click.command()
@click.option("--url", required=True, help="URL nguồn cần phân tích")
@click.option("--need", required=True, help="Nhu cầu phân tích / mục tiêu dataset")
@click.option("--out", required=True, type=click.Path(path_type=Path))
@click.option("--yes", is_flag=True, help="Chạy pipeline ngay, bỏ bước confirm plan")
def main(url: str, need: str, out: Path, yes: bool) -> None:
    """Agent (§14): phân tích URL theo nhu cầu → DatasetPlan → chạy pipeline."""
    configure_logging()
    settings = load_settings()
    log.info("agent_start", url=url, model=settings.agent.model)

    profile = probe_run(url, out / "s0", settings)  # S0 trước — agent đọc profile
    session = IntakeSession(
        url, need, profile, ChatLLM(settings.agent),
        max_rounds=settings.agent.max_rounds,
    )

    step = session.start()
    while not step.done:
        click.echo("Agent cần thêm thông tin:")
        answers = [click.prompt(f"  ? {q}") for q in step.questions]
        step = session.answer(answers)

    plan = step.plan
    assert plan is not None  # step.done đảm bảo
    out.mkdir(parents=True, exist_ok=True)
    (out / "dataset_plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    click.echo("=== DatasetPlan (đã lưu dataset_plan.json) ===")
    click.echo(plan.model_dump_json(indent=2))

    if not yes and not click.confirm("Chạy pipeline S1→S5 với plan này?"):
        click.echo("Đã dừng — plan giữ nguyên để chỉnh/chạy sau.")
        return

    summary = execute_plan(plan, settings, out)
    log.info(
        "agent_done",
        fetched=summary["fetched"],
        kept=summary["kept"],
        built=summary["built"],
    )
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
