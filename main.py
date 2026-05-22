"""
Point d'entrée principal du grocery agent.

Usage:
    python main.py
    python main.py --postal-code "J8Y 3Z6" --max-flyers 10 --output plan.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import io
from pathlib import Path

# Force UTF-8 sur la console Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import (
    POSTAL_CODE, MAX_FLYERS, SCRAPER_DELAY_SECONDS,
    NEARBY_GROCERY_STORES, VEG_FRUIT_MIN_SAVINGS_PCT,
)
from scraper.flipp import FlippScraper
from scraper.filters import apply_all as apply_filters
from planner.meal_planner import MealPlanner
from output.formatter import format_grocery_list


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent d'épicerie automatique – Flipp + Claude")
    parser.add_argument("--postal-code", default=POSTAL_CODE, help="Code postal (défaut: J8Y 3Z6)")
    parser.add_argument("--max-flyers", type=int, default=MAX_FLYERS, help="Nombre max de circulaires à scraper")
    parser.add_argument("--output", default=None, help="Fichier de sortie texte (optionnel)")
    parser.add_argument("--json-output", default=None, help="Fichier de sortie JSON brut (optionnel)")
    parser.add_argument("--deals-only", action="store_true", help="Afficher seulement les deals sans planifier")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Agent d'épicerie – {args.postal_code}")
    print(f"{'='*60}\n")

    # ── 1. Scraping ────────────────────────────────────────────────────────
    print("[ 1/3 ] Récupération des circulaires Flipp…")
    scraper = FlippScraper(postal_code=args.postal_code)

    try:
        deals = scraper.get_all_deals(max_flyers=args.max_flyers)
    except Exception as exc:
        print(f"\n❌ Erreur de scraping: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  ✓ {len(deals)} deals bruts récupérés\n")

    # ── 1b. Filtres géo + rabais fruits/légumes ────────────────────────────
    print("[ 1b/3 ] Application des filtres…")
    deals, stats = apply_filters(
        deals,
        nearby_stores=NEARBY_GROCERY_STORES,
        veg_fruit_min_savings_pct=VEG_FRUIT_MIN_SAVINGS_PCT,
    )
    from collections import Counter
    by_cat = Counter(d.category for d in deals)
    print(f"  • Épiceries hors rayon exclues  : {stats['excluded_store']} deals")
    print(f"  • Légumes/fruits sans gros rabais: {stats['excluded_veg_no_deal']} deals")
    print(f"    (seuil: {VEG_FRUIT_MIN_SAVINGS_PCT:.0f}% – besoins supposés comblés)")
    print(f"  • Légumes/fruits conservés (>=20%): {stats['veg_included']}")
    print(f"  ✓ {stats['final']} deals après filtres")
    print(f"    → protéines: {by_cat['proteins']}  grains: {by_cat['whole_grains']}"
          f"  légumes/fruits: {by_cat['vegetables_fruits']}  bonnes graisses: {by_cat['good_fats']}\n")

    if args.deals_only:
        _print_deals_summary(deals)
        return

    if not deals:
        print("❌ Aucun deal trouvé après filtres. Ajustez NEARBY_GROCERY_STORES dans config.py.")
        sys.exit(1)

    # ── 2. Planification ───────────────────────────────────────────────────
    print("[ 2/3 ] Génération du plan de repas avec Claude…")
    planner = MealPlanner()

    try:
        plan = planner.plan(deals)
    except Exception as exc:
        print(f"\n❌ Erreur de planification: {exc}", file=sys.stderr)
        sys.exit(1)

    print("  ✓ Plan de repas généré\n")

    # Sauvegarde JSON optionnelle
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  JSON sauvegardé: {args.json_output}")

    # ── 3. Affichage ───────────────────────────────────────────────────────
    print("[ 3/3 ] Formatage de la liste d'épicerie…\n")
    output = format_grocery_list(plan)
    print(output)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"\n  Liste sauvegardée: {args.output}")


def _print_deals_summary(deals: list) -> None:
    from collections import defaultdict

    by_store: dict = defaultdict(list)
    for d in deals:
        by_store[d.store].append(d)

    print(f"\n{'─'*60}")
    print(f"  RÉSUMÉ DES DEALS ({len(deals)} total)")
    print(f"{'─'*60}")
    for store, store_deals in sorted(by_store.items()):
        print(f"\n  {store} ({len(store_deals)} deals)")
        for d in sorted(store_deals, key=lambda x: x.price)[:5]:
            savings_str = f"  [-{d.savings_pct}%]" if d.savings_pct else ""
            print(f"    • {d.name:<40} {d.price:>6.2f} ${savings_str}")
        if len(store_deals) > 5:
            print(f"    … et {len(store_deals) - 5} autres")


if __name__ == "__main__":
    main()
