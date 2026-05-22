"""
FastAPI server – Agent Épicerie Gatineau
POST /run      → lance le scraping + planification en arrière-plan
GET  /status/{job_id} → résultat ou statut en cours
GET  /health   → healthcheck Render
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI
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

# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _run_job(job_id: str, postal_code: str, max_flyers: int) -> None:
    try:
        # Étape 1 : scraping
        scraper = FlippScraper(postal_code=postal_code)
        deals = scraper.get_all_deals(max_flyers=max_flyers)

        # Étape 2 : filtres géo + rabais fruits/légumes
        filtered, _ = apply_filters(
            deals,
            nearby_stores=config.NEARBY_GROCERY_STORES,
            veg_fruit_min_savings_pct=config.VEG_FRUIT_MIN_SAVINGS_PCT,
        )

        if not filtered:
            jobs[job_id] = {
                "status": "error",
                "result": "Aucun deal trouvé après filtres. Vérifiez NEARBY_GROCERY_STORES dans config.py.",
            }
            return

        # Étape 3 : planification Claude
        plan = MealPlanner().plan(filtered)

        # Étape 4 : formatage
        output = format_grocery_list(plan)

        jobs[job_id] = {"status": "done", "result": output}

    except Exception as exc:
        jobs[job_id] = {"status": "error", "result": f"Erreur: {exc}"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/run")
def run(
    background_tasks: BackgroundTasks,
    postal_code: str = config.POSTAL_CODE,
    max_flyers: int = config.MAX_FLYERS,
) -> dict:
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "result": None}
    background_tasks.add_task(_run_job, job_id, postal_code, max_flyers)
    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        return {"status": "error", "result": "Job introuvable."}
    return job


# ---------------------------------------------------------------------------
# Static files (après les routes pour ne pas masquer /health etc.)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")
