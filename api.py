"""
FastAPI server – Agent Épicerie Gatineau
POST /run      → lance le scraping + planification en arrière-plan
GET  /status/{job_id} → résultat ou statut en cours
GET  /health   → healthcheck Render
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from output.formatter import format_grocery_list
from planner.meal_planner import MealPlanner
from scraper.filters import apply_all as apply_filters
from scraper.flipp import FlippScraper

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Agent Épicerie Gatineau", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Stockage en mémoire des jobs
jobs: dict[str, dict[str, Any]] = {}

# Verrou : 1 seul job à la fois (mémoire limitée sur Render free)
_job_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _run_job(job_id: str, postal_code: str, max_flyers: int) -> None:
    acquired = _job_lock.acquire(blocking=False)
    if not acquired:
        jobs[job_id] = {
            "status": "error",
            "result": "Un autre job est déjà en cours. Attends qu'il se termine et réessaie.",
        }
        return

    try:
        # Étape 1 : scraping
        jobs[job_id]["step"] = "Scraping Flipp..."
        scraper = FlippScraper(postal_code=postal_code)
        deals = scraper.get_all_deals(max_flyers=max_flyers)

        # Étape 2 : filtres géo + rabais fruits/légumes
        jobs[job_id]["step"] = "Application des filtres..."
        filtered, stats = apply_filters(
            deals,
            nearby_stores=config.NEARBY_GROCERY_STORES,
            veg_fruit_min_savings_pct=config.VEG_FRUIT_MIN_SAVINGS_PCT,
        )

        if not filtered:
            jobs[job_id] = {
                "status": "error",
                "result": "Aucun deal trouvé après filtres.",
            }
            return

        # Étape 3 : planification Claude
        jobs[job_id]["step"] = f"Planification Claude ({stats['final']} deals)..."
        plan = MealPlanner().plan(filtered)

        # Étape 4 : formatage
        output = format_grocery_list(plan)

        jobs[job_id] = {"status": "done", "result": output}

    except Exception as exc:
        jobs[job_id] = {"status": "error", "result": f"Erreur: {exc}"}

    finally:
        _job_lock.release()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    running = any(j["status"] == "running" for j in jobs.values())
    return {"status": "ok", "job_running": running}


@app.post("/run")
def run(
    background_tasks: BackgroundTasks,
    postal_code: str = config.POSTAL_CODE,
    max_flyers: int = config.MAX_FLYERS,
) -> dict:
    # Rejeter si un job tourne déjà
    if any(j["status"] == "running" for j in jobs.values()):
        raise HTTPException(
            status_code=429,
            detail="Un job est déjà en cours. Attends qu'il se termine.",
        )
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "result": None, "step": "Démarrage..."}
    background_tasks.add_task(_run_job, job_id, postal_code, max_flyers)
    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        return {"status": "error", "result": "Job introuvable (serveur redémarré ?)."}
    return job


# ---------------------------------------------------------------------------
# Static files (après les routes pour ne pas masquer /health etc.)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")
