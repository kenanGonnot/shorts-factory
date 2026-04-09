from app.workers.celery_app import celery_app
from app.core.db import SessionLocal
from app.core.logging import setup_logging, log
from app.models import VideoJob
from app.chains.pipeline import build_pipeline
from app.chains.state import PipelineState

setup_logging()


@celery_app.task(name="run_pipeline")
def run_pipeline_task(job_id: str, topic: str) -> dict:
    db = SessionLocal()
    job = db.get(VideoJob, job_id)
    if job is None:
        log.error("job.missing", job_id=job_id)
        return {"ok": False}

    job.status = "running"
    db.commit()

    pipeline = build_pipeline()
    state: PipelineState = {"job_id": job_id, "topic": topic}

    try:
        result = pipeline.invoke(state)
        job.status = "done"
        job.youtube_id = result.get("youtube_id")
        job.payload = {
            "script": result.get("script"),
            "final_path": result.get("final_path"),
        }
        db.commit()
        return {"ok": True, "youtube_id": result.get("youtube_id")}
    except Exception as e:
        log.exception("pipeline.failed", job_id=job_id, error=str(e))
        job.status = "failed"
        job.error = str(e)
        db.commit()
        raise
    finally:
        db.close()
