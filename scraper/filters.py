"""
Filtres appliqués après le scraping Flipp :
  1. Garde uniquement les épiceries de la whitelist NEARBY_GROCERY_STORES.
  2. Pour la catégorie vegetables_fruits, exclut les items sans rabais suffisant
     (on suppose que les fruits/légumes au prix courant sont achetés ailleurs).
"""

from __future__ import annotations

from scraper.flipp import Deal


def apply_all(
    deals: list[Deal],
    nearby_stores: set[str],
    veg_fruit_min_savings_pct: float,
) -> tuple[list[Deal], dict]:
    """
    Retourne (deals_filtrés, stats).

    stats contient les compteurs pour afficher ce qui a été exclu.
    """
    stats = {
        "total_before": len(deals),
        "excluded_store": 0,
        "excluded_veg_no_deal": 0,
        "veg_included": 0,
        "final": 0,
    }

    filtered: list[Deal] = []

    for deal in deals:
        # ── Filtre 1 : magasin dans le rayon ──────────────────────────
        if not _store_matches(deal.store, nearby_stores):
            stats["excluded_store"] += 1
            continue

        # ── Filtre 2 : fruits/légumes sans rabais suffisant ───────────
        if deal.category == "vegetables_fruits" and veg_fruit_min_savings_pct > 0:
            pct = deal.savings_pct or 0.0
            if pct < veg_fruit_min_savings_pct:
                stats["excluded_veg_no_deal"] += 1
                continue
            stats["veg_included"] += 1

        filtered.append(deal)

    stats["final"] = len(filtered)
    return filtered, stats


def _store_matches(store_name: str, whitelist: set[str]) -> bool:
    """
    Correspondance souple : vérifie si le nom du magasin contient
    un des noms de la whitelist (insensible à la casse).
    Exemple : "IGA Extra" correspond à "IGA".
    """
    store_lower = store_name.lower()
    for allowed in whitelist:
        if allowed.lower() in store_lower:
            return True
    return False
