"""CLI: python -m scripts.run_pipeline "Why coffee makes you focus" """
import sys, uuid
import typer

from app.core.logging import setup_logging, log
from app.chains.pipeline import build_pipeline

cli = typer.Typer(add_completion=False)


@cli.command()
def run(topic: str):
    setup_logging()
    pipeline = build_pipeline()
    job_id = f"cli-{uuid.uuid4().hex[:8]}"
    log.info("cli.start", job_id=job_id, topic=topic)
    out = pipeline.invoke({"job_id": job_id, "topic": topic})
    log.info(
        "cli.done",
        job_id=job_id,
        youtube_id=out.get("youtube_id"),
        final=out.get("final_path"),
    )
    typer.echo(out.get("final_path") or "no output")


if __name__ == "__main__":
    cli()
