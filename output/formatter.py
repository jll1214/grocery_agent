"""
Formateur de sortie console.
Structure : Dimanche (j.1) -> Samedi (j.7), cook-once souper->diner.
"""

from __future__ import annotations

from typing import Any

_MEAL_LABELS = {
    "breakfast": "Dejeuner",
    "lunch":     "Diner   ",
    "dinner":    "Souper  ",
}


def format_grocery_list(plan: dict[str, Any]) -> str:
    lines: list[str] = []

    # ── Chaine cook-once ─────────────────────────────────────────────────────
    week = plan.get("week_structure", {})
    chain = week.get("cook_once_chain", [])
    if chain:
        _header(lines, "CHAINE COOK ONCE : SOUPER -> DINER DU LENDEMAIN")
        for link in chain:
            lines.append(f"  {link}")
        lines.append("")

    # ── Planning de cuisson ───────────────────────────────────────────────────
    sched = plan.get("cooking_schedule", {})
    if sched:
        _header(lines, "PLANNING DE CUISSON")
        lines.append("")

        sunday = sched.get("sunday_batch", {})
        if sunday:
            dur = sunday.get("duration_min", "?")
            rec = sunday.get("recommendation", "")
            lines.append(f"  [DIMANCHE] Session principale ({dur} min)")
            if rec:
                lines.append(f"  Recommandation : {rec}")
            for t in sunday.get("tasks", []):
                task = t.get("task", "")
                tdur = t.get("duration_min", "")
                yld  = t.get("yields", "")
                yld_str = f"  -> {yld}" if yld else ""
                lines.append(f"    [{tdur} min]  {task}{yld_str}")
            lines.append("")

        midweek = sched.get("midweek_session", {})
        if midweek and midweek.get("tasks"):
            mday = midweek.get("day", "Mi-semaine")
            mdur = midweek.get("duration_min", "?")
            lines.append(f"  [{mday.upper()}] Session mi-semaine ({mdur} min)")
            for t in midweek.get("tasks", []):
                task = t.get("task", "")
                tdur = t.get("duration_min", "")
                dur_str = f"[{tdur} min]  " if tdur else ""
                lines.append(f"    {dur_str}{task}")
            lines.append("")

    # ── Ingredients frais ─────────────────────────────────────────────────────
    fresh = plan.get("fresh_ingredients_plan", {})
    if fresh:
        _header(lines, "INGREDIENTS FRAIS DE LA SEMAINE")
        items_list = fresh.get("items", [])
        lines.append(f"  {len(items_list)} produits frais : {', '.join(items_list)}")
        order = fresh.get("usage_order", "")
        if order:
            lines.append(f"  Ordre d'utilisation : {order}")
        lines.append("")

    # ── Gros formats ──────────────────────────────────────────────────────────
    bulk_items = plan.get("bulk_items_reuse", [])
    if bulk_items:
        _header(lines, "GROS FORMATS -- PLAN D'UTILISATION")
        for bulk in bulk_items:
            name  = bulk.get("item", "")
            store = bulk.get("store", "")
            price = bulk.get("total_price", 0.0)
            qty   = bulk.get("total_qty", "")
            lines.append(f"  {name} @ {store}  ({qty}) -- {_p(price)}")
            for use in bulk.get("uses", []):
                day  = use.get("day", "?")
                meal = use.get("meal", "")
                form = use.get("form", "")
                uqty = use.get("qty", "")
                alloc = use.get("cost_allocated", 0.0)
                mlabel = {"breakfast": "Dej", "lunch": "Din", "dinner": "Sou"}.get(meal, meal)
                lines.append(f"    J.{day} {mlabel} : {form} ({uqty}) -- {_p(alloc)}")
            lines.append("")

    # ── Plan de repas ─────────────────────────────────────────────────────────
    _header(lines, "PLAN DE REPAS  (Dimanche j.1 -> Samedi j.7)")
    lines.append("")

    for day_data in plan.get("meal_plan", []):
        day      = day_data.get("day", "?")
        day_name = day_data.get("day_name", f"Jour {day}")
        is_batch = day_data.get("is_batch_cooking_day", False)

        batch_tag = "  [BATCH COOKING]" if is_batch else ""
        lines.append(f"JOUR {day} -- {day_name.upper()}{batch_tag}")
        lines.append("-" * 62)

        for meal_key, label in _MEAL_LABELS.items():
            meal = day_data.get(meal_key, {})
            if not meal:
                continue

            name     = meal.get("name", "--")
            cost     = meal.get("cost", 0.0)
            cpp      = meal.get("cost_per_portion")
            is_left  = meal.get("is_leftover", False)
            portions = meal.get("portions_cooked")
            next_day = meal.get("next_day_lunch_note", "")
            prep_min = meal.get("prep_time_min")
            macros   = meal.get("macros", {})

            # Ligne titre du repas
            if is_left:
                src = meal.get("leftover_source", "souper precedent")
                lines.append(f"  {label}: {name}")
                lines.append(f"    [LEFTOVER de {src} -- rechauffer {prep_min or 5} min -- 0.00 $]")
            else:
                portions_tag = f"  [x{portions} portions]" if portions and portions > 1 else ""
                cpp_str = f"  [{_p(cpp)}/portion]" if cpp is not None else ""
                lines.append(f"  {label}: {name}{portions_tag}  (total {_p(cost)}{cpp_str})")
                if next_day:
                    lines.append(f"    --> {next_day}")

            # Macros
            prot_g  = macros.get("protein_g")
            fat_g   = macros.get("fat_g")
            fiber_g = macros.get("fiber_g")
            kcal    = macros.get("kcal")
            parts   = []
            if prot_g is not None:
                target = 25 if meal_key == "breakfast" else 40
                flag   = " (!)" if (not is_left) and prot_g < target else ""
                parts.append(f"prot {prot_g}g{flag}")
            if fat_g   is not None: parts.append(f"lip {fat_g}g")
            if fiber_g is not None: parts.append(f"fibres {fiber_g}g")
            if kcal    is not None: parts.append(f"{kcal} kcal")
            if parts:
                lines.append(f"    Macros  : {' | '.join(parts)}")

            prot_src = meal.get("protein_sources", [])
            good_fat = meal.get("good_fats", [])
            if prot_src: lines.append(f"    Proteines : {', '.join(prot_src)}")
            if good_fat: lines.append(f"    Bons gras : {', '.join(good_fat)}")

            check = meal.get("food_guide_check", {})
            if check and not is_left:
                v = check.get("vegetables_pct", "?")
                g = check.get("grains_pct", "?")
                p = check.get("protein_pct", "?")
                lines.append(f"    Guide   : legumes {v}%  grains {g}%  proteines {p}%")

            if not is_left:
                for ing in meal.get("ingredients", []):
                    iname = ing.get("item", "")
                    store = ing.get("store", "")
                    qty   = ing.get("qty", "")
                    icost = ing.get("cost", 0.0)
                    lines.append(f"    * {iname} ({qty}) @ {store} -- {_p(icost)}")

        lines.append("")

    # ── Validation coût : top 3 recettes les plus chères ─────────────────────
    _format_cost_validation(lines, plan.get("meal_plan", []))

    # ── Resume nutritionnel ───────────────────────────────────────────────────
    weekly = plan.get("weekly_nutrition_summary", {})
    if weekly:
        _header(lines, "RESUME NUTRITIONNEL HEBDOMADAIRE")
        kcal  = weekly.get("avg_daily_kcal", 0)
        prot  = weekly.get("avg_daily_protein_g", 0)
        fat   = weekly.get("avg_daily_fat_g", 0)
        carb  = weekly.get("avg_daily_carb_g", 0)
        fiber = weekly.get("avg_daily_fiber_g", 0)

        # Calories avec écart vs cible 2200
        kcal_flag = ""
        if isinstance(kcal, (int, float)) and kcal > 0:
            diff = kcal - 2200
            kcal_flag = f"  ({'+' if diff >= 0 else ''}{diff:.0f} vs cible 2200)"
        lines.append(f"  Calories moy./jour     : {kcal} kcal{kcal_flag}")

        # Macros avec % des kcal calculé si possible
        def _macro_pct(g: float, cal_per_g: float) -> str:
            if not kcal or not isinstance(g, (int, float)) or g <= 0:
                return ""
            return f"  ({round(g * cal_per_g / kcal * 100)}% kcal)"

        lines.append(f"  Glucides moy./jour     : {carb} g{_macro_pct(carb, 4)}  [cible ~50%]")
        lines.append(f"  Lipides moy./jour      : {fat} g{_macro_pct(fat, 9)}  [cible ~20%]")
        lines.append(f"  Proteines moy./jour    : {prot} g{_macro_pct(prot, 4)}  [cible ~30%]")
        lines.append(f"  Fibres moy./jour       : {fiber} g")
        lines.append("")
        lines.append(f"  Repas viande/poisson   : {weekly.get('animal_protein_meals', '?')}/semaine")
        lines.append(f"  Repas proteines vegetal: {weekly.get('plant_protein_meals', '?')}/semaine")
        lines.append(f"  Diners zero-prep       : {weekly.get('leftover_lunches', '?')}/7")
        lines.append(f"  Recettes uniques       : {weekly.get('total_unique_recipes', '?')}")
        lines.append(f"  Repas < 3.00$/portion  : {weekly.get('meals_under_3_dollars_per_portion', '?')}/21")
        lines.append("")

    # ── Liste d'epicerie ──────────────────────────────────────────────────────
    _header(lines, "LISTE D'EPICERIE PAR MAGASIN")
    lines.append("")

    for store_block in plan.get("grocery_list", []):
        store_name  = store_block.get("store", "Inconnu")
        store_total = store_block.get("store_total", 0.0)
        lines.append(f"  [== {store_name.upper()} ==]")
        for item in store_block.get("items", []):
            iname      = item.get("name", "")
            qty        = item.get("qty", "")
            unit_price = item.get("unit_price", 0.0)
            total      = item.get("total", 0.0)
            lines.append(
                f"  | {iname:<38} {qty:<12} {_p(unit_price):>8}  ->  {_p(total):>8}"
            )
        lines.append(f"  Sous-total {store_name}: {_p(store_total):>8}")
        lines.append("")

    # ── Alignement de prix ───────────────────────────────────────────────────
    _format_alignement_prix(lines, plan.get("alignement_prix", []))

    # ── Totaux ────────────────────────────────────────────────────────────────
    _header(lines, "RESUME FINANCIER")
    grand_total = plan.get("grand_total", 0.0)
    savings     = plan.get("savings_vs_regular", 0.0)
    lines.append(f"  Total epicerie de la semaine : {_p(grand_total)}")
    if savings:
        lines.append(f"  Economies vs prix regulier   : {_p(savings)}")
        if grand_total > 0:
            pct = round(savings / (grand_total + savings) * 100, 1)
            lines.append(f"  Rabais moyen                 : {pct}%")

    notes = plan.get("notes", "")
    if notes:
        lines.append("")
        lines.append("  Notes :")
        for note_line in notes.split(". "):
            if note_line.strip():
                lines.append(f"    * {note_line.strip()}")

    lines.append("")
    return "\n".join(lines)


def _format_alignement_prix(lines: list[str], items: list[dict]) -> None:
    """Affiche les deals concurrents à demander en alignement de prix chez Maxi."""
    if not items:
        return

    _header(lines, "ALIGNEMENT DE PRIX A DEMANDER CHEZ MAXI")
    lines.append("  Montre ces circulaires a la caisse — Maxi aligne les prix concurrents.")
    lines.append("")

    used     = [i for i in items if i.get("used_in_plan")]
    extra    = [i for i in items if not i.get("used_in_plan")]

    if used:
        lines.append("  [UTILISES DANS LE MENU — alignement necessaire]")
        for it in used:
            name    = it.get("item", "")
            store   = it.get("store_concurrent", "")
            price   = it.get("price", 0.0)
            unit    = it.get("unit", "")
            savings = it.get("savings_pct", 0)
            note    = it.get("note", "")
            lines.append(f"  * {name:<35} {store:<12} {_p(price)}/{unit}  (-{savings}%)")
            if note:
                lines.append(f"      -> {note}")
        lines.append("")

    if extra:
        lines.append("  [BONS RABAIS SUPPLEMENTAIRES — optionnel]")
        for it in extra:
            name    = it.get("item", "")
            store   = it.get("store_concurrent", "")
            price   = it.get("price", 0.0)
            unit    = it.get("unit", "")
            savings = it.get("savings_pct", 0)
            note    = it.get("note", "")
            lines.append(f"  * {name:<35} {store:<12} {_p(price)}/{unit}  (-{savings}%)")
            if note:
                lines.append(f"      -> {note}")
        lines.append("")


def _format_cost_validation(lines: list[str], meal_plan: list[dict]) -> None:
    """Affiche le détail du calcul de coût pour les 3 recettes non-leftover les plus chères."""
    candidates: list[tuple[float, str, str, int, dict]] = []  # (cpp, day_name, meal_label, portions, meal)

    for day_data in meal_plan:
        day_name = day_data.get("day_name", f"Jour {day_data.get('day', '?')}")
        for meal_key, label in _MEAL_LABELS.items():
            meal = day_data.get(meal_key, {})
            if not meal or meal.get("is_leftover"):
                continue
            cpp = meal.get("cost_per_portion")
            if cpp is None:
                continue
            portions = meal.get("portions_cooked", 1)
            candidates.append((cpp, day_name, label.strip(), portions, meal))

    if not candidates:
        return

    top3 = sorted(candidates, key=lambda x: x[0], reverse=True)[:3]

    _header(lines, "VALIDATION COUT -- TOP 3 RECETTES LES PLUS CHERES")
    lines.append("")

    for rank, (cpp, day_name, meal_label, portions, meal) in enumerate(top3, 1):
        name  = meal.get("name", "--")
        total = meal.get("cost", 0.0)
        ings  = meal.get("ingredients", [])

        lines.append(f"  #{rank}  {day_name} / {meal_label} : {name}")

        # Détail ingrédient par ingrédient
        ing_sum = 0.0
        for ing in ings:
            iname = ing.get("item", "")
            qty   = ing.get("qty", "")
            icost = ing.get("cost", 0.0)
            store = ing.get("store", "")
            ing_sum += icost
            lines.append(f"       {iname:<32} {qty:<12}  {_p(icost):>8}")

        # Ligne de totalisation
        lines.append(f"       {'─' * 56}")
        lines.append(f"       {'Sous-total ingredients':<44}  {_p(ing_sum):>8}")

        if portions and portions > 1:
            lines.append(f"       Portions cuisinees : {portions}  ->  {_p(ing_sum)} / {portions} = {_p(ing_sum / portions)} par portion")
        else:
            lines.append(f"       Portions cuisinees : 1  ->  {_p(total)} par portion")

        if abs(ing_sum - total) > 0.02:
            lines.append(f"       [!] Ecart : ingredients {_p(ing_sum)} vs cost declare {_p(total)}")

        lines.append(f"       => cost_per_portion declare : {_p(cpp)}")
        lines.append("")


def _header(lines: list[str], title: str) -> None:
    bar = "=" * (len(title) + 4)
    lines.append(f"+{bar}+")
    lines.append(f"|  {title}  |")
    lines.append(f"+{bar}+")


def _p(value: float | None) -> str:
    if value is None:
        return " -- "
    return f"{value:.2f} $"
