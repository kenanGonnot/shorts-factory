import uuid
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import Base, engine, get_db
from app.core.logging import setup_logging, log
from app.models import VideoJob
from app.workers.tasks import run_pipeline_task

setup_logging()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Shorts Factory")


class GenerateRequest(BaseModel):
    topic: str


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())
    job = VideoJob(id=job_id, topic=req.topic, status="pending")
    db.add(job)
    db.commit()
    run_pipeline_task.delay(job_id, req.topic)
    log.info("job.queued", job_id=job_id, topic=req.topic)
    return GenerateResponse(job_id=job_id, status="pending")


@app.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404)
    return {
        "id": job.id,
        "topic": job.topic,
        "status": job.status,
        "youtube_id": job.youtube_id,
        "error": job.error,
        "payload": job.payload,
    }


@app.get("/health")
def health():
    return {"ok": True}
