"""
FastAPI server – Agent Épicerie Gatineau
POST /run            → lance le scraping + planification en arrière-plan
GET  /status/{job_id} → résultat ou statut en cours
GET  /health         → healthcheck Render
"""

from __future__ import annotations

import gc
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
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

# 1 seul job à la fois (mémoire limitée sur Render free)
_job_lock = threading.Lock()

# Timeouts
SCRAPE_TIMEOUT_SEC  = 600   # 10 min max pour le scraping
CLAUDE_TIMEOUT_SEC  = 300   #  5 min max pour l'appel Claude

# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _run_job(job_id: str, postal_code: str, max_flyers: int) -> None:
    acquired = _job_lock.acquire(blocking=False)
    if not acquired:
        jobs[job_id] = {
            "status": "error",
            "result": "Un job est déjà en cours. Attends qu'il se termine.",
        }
        return

    try:
        # ── Étape 1 : scraping avec timeout ──────────────────────────────
        jobs[job_id]["step"] = "Scraping Flipp (2-3 min)..."
        print(f"[{job_id[:8]}] Démarrage scraping postal={postal_code} max_flyers={max_flyers}")

        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                lambda: FlippScraper(postal_code=postal_code).get_all_deals(max_flyers=max_flyers)
            )
            try:
                deals = future.result(timeout=SCRAPE_TIMEOUT_SEC)
            except FuturesTimeout:
                jobs[job_id] = {"status": "error", "result": "Timeout scraping (10 min dépassées)."}
                return

        print(f"[{job_id[:8]}] {len(deals)} deals bruts")

        # ── Étape 2 : filtres ────────────────────────────────────────────
        jobs[job_id]["step"] = "Filtres géographiques..."
        filtered, stats = apply_filters(
            deals,
            nearby_stores=config.NEARBY_GROCERY_STORES,
            veg_fruit_min_savings_pct=config.VEG_FRUIT_MIN_SAVINGS_PCT,
        )
        print(f"[{job_id[:8]}] {stats['final']} deals après filtres")

        if not filtered:
            jobs[job_id] = {
                "status": "error",
                "result": "Aucun deal trouvé après filtres.",
            }
            return

        # ── Étape 3 : libération mémoire avant appel Claude ──────────────
        deal_count = len(deals)
        del deals
        gc.collect()
        print(f"[{job_id[:8]}] Mémoire libérée (deals supprimés), envoi Claude...")

        # ── Étape 4 : Claude avec timeout ────────────────────────────────
        jobs[job_id]["step"] = f"Claude planifie le menu ({stats['final']} deals)..."
        print(f"[{job_id[:8]}] Envoi à Claude...")

        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(MealPlanner().plan, filtered)
            try:
                plan = future.result(timeout=CLAUDE_TIMEOUT_SEC)
            except FuturesTimeout:
                jobs[job_id] = {
                    "status": "error",
                    "result": (
                        f"Timeout Claude ({CLAUDE_TIMEOUT_SEC}s dépassées). "
                        "L'API Anthropic met trop de temps à répondre. Réessaie dans quelques minutes."
                    ),
                }
                return

        print(f"[{job_id[:8]}] Plan reçu de Claude")

        # ── Étape 4 : formatage ──────────────────────────────────────────
        jobs[job_id]["step"] = "Formatage de la liste..."
        output = format_grocery_list(plan)

        jobs[job_id] = {"status": "done", "result": output}
        print(f"[{job_id[:8]}] Terminé ✓")

    except Exception as exc:
        print(f"[{job_id[:8]}] ERREUR: {exc}")
        jobs[job_id] = {"status": "error", "result": f"Erreur inattendue: {exc}"}

    finally:
        _job_lock.release()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    running = [jid for jid, j in jobs.items() if j["status"] == "running"]
    return {"status": "ok", "jobs_running": len(running)}


@app.get("/test-claude")
def test_claude() -> dict:
    """Test minimal de connectivité Anthropic (sans scraping)."""
    import anthropic as _anthropic
    import config as _cfg
    try:
        client = _anthropic.Anthropic(api_key=_cfg.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=_cfg.MODEL,
            max_tokens=20,
            messages=[{"role": "user", "content": "Réponds uniquement: OK"}],
        )
        return {"status": "ok", "reply": resp.content[0].text.strip()}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.post("/run")
def run(
    background_tasks: BackgroundTasks,
    postal_code: str = config.POSTAL_CODE,
    max_flyers: int = config.MAX_FLYERS,
) -> dict:
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
        return {
            "status": "error",
            "result": "Job introuvable — le serveur a probablement redémarré. Relance une génération.",
        }
    return job


# ---------------------------------------------------------------------------
# Static (après les routes API)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")
