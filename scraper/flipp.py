"""
Flipp.com scraper – requests uniquement, API dam.flippenterprise.net.

Flux:
  1. GET /api/flipp/data          → liste des 150+ circulaires (store name, ID, dates)
  2. GET /api/flipp/flyer_items/search?q={mot}  → flyer_item_ids par catégorie
  3. GET /api/flipp/flyer_items/{id}             → détail avec current_price, sale_story

Aucun browser requis — 100% requests.
"""

from __future__ import annotations

import random
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Deal:
    store: str
    name: str
    price: float
    original_price: float | None
    unit: str
    sale_story: str
    category: str
    valid_from: str
    valid_to: str
    flyer_id: int
    item_id: int

    @property
    def savings(self) -> float | None:
        if self.original_price and self.original_price > self.price:
            return round(self.original_price - self.price, 2)
        return None

    @property
    def savings_pct(self) -> float | None:
        if self.savings and self.original_price:
            return round(self.savings / self.original_price * 100, 1)
        return None

    def as_dict(self) -> dict:
        return {
            "store": self.store,
            "name": self.name,
            "price": self.price,
            "original_price": self.original_price,
            "unit": self.unit,
            "sale_story": self.sale_story,
            "category": self.category,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "savings_pct": self.savings_pct,
        }


# ---------------------------------------------------------------------------
# Mots-clés de recherche par segment du guide alimentaire
# ---------------------------------------------------------------------------

_SEARCH_KEYWORDS: dict[str, list[str]] = {
    "proteins": [
        "poulet", "chicken", "boeuf", "beef", "porc", "pork",
        "saumon", "salmon", "thon", "tuna", "crevette", "shrimp",
        "oeuf", "egg", "tofu", "fromage", "cheese",
        "yogourt", "yogurt", "lait", "milk", "lentille", "haricot",
        "dinde", "turkey", "veau", "morue", "cod", "sardine",
        "pois chiche", "chickpea", "edamame", "tempeh", "cottage",
    ],
    "vegetables_fruits": [
        "tomate", "tomato", "carotte", "carrot", "brocoli", "broccoli",
        "épinard", "spinach", "laitue", "lettuce", "pomme", "apple",
        "banane", "banana", "fraise", "strawberry", "bleuet", "blueberry",
        "oignon", "onion", "poivron", "pepper", "concombre", "cucumber",
        "melon", "orange", "citron", "mangue", "ananas", "avocat",
        "céleri", "asperge", "courgette", "champignon", "mushroom",
        "kale", "chou", "betterave", "beet", "patate douce", "sweet potato",
    ],
    "whole_grains": [
        "pain", "bread", "riz", "rice", "pâtes", "pasta",
        "avoine", "oat", "quinoa", "céréale", "cereal",
        "tortilla", "bagel", "farine", "flour", "orge", "barley",
        "couscous", "boulgour", "bulgur", "sarrasin", "buckwheat",
        "pain de blé", "whole wheat", "multigrain", "multigrain",
    ],
    "good_fats": [
        "noix", "amande", "almond", "cajou", "cashew",
        "pacane", "pecan", "pistache", "pistachio", "noisette", "hazelnut",
        "noix de grenoble", "walnut", "noix du brésil", "brazil nut",
        "graine de chia", "chia", "graine de lin", "flax",
        "graine de chanvre", "hemp seed", "graine de tournesol", "sunflower seed",
        "graine de citrouille", "pumpkin seed",
        "beurre d'arachide", "peanut butter", "beurre d'amande", "almond butter",
        "huile d'olive", "olive oil",
        "sardine", "maquereau", "mackerel", "hareng", "herring",
    ],
}

# ---------------------------------------------------------------------------
# API Flipp
# ---------------------------------------------------------------------------

_DAM_BASE = "https://dam.flippenterprise.net/api/flipp"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8",
    "Referer": "https://flipp.com/",
    "Origin": "https://flipp.com",
}


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class FlippScraper:
    """
    Récupère les deals en rabais de Flipp.com pour un code postal donné.
    Utilise uniquement requests — aucun browser nécessaire.

    Usage:
        scraper = FlippScraper("J8Y 3Z6")
        deals = scraper.get_all_deals()
    """

    def __init__(
        self,
        postal_code: str,
        locale: str = "fr",
        delay: float = 0.3,
    ) -> None:
        self.postal_code = postal_code.replace(" ", "").upper()
        self.locale = locale
        self.delay = delay
        self._sid = str(random.randint(10**15, 10**16))

        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_all_deals(self, max_flyers: Optional[int] = None) -> list[Deal]:
        """
        Stratégie en 3 étapes :
        1. Récupère la liste des circulaires (store info)
        2. Cherche les items par mots-clés de chaque catégorie alimentaire
        3. Récupère le détail (prix) de chaque item
        """
        # ── Étape 1 : catalogue des circulaires ───────────────────────
        print("  [flipp] Récupération des circulaires...")
        flyers = self._get_flyers()
        if max_flyers:
            flyers = flyers[:max_flyers]
        flyer_store: dict[int, str] = {
            f["id"]: f.get("merchant") or f.get("name", "Inconnu")
            for f in flyers
        }
        flyer_meta: dict[int, dict] = {f["id"]: f for f in flyers}
        print(f"  [flipp] {len(flyers)} circulaires disponibles")

        # ── Étape 2 : recherche par mots-clés ─────────────────────────
        print("  [flipp] Recherche des items par catégorie...")
        item_ids_by_category: dict[str, set[int]] = {cat: set() for cat in _SEARCH_KEYWORDS}

        for category, keywords in _SEARCH_KEYWORDS.items():
            print(f"    {category}: {len(keywords)} mots-clés", end=" ")
            for kw in keywords:
                ids = self._search_items(kw)
                item_ids_by_category[category].update(ids)
                time.sleep(self.delay)
            print(f"→ {len(item_ids_by_category[category])} items uniques")

        all_ids: set[int] = set()
        for ids in item_ids_by_category.values():
            all_ids.update(ids)
        print(f"  [flipp] {len(all_ids)} items uniques à récupérer")

        # ── Étape 3 : détail et prix (parallèle) ──────────────────────
        print("  [flipp] Récupération des prix (parallèle)...")
        item_to_category: dict[int, str] = {}
        for cat, ids in item_ids_by_category.items():
            for iid in ids:
                if iid not in item_to_category:
                    item_to_category[iid] = cat

        deals: list[Deal] = []
        lock = threading.Lock()
        counter = [0]
        total = len(all_ids)

        def fetch_and_normalize(item_id: int) -> Optional[Deal]:
            detail = self._get_item_detail(item_id)
            with lock:
                counter[0] += 1
                if counter[0] % 100 == 0:
                    print(f"    {counter[0]}/{total} items traités...")
            if not detail:
                return None
            category = item_to_category.get(item_id, "other")
            fid = detail.get("flyer_id") or 0
            store = detail.get("merchant") or flyer_store.get(fid, "Inconnu")
            meta = flyer_meta.get(fid, {})
            return self._normalize(detail, store, fid, category, meta)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_and_normalize, iid): iid for iid in all_ids}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    with lock:
                        deals.append(result)

        # Dédoublonne par (store, name) — garde le prix le plus bas
        deals = self._deduplicate(deals)
        print(f"  [flipp] {len(deals)} deals uniques avec prix")
        return deals

    @staticmethod
    def _deduplicate(deals: list[Deal]) -> list[Deal]:
        """Garde un seul deal par (store, name normalisé), au prix le plus bas."""
        seen: dict[tuple[str, str], Deal] = {}
        for d in deals:
            key = (d.store, d.name.lower()[:60])
            existing = seen.get(key)
            if existing is None or d.price < existing.price:
                seen[key] = d
        return list(seen.values())

    # ------------------------------------------------------------------
    # API calls
    # ------------------------------------------------------------------

    def _get_flyers(self) -> list[dict]:
        resp = self.session.get(
            f"{_DAM_BASE}/data",
            params={
                "locale": self.locale,
                "postal_code": self.postal_code,
                "sid": self._sid,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("flyers", [])

    def _search_items(self, query: str) -> list[int]:
        """Retourne les flyer_item_ids correspondant à la recherche."""
        try:
            resp = self.session.get(
                f"{_DAM_BASE}/flyer_items/search",
                params={
                    "q": query,
                    "postal_code": self.postal_code,
                    "locale": self.locale,
                },
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [item["flyer_item_id"] for item in items if "flyer_item_id" in item]
        except Exception:
            return []

    def _get_item_detail(self, item_id: int) -> Optional[dict]:
        """Retourne le détail complet d'un item avec current_price."""
        try:
            resp = self.session.get(
                f"{_DAM_BASE}/flyer_items/{item_id}",
                timeout=12,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalize(
        self,
        item: dict,
        store: str,
        flyer_id: int,
        category: str,
        meta: dict,
    ) -> Optional[Deal]:
        name = (item.get("name") or "").strip()
        if not name:
            return None

        price_raw = item.get("current_price")
        if price_raw is None:
            return None
        try:
            price = float(price_raw)
        except (ValueError, TypeError):
            return None

        if price <= 0:
            return None

        orig_raw = item.get("original_price") or item.get("pre_price")
        original_price: float | None = None
        if orig_raw is not None:
            try:
                original_price = float(orig_raw)
            except (ValueError, TypeError):
                pass

        return Deal(
            store=store,
            name=name,
            price=price,
            original_price=original_price,
            unit=item.get("price_text") or item.get("unit_of_measure") or "",
            sale_story=item.get("sale_story") or item.get("description") or "",
            category=category,
            valid_from=item.get("valid_from") or meta.get("valid_from", ""),
            valid_to=item.get("valid_to") or meta.get("valid_to", ""),
            flyer_id=flyer_id,
            item_id=item.get("id") or 0,
        )
