"""Neural ML layer configuration endpoints.

GET  /api/v1/settings/neural         — current config + model status
PUT  /api/v1/settings/neural         — update tunable parameters
POST /api/v1/settings/neural/train   — trigger scorer retraining
GET  /api/v1/settings/neural/train   — training job status
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import require_permission, AuthContext

router = APIRouter(prefix="/api/v1/settings/neural", tags=["Neural"])

# ---------------------------------------------------------------------------
# In-process training job state (single-worker; gunicorn multi-worker users
# should use the train_scorer.py CLI directly and reload the scorer).
# ---------------------------------------------------------------------------
_train_job: dict[str, Any] = {"status": "idle", "started_at": None, "log": "", "pid": None}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NeuralSettingsUpdate(BaseModel):
    scorer_path: str | None = None
    log_path: str | None = None
    log_paths: str | None = None       # colon-separated
    tail_lines: int | None = None
    anomaly_threshold: float | None = None
    contamination: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model_status() -> dict:
    path = str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None
    if not path:
        return {"present": False, "path": None, "size_kb": None, "mtime": None}
    if not os.path.isfile(path):
        return {"present": False, "path": path, "size_kb": None, "mtime": None}
    stat = os.stat(path)
    return {
        "present": True,
        "path": path,
        "size_kb": round(stat.st_size / 1024, 1),
        "mtime": stat.st_mtime,
    }


def _current_threshold_contamination() -> tuple[float, float]:
    """Read threshold/contamination from the live scorer if available."""
    path = str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None
    if path and os.path.isfile(path):
        try:
            import pickle
            with open(path, "rb") as f:
                data = pickle.load(f)
            return (
                float(data.get("anomaly_threshold", -0.05)),
                float(data.get("contamination", 0.1)),
            )
        except Exception:
            pass
    return -0.05, 0.1


# ---------------------------------------------------------------------------
# GET /settings/neural
# ---------------------------------------------------------------------------

@router.get("")
async def get_neural_settings(
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    threshold, contamination = _current_threshold_contamination()
    return {
        "scorer_path": str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None,
        "log_path": str(settings.ML_LOG_PATH) if settings.ML_LOG_PATH else None,
        "log_paths": settings.ML_LOG_PATHS,
        "tail_lines": settings.ML_TAIL_LINES,
        "anomaly_threshold": threshold,
        "contamination": contamination,
        "model": _model_status(),
        "training": _train_job,
    }


# ---------------------------------------------------------------------------
# PUT /settings/neural
# ---------------------------------------------------------------------------

@router.put("")
async def update_neural_settings(
    body: NeuralSettingsUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    if body.scorer_path is not None:
        settings.ML_SCORER_PATH = body.scorer_path or None  # type: ignore[assignment]
    if body.log_path is not None:
        settings.ML_LOG_PATH = body.log_path or None  # type: ignore[assignment]
    if body.log_paths is not None:
        settings.ML_LOG_PATHS = body.log_paths or None
    if body.tail_lines is not None:
        if body.tail_lines < 100:
            raise HTTPException(400, "tail_lines must be ≥ 100")
        settings.ML_TAIL_LINES = body.tail_lines

    # threshold / contamination are stored in the .pkl — patch it in-place
    if (body.anomaly_threshold is not None or body.contamination is not None) and settings.ML_SCORER_PATH:
        path = str(settings.ML_SCORER_PATH)
        if os.path.isfile(path):
            try:
                import pickle
                with open(path, "rb") as f:
                    data = pickle.load(f)
                if body.anomaly_threshold is not None:
                    data["anomaly_threshold"] = body.anomaly_threshold
                    if data.get("forest"):
                        data["forest"].contamination = data.get("contamination", 0.1)
                if body.contamination is not None:
                    if not (0.01 <= body.contamination <= 0.49):
                        raise HTTPException(400, "contamination must be between 0.01 and 0.49")
                    data["contamination"] = body.contamination
                with open(path, "wb") as f:
                    pickle.dump(data, f)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(500, f"Failed to patch scorer: {e}")

    from app.services.audit import audit_event
    from app.core.database import async_session
    async with async_session() as db:
        await audit_event(
            db=db,
            event_type="NEURAL_SETTINGS_UPDATED",
            severity="INFO",
            request=request,
            subject_type="settings",
            subject_id="neural",
            description="Neural ML settings updated",
        )
        await db.commit()

    threshold, contamination = _current_threshold_contamination()
    return {
        "status": "updated",
        "scorer_path": str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None,
        "log_path": str(settings.ML_LOG_PATH) if settings.ML_LOG_PATH else None,
        "log_paths": settings.ML_LOG_PATHS,
        "tail_lines": settings.ML_TAIL_LINES,
        "anomaly_threshold": threshold,
        "contamination": contamination,
        "model": _model_status(),
    }


# ---------------------------------------------------------------------------
# POST /settings/neural/train  — kick off a training run
# ---------------------------------------------------------------------------

class TrainRequest(BaseModel):
    epochs: int = 40
    contamination: float | None = None
    threshold: float = -0.05
    log_path: str | None = None
    evaluate: bool = False


@router.post("/train")
async def trigger_training(
    body: TrainRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    global _train_job

    if _train_job["status"] == "running":
        raise HTTPException(409, "A training job is already running")

    output_path = str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else "/data/models/anomaly_scorer.pkl"

    # Locate train_scorer.py — it ships with Neural
    neural_root = os.environ.get("NEURAL_ROOT", "/opt/certmanager/Neural")
    train_script = os.path.join(neural_root, "train_scorer.py")
    if not os.path.isfile(train_script):
        raise HTTPException(404, f"train_scorer.py not found at {train_script}. Set NEURAL_ROOT env var.")

    cmd = [
        sys.executable, train_script,
        "--output", output_path,
        "--epochs", str(body.epochs),
        "--threshold", str(body.threshold),
    ]
    if body.contamination is not None:
        cmd += ["--contamination", str(body.contamination)]
    if body.log_path:
        cmd += ["--log-path", body.log_path]
    if body.evaluate:
        cmd.append("--evaluate")

    _train_job = {"status": "running", "started_at": time.time(), "log": "", "pid": None}

    async def _run() -> None:
        global _train_job
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            _train_job["pid"] = proc.pid
            stdout, _ = await proc.communicate()
            log = stdout.decode(errors="replace")
            _train_job["log"] = log
            _train_job["status"] = "completed" if proc.returncode == 0 else "failed"
            _train_job["return_code"] = proc.returncode
            _train_job["finished_at"] = time.time()
        except Exception as e:
            _train_job["status"] = "failed"
            _train_job["log"] = str(e)
            _train_job["finished_at"] = time.time()

    asyncio.create_task(_run())

    from app.services.audit import audit_event
    from app.core.database import async_session
    async with async_session() as db:
        await audit_event(
            db=db,
            event_type="NEURAL_TRAINING_STARTED",
            severity="INFO",
            request=request,
            subject_type="neural",
            subject_id="scorer",
            description=f"Neural scorer training started (epochs={body.epochs}, output={output_path})",
        )
        await db.commit()

    return {"status": "started", "output_path": output_path, "command": cmd}


# ---------------------------------------------------------------------------
# GET /settings/neural/train  — poll training status
# ---------------------------------------------------------------------------

@router.get("/train")
async def get_training_status(
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    return dict(_train_job)
