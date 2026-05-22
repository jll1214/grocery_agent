import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
POSTAL_CODE: str = os.getenv("POSTAL_CODE", "J8Y 3Z6")
LOCALE: str = "fr"
MODEL: str = "claude-sonnet-4-6"

# Meal plan targets per Canada's Food Guide 2019
FOOD_GUIDE_RATIOS = {
    "vegetables_fruits": 0.50,
    "whole_grains": 0.25,
    "proteins": 0.25,
}

SCRAPER_DELAY_SECONDS: float = 0.3
MAX_FLYERS: int = 20

# Cibles protéiques par repas (grammes) – basées sur le FCÉN
PROTEIN_TARGET_BREAKFAST_G: int = 20
PROTEIN_TARGET_LUNCH_G: int = 30
PROTEIN_TARGET_DINNER_G: int = 30

# ---------------------------------------------------------------------------
# Filtre géographique – épiceries dans un rayon de ~4.30 km de la rue Laroche
# (Hull, Gatineau). Noms exacts tels qu'ils apparaissent dans les circulaires Flipp.
# Ajouter/retirer selon les magasins réels de ton secteur.
# ---------------------------------------------------------------------------
NEARBY_GROCERY_STORES: set[str] = {
    "IGA",
    "Metro",
    "Maxi",
    "Super C",
    "Walmart",
    "Costco",
    "Adonis",
    "Farm Boy",
    "No Frills",
    "Provigo",
    "Loblaws",
    "Real Canadian Superstore",
    "Your Independent Grocer",
    "Giant Tiger",
    "La Boite à Grains",
    "Food Basics",
    "FreshCo",
    "President's Choice",        # offres PC disponibles chez Maxi/Provigo/Loblaws
    "Wholesale Club and Club Entrepôt",
}

# ---------------------------------------------------------------------------
# Filtre fruits & légumes – inclus seulement si le rabais est >= ce seuil (%).
# Sinon, Claude part du principe que ces besoins sont comblés autrement.
# Mettre à 0 pour désactiver le filtre et toujours inclure.
# ---------------------------------------------------------------------------
VEG_FRUIT_MIN_SAVINGS_PCT: float = 20.0
