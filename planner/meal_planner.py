"""
Planificateur de repas basé sur le Guide alimentaire canadien 2019
et le Fichier canadien sur les éléments nutritifs (FCÉN).

Structure hebdomadaire :
  Jour 1 = Dimanche  (batch cooking principal + souper x2)
  Jour 2 = Lundi     (diner = leftover Dim; souper x2 -> Mar diner)
  Jour 3 = Mardi     (diner = leftover Lun; souper x2 -> Mer diner)
  Jour 4 = Mercredi  (diner = leftover Mar; souper x2 -> Jeu diner)
  Jour 5 = Jeudi     (diner = leftover Mer; souper x2 -> Ven diner)
  Jour 6 = Vendredi  (diner = leftover Jeu; souper x2 -> Sam diner)
  Jour 7 = Samedi    (diner = leftover Ven; souper = repas weekend)

Principes :
  - Cook-once : souper du soir N -> diner du jour N+1 (zero prep)
  - Batch cooking le dimanche (option : +session mi-semaine)
  - Proteines >= 20g dejeuner, >= 30g diner/souper (FCEN)
  - >= 1 repas viande/poisson, >= 3 repas proteines vegetales/semaine
  - Gros formats declines en plusieurs recettes
  - Cout par portion calcule sur la fraction reellement utilisee
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from pathlib import Path

from config import ANTHROPIC_API_KEY, MODEL
from scraper.flipp import Deal

_DEBUG_PATH = Path(__file__).parent.parent / "debug_raw_response.json"

# ---------------------------------------------------------------------------
# Donnees FCEN de reference (pour 100 g sauf indication)
# ---------------------------------------------------------------------------

_FCEN_REFERENCE = """\
FCEN - VALEURS NUTRITIVES DE REFERENCE (pour 100 g sauf indication) :

PROTEINES ANIMALES :
* Poitrine de poulet cuite        : 31 g prot | 165 kcal | 3.6 g lip
* Cuisse de poulet cuite          : 26 g prot | 209 kcal | 11 g lip
* Boeuf hache mi-maigre cuit      : 26 g prot | 218 kcal | 13 g lip
* Porc longe cuit                 : 29 g prot | 175 kcal | 6 g lip
* Saumon Atlantique cuit          : 25 g prot | 182 kcal | 7 g lip (2 g omega-3)
* Thon en conserve (eau)          : 26 g prot | 116 kcal | 1 g lip
* Sardines en conserve (egouttees): 25 g prot | 208 kcal | 11 g lip (3.5 g omega-3)
* Maquereau en conserve           : 23 g prot | 155 kcal | 8 g lip (2 g omega-3)
* Oeuf entier cuit (1 gros = 50g) :  6.5 g prot | 78 kcal | 5 g lip
* Dinde poitrine cuite            : 30 g prot | 161 kcal | 4 g lip

PROTEINES VEGETALES :
* Tofu ferme (portion 150 g)      : 12 g prot | 114 kcal | 6 g lip
* Lentilles cuites (200 g)        : 18 g prot | 232 kcal | 0.8 g lip | 16 g fibres
* Pois chiches cuits (200 g)      : 18 g prot | 328 kcal | 5 g lip | 12 g fibres
* Haricots noirs cuits (200 g)    : 15 g prot | 264 kcal | 1 g lip | 15 g fibres
* Edamame (100 g)                 : 11 g prot | 121 kcal | 5 g lip
* Fromage cheddar (30 g)          :  7.5 g prot | 121 kcal | 10 g lip
* Yogourt grec nature 2% (175 g)  : 15 g prot | 128 kcal | 4 g lip
* Lait 2% (250 ml)                :  8 g prot | 128 kcal | 5 g lip
* Cottage cheese 2% (125 g)       : 14 g prot | 101 kcal | 2.5 g lip
* Beurre d'arachide (30 g)        :  8 g prot | 188 kcal | 16 g lip

GLUCIDES COMPLEXES :
* Flocons d'avoine cuits (234 g)  :  6 g prot | 166 kcal | 4 g lip | 4 g fibres
* Riz brun cuit (200 g)           :  5 g prot | 216 kcal | 1.8 g lip | 4 g fibres
* Quinoa cuit (185 g)             :  8 g prot | 222 kcal | 3.6 g lip | 5 g fibres
* Pain de ble entier (1 tr. 28 g) : 3.5 g prot | 69 kcal | 1 g lip | 1.9 g fibres
* Pates de ble entier cuites (150g): 7.5 g prot | 176 kcal | 1.5 g lip | 6 g fibres
* Patate douce cuite (150 g)      :  2 g prot | 129 kcal | 0.1 g lip | 4 g fibres
* Lentilles + riz brun = proteine complete (acides amines complementaires)

BONNES GRAISSES :
* Avocat (1/2 = 80 g)             : 1.5 g prot | 128 kcal | 12 g lip (10 g mono)
* Amandes (30 g)                   : 6 g prot | 173 kcal | 15 g lip | 3.5 g fibres
* Noix de Grenoble (30 g)         : 4.5 g prot | 196 kcal | 20 g lip (omega-3 ALA)
* Graines de chia (30 g)          : 5 g prot | 138 kcal | 9 g lip | 10 g fibres
* Graines de lin moulues (15 g)   : 2.7 g prot | 74 kcal | 6 g lip (omega-3)
* Huile d'olive (15 ml)           : 0 prot | 119 kcal | 14 g lip (10 g mono)
* Beurre d'amande (30 g)          : 7 g prot | 196 kcal | 17 g lip

CONVERSIONS UTILES :
* 1 c. a soupe (15 ml) graines de chia ~ 12 g
* 1 poignee (30 g) d'amandes ~ 23 amandes
* 1 tasse (250 ml) lentilles crues -> 2.5 tasses cuites
* 1 tasse (250 ml) riz brun cru -> 3 tasses cuites
* 1 filet de saumon (portion) ~ 150 g
* 1 boite de thon (85 g egoutte) -> 22 g proteines"""

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
Tu es un nutritionniste expert et planificateur de repas au Canada.
Tu utilises le Fichier canadien sur les elements nutritifs (FCEN) comme base
de donnees de reference pour toutes les valeurs nutritives et conversions poids/volume.

{_FCEN_REFERENCE}

=====================================================
REGLE CENTRALE : COOK ONCE, EAT TWICE
=====================================================

La semaine commence le DIMANCHE (Jour 1) et se termine le SAMEDI (Jour 7) :
  Jour 1 = Dimanche | Jour 2 = Lundi | Jour 3 = Mardi | Jour 4 = Mercredi
  Jour 5 = Jeudi    | Jour 6 = Vendredi | Jour 7 = Samedi

MAXIMUM 2 SESSIONS DE CUISINE PAR SEMAINE — REGLE ABSOLUE :
  Seuls 2 moments impliquent de la VRAIE cuisine (cuisson au feu/four) :
    SESSION 1 : Dimanche (obligatoire, 2-3 h) — batch cooking complet
    SESSION 2 : Mardi ou Mercredi soir (optionnel, 30-45 min) — rafraichissement

  Tous les autres soirs = ASSEMBLAGE UNIQUEMENT (< 10 min) :
    Combiner des composants pre-cuits du dimanche + sauce/epices differentes.
    Rechauffer au besoin. ZERO cuisson reelle.

SOUPER -> DINER DU LENDEMAIN (chaine ininterrompue) :
  Chaque souper est prepare EN DOUBLE PORTION (assemblage x2).
  Ce double DEVIENT AUTOMATIQUEMENT le diner du jour suivant (rechauffer 5 min).

  Dimanche souper x2  [CUISINE]    -> Lundi diner     (leftover, 0 prep)
  Lundi souper x2     [ASSEMBLAGE] -> Mardi diner     (leftover, 0 prep)
  Mardi souper x2     [ASSEMBLAGE ou SESSION 2] -> Mercredi diner
  Mercredi souper x2  [ASSEMBLAGE ou SESSION 2] -> Jeudi diner
  Jeudi souper x2     [ASSEMBLAGE] -> Vendredi diner  (leftover, 0 prep)
  Vendredi souper x2  [ASSEMBLAGE] -> Samedi diner    (leftover, 0 prep)
  Samedi souper       [ASSEMBLAGE] -> repas weekend (pas de doublement)

COUT DES REPAS LEFTOVER :
  Le diner-leftover a un cost = 0 $ et cost_per_portion = 0 $.
  Il est deja comptabilise dans le souper du jour precedent.
  Le souper x2 doit montrer cost = cout TOTAL pour 2 portions.
  cost_per_portion du souper = cost / 2.
  Le grand_total NE compte pas les diners-leftovers.

=====================================================
SESSION 1 : BATCH COOKING DU DIMANCHE (obligatoire)
=====================================================

Le Dimanche, cuisiner EN UNE SEULE FOIS tous les composants de base
qui seront ASSEMBLES differemment chaque soir de la semaine :

  PROTEINES (cuire tout le dimanche) :
    - Proteine animale principale (ex : cuire 1.5 kg de poulet, roles ou poeles)
    - Legumineuses (ex : 2 boites de pois chiches + 400 g lentilles)
    - Si 2e proteine prevue mi-semaine -> laisser pour SESSION 2

  GRAINS (cuire en grande quantite) :
    - Grain principal pour 4-5 jours (ex : 600 g riz brun cru -> ~1.8 kg cuit)
    - Grain secondaire si applicable (ex : 300 g quinoa cru -> ~900 g cuit)

  SAUCES / BASES AROMATIQUES (2-3 sauces differentes) :
    - Chaque soir, la meme proteine + le meme grain prennent une sauce differente
    - Ex : lundi sauce curry, mardi sauce tomate-basilic, mercredi soja-gingembre

  SOUPER DU DIMANCHE : le premier assemblage, sert de diner Lundi.

=====================================================
SESSION 2 : MI-SEMAINE (optionnel, 30-45 min)
=====================================================

Planifier si : nouvelle proteine fraiche (poisson, oeufs), nouveaux legumes
frais a cuire, ou lot de grains epuise. NE PAS recuire ce qui est deja pret.
Recommande l'option A (tout dimanche) ou B (dimanche + mi-semaine) selon
la complexite du menu.

=====================================================
OBJECTIF CALORIQUE ET MACRONUTRIMENTS
=====================================================

CIBLE : 2200 kcal/jour en moyenne (sur 7 jours).
  Repartition cible par repas :
    Dejeuner  : ~550 kcal
    Diner     : ~700 kcal  (leftovers = idem souper veille)
    Souper    : ~950 kcal  (portions x2, donc 1900 kcal cuisinaees au total)

MACROS CIBLES (flexibles, ecart +/- 10% accepte) :
    Glucides  : ~50% des kcal  (~275 g/jour)
    Lipides   : ~20% des kcal  (~49 g/jour)
    Proteines : ~30% des kcal  (~165 g/jour)
  Ces pourcentages sont des guides, pas des contraintes rigides.
  Privilegie la satiete, la variete et les aliments entiers.
  Dans le JSON, rapporte les macros reelles calculees (pas les cibles).

=====================================================
REGLES NUTRITIONNELLES
=====================================================

1. PROTEINES : >= 25 g au dejeuner, >= 40 g au diner et au souper (valeurs FCEN).
   Identifier clairement les sources de proteines dans chaque repas.

2. VIANDE/POISSON : >= 1 repas par semaine. Prioriser les rabais circulaire.

3. PROTEINES VEGETALES : >= 3 repas/semaine (tofu, lentilles, pois chiches, haricots noirs).

4. BONNES GRAISSES : noix au dejeuner, huile d'olive au diner/souper, poissons gras si en rabais.

5. GLUCIDES COMPLEXES : riz brun, quinoa, avoine, pain de ble entier, patate douce.
   Augmente les portions de grains pour atteindre la cible de 2200 kcal.

6. GUIDE ALIMENTAIRE CANADIEN 2019 :
   50% assiette = legumes et fruits | 25% = grains entiers | 25% = proteines

=====================================================
REGLES DE COUT ET DE GESTION DES INGREDIENTS
=====================================================

7. COUT REEL PAR PORTION :
   cout_alloue = prix_paquet x (quantite_utilisee / contenance_totale)
   Viser cost_per_portion < 3.00 $ pour les soupers (= 1.50 $/portion en double).

8. MAX 6 legumes/fruits frais differents pour la semaine. Privilegier les legumes
   stables (carottes, choux, patates douces) en fin de semaine, les fragiles (epinards,
   fines herbes) en debut. L'ordre d'utilisation doit etre explicite.

9. GROS FORMATS : Si un item est en grand format (5 kg, gros bloc, format familial),
   le decliner dans >= 3 recettes differentes sous des formes variees.
   Chaque usage montre le cout alloue proportionnel.

10. BUDGET : minimiser le cout total. Les legumineuses et oeufs doivent dominer.

=====================================================
STRATEGIE D'ACHAT : TOUT AU MAXI
=====================================================

11. MAXI EN PRIORITE : Construis le menu en privilegiant EN PREMIER les
    articles dont "store" contient "Maxi". L'objectif est de faire UNE
    SEULE epicerie hebdomadaire chez Maxi. Si un article Maxi couvre le
    besoin, utilise-le meme si un concurrent est legerement moins cher.

12. ALIGNEMENT DE PRIX : Maxi accepte l'alignement sur les circulaires
    concurrentes. Identifie les deals NON-Maxi (savings_pct >= 25%) qui
    valent d'etre demandes en matching de prix chez Maxi. Inclus :
    - Tous les items non-Maxi que tu as UTILISES dans les recettes
      (marque used_in_plan: true) — l'utilisateur les demandera en alignement.
    - Les meilleurs rabais concurrents NON utilises dans le menu mais
      interessants (marque used_in_plan: false), max 4 extras.
    Total "alignement_prix" : max 10 items, tries par savings_pct decroissant.

=====================================================
REGLES DE FORMATAGE JSON -- STRICTEMENT OBLIGATOIRES
=====================================================

1. Reponds UNIQUEMENT avec un objet JSON valide.
   Aucun texte avant, aucun texte apres, aucun bloc markdown (pas de ```json).

2. Guillemets internes : echappe SYSTEMATIQUEMENT tout guillemet double a l'interieur
   d'une chaine avec \" (ex: "nom": "Soupe \"bonne femme\" classique").

3. Virgules trainantes : JAMAIS de virgule apres le dernier element d'un tableau ou
   d'un objet. Interdit : ["a", "b",]  ou  {{"cle": 1,}}

4. Retours a la ligne dans les chaines : INTERDITS. Remplace tout saut de ligne
   dans un texte (notes, descriptions, conseils) par un espace simple.

5. Nombres : utilise uniquement des litteraux JSON valides (0.0 pas .0, jamais NaN
   ni Infinity). Les champs numeriques manquants valent 0, jamais null.

6. Le JSON produit doit etre parseable directement par json.loads() sans pre-traitement.
"""

# ---------------------------------------------------------------------------
# User template
# ---------------------------------------------------------------------------

_USER_TEMPLATE = """\
Voici les rabais disponibles cette semaine a Gatineau (code postal J8Y 3Z6).

CONTEXTE :
- Epiceries dans un rayon de 4.30 km de la rue Laroche uniquement.
- Legumes/fruits listes = uniquement ceux avec >= 20% de rabais.
  Les legumes courants (carottes, oignons, etc.) sont dans le garde-manger ou
  achetes au prix courant — utilise-les librement dans les recettes mais ne les
  ajoute PAS a la liste d'epicerie sauf s'ils apparaissent ci-dessous.
- Le champ "unit" indique la contenance totale du paquet (ex: "5 kg", "900 g").
  Utilise-le pour calculer le cout alloue proportionnel a chaque recette.

=======================================================
PROTEINES EN RABAIS (animales et vegetales) :
{proteins_json}

=======================================================
GRAINS ENTIERS EN RABAIS :
{grains_json}

=======================================================
LEGUMES ET FRUITS EN RABAIS (>= 20% seulement) :
{veg_json}

=======================================================
BONNES GRAISSES EN RABAIS :
{fats_json}

=======================================================
INSTRUCTIONS :

1. STRUCTURE : Planifie 7 jours en commencant par le Dimanche (Jour 1).
   Jour 1=Dimanche, Jour 2=Lundi, ..., Jour 6=Vendredi, Jour 7=Samedi.

2. COOK ONCE : Chaque souper est cuisine x2 portions.
   Le souper du Jour N DEVIENT le diner du Jour N+1 (leftover, 0 $ de cout).
   EXCEPTION : le souper du Samedi (Jour 7) n'est pas double.

3. BATCH COOKING : Definis la session du Dimanche avec une liste de taches
   ordonnees (quoi cuisiner, en quelle quantite, pour combien de jours).
   Si pertinent, ajoute une session mi-semaine (Mar ou Mer soir).

4. COUT : Calcule le cout alloue de chaque ingredient (fraction du paquet).
   Le cost du souper = cout total pour 2 portions; cost_per_portion = cost/2.
   Les diners-leftover ont cost = 0 et cost_per_portion = 0.

5. Respecte les cibles proteiques, les regles de gros formats, et la limite
   de 6 legumes/fruits frais pour la semaine.

6. Liste d'epicerie : groupee par magasin, quantites totales achetees,
   prix total du paquet (pas la fraction). Ne pas compter les leftovers deux fois.

7. MAXI D'ABORD : Priorise les items "store": "Maxi" dans toutes les recettes.
   Tout item non-Maxi utilise dans une recette DOIT apparaitre dans "alignement_prix"
   avec used_in_plan: true. Ajoute aussi jusqu'a 4 bons rabais concurrents
   (savings_pct >= 25%) non utilises dans le menu, avec used_in_plan: false.

FORMAT JSON ATTENDU :
{{
  "week_structure": {{
    "day_names": ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"],
    "cook_once_chain": [
      "Dimanche souper x2 -> Lundi diner",
      "Lundi souper x2 -> Mardi diner",
      "Mardi souper x2 -> Mercredi diner",
      "Mercredi souper x2 -> Jeudi diner",
      "Jeudi souper x2 -> Vendredi diner",
      "Vendredi souper x2 -> Samedi diner"
    ]
  }},
  "cooking_schedule": {{
    "sunday_batch": {{
      "duration_min": 120,
      "recommendation": "Option A : tout en une session ou Option B : dimanche + mercredi",
      "tasks": [
        {{"task": "Cuire riz brun 600g cru (pour 4 jours)", "duration_min": 45, "yields": "1.8 kg cuit"}},
        {{"task": "Cuire lentilles 400g (j.2 diner + j.4 souper)", "duration_min": 30, "yields": "1 kg cuit"}},
        {{"task": "Preparer curry de pois chiches x2 (-> Lundi diner)", "duration_min": 35, "yields": "2 portions"}}
      ]
    }},
    "midweek_session": {{
      "day": "Mercredi",
      "duration_min": 35,
      "tasks": [
        {{"task": "Cuire quinoa 300g cru (j.4-j.6)", "duration_min": 20}},
        {{"task": "Mariner tofu pour Jeudi soir", "duration_min": 10}}
      ]
    }}
  }},
  "fresh_ingredients_plan": {{
    "items": ["epinard", "brocoli", "poivron rouge", "champignon", "avocat"],
    "count": 5,
    "usage_order": "Epinards j.1-2 -> brocoli j.3-4 -> poivrons j.5 -> champignons j.6 -> avocats j.7"
  }},
  "bulk_items_reuse": [
    {{
      "item": "Carottes sac 5 kg",
      "store": "Maxi",
      "total_price": 3.99,
      "total_qty": "5000g",
      "uses": [
        {{"day": 1, "meal": "dinner", "form": "carottes rotees au cumin", "qty": "400g", "cost_allocated": 0.32}},
        {{"day": 3, "meal": "dinner", "form": "salade de carottes rapees", "qty": "300g", "cost_allocated": 0.24}},
        {{"day": 5, "meal": "dinner", "form": "soupe carottes-gingembre", "qty": "500g", "cost_allocated": 0.40}}
      ]
    }}
  ],
  "meal_plan": [
    {{
      "day": 1,
      "day_name": "Dimanche",
      "is_batch_cooking_day": true,
      "breakfast": {{
        "name": "Gruau proteines aux noix",
        "protein_sources": ["yogourt grec", "graines de chia"],
        "good_fats": ["amandes"],
        "ingredients": [
          {{"item": "Flocons d'avoine", "store": "garde-manger", "qty": "80g", "cost": 0.25}},
          {{"item": "Yogourt grec 2%", "store": "Metro", "qty": "175g", "cost": 0.85}},
          {{"item": "Amandes", "store": "Costco", "qty": "30g", "cost": 0.45}}
        ],
        "cost": 1.55,
        "cost_per_portion": 1.55,
        "macros": {{"protein_g": 22, "fat_g": 12, "carb_g": 35, "fiber_g": 6, "kcal": 340}}
      }},
      "lunch": {{
        "name": "Soupe aux lentilles (preparee lors du batch)",
        "protein_sources": ["lentilles"],
        "good_fats": ["huile d'olive"],
        "ingredients": [
          {{"item": "Lentilles rouges", "store": "IGA", "qty": "100g cru", "cost": 0.28}},
          {{"item": "Huile d'olive", "store": "garde-manger", "qty": "15ml", "cost": 0.20}}
        ],
        "cost": 0.48,
        "cost_per_portion": 0.48,
        "macros": {{"protein_g": 18, "fat_g": 5, "carb_g": 40, "fiber_g": 10, "kcal": 290}},
        "food_guide_check": {{"vegetables_pct": 50, "grains_pct": 25, "protein_pct": 25}}
      }},
      "dinner": {{
        "name": "Bol curry de pois chiches au riz brun",
        "prep_type": "cuisine",
        "portions_cooked": 2,
        "serves_next_day_lunch": true,
        "next_day_lunch_note": "-> Lundi diner (rechauffer 5 min)",
        "protein_type": "plant",
        "protein_sources": ["pois chiches"],
        "good_fats": ["huile d'olive"],
        "ingredients": [
          {{"item": "Pois chiches (boite 540ml)", "store": "Maxi", "qty": "2 x 540ml", "cost": 2.50}},
          {{"item": "Riz brun", "store": "garde-manger", "qty": "200g cru", "cost": 0.50}},
          {{"item": "Huile d'olive", "store": "garde-manger", "qty": "30ml", "cost": 0.40}}
        ],
        "cost": 3.40,
        "cost_per_portion": 1.70,
        "note": "SESSION 1 : cuisiner 2 portions — la 2e portion devient le diner de Lundi",
        "macros": {{"protein_g": 42, "fat_g": 12, "carb_g": 70, "fiber_g": 14, "kcal": 560}},
        "food_guide_check": {{"vegetables_pct": 50, "grains_pct": 25, "protein_pct": 25}}
      }}
    }},
    {{
      "day": 2,
      "day_name": "Lundi",
      "is_batch_cooking_day": false,
      "breakfast": {{
        "name": "...",
        "protein_sources": ["..."],
        "good_fats": ["..."],
        "ingredients": ["..."],
        "cost": 0.0,
        "cost_per_portion": 0.0,
        "macros": {{"protein_g": 0, "fat_g": 0, "carb_g": 0, "fiber_g": 0, "kcal": 0}}
      }},
      "lunch": {{
        "name": "Curry de pois chiches (reste du souper Dimanche)",
        "is_leftover": true,
        "leftover_source": "Dimanche souper",
        "prep_time_min": 5,
        "prep_note": "Rechauffer seulement — aucune preparation requise",
        "protein_sources": ["pois chiches"],
        "ingredients": [],
        "cost": 0,
        "cost_per_portion": 0,
        "macros": {{"protein_g": 32, "fat_g": 10, "carb_g": 55, "fiber_g": 14, "kcal": 460}}
      }},
      "dinner": {{
        "name": "Bol poulet effiloche sauce soja-gingembre au quinoa",
        "prep_type": "assemblage",
        "assembly_components": ["poulet role pre-cuit (Dimanche)", "quinoa pre-cuit (Dimanche)", "epinards frais", "sauce soja-gingembre (5 min)"],
        "prep_time_min": 8,
        "portions_cooked": 2,
        "serves_next_day_lunch": true,
        "next_day_lunch_note": "-> Mardi diner (rechauffer 5 min)",
        "protein_type": "animal",
        "protein_sources": ["poulet"],
        "good_fats": ["sesame"],
        "ingredients": [
          {{"item": "Poulet role pre-cuit", "store": "pre-cuit Dimanche", "qty": "200g", "cost": 1.20}},
          {{"item": "Quinoa pre-cuit", "store": "pre-cuit Dimanche", "qty": "180g", "cost": 0.40}},
          {{"item": "Epinards frais", "store": "Maxi", "qty": "60g", "cost": 0.30}},
          {{"item": "Sauce soja + gingembre", "store": "garde-manger", "qty": "30ml", "cost": 0.20}}
        ],
        "cost": 2.10,
        "cost_per_portion": 1.05,
        "note": "ASSEMBLAGE — aucune cuisson, composants pre-cuits du dimanche, sauce differente",
        "macros": {{"protein_g": 45, "fat_g": 10, "carb_g": 65, "fiber_g": 6, "kcal": 540}},
        "food_guide_check": {{"vegetables_pct": 50, "grains_pct": 25, "protein_pct": 25}}
      }}
    }}
  ],
  "weekly_nutrition_summary": {{
    "animal_protein_meals": 1,
    "plant_protein_meals": 5,
    "avg_daily_protein_g": 165,
    "avg_daily_fat_g": 49,
    "avg_daily_carb_g": 275,
    "avg_daily_fiber_g": 35,
    "avg_daily_kcal": 2200,
    "protein_pct_kcal": 30,
    "fat_pct_kcal": 20,
    "carb_pct_kcal": 50,
    "meals_under_3_dollars_per_portion": 19,
    "leftover_lunches": 6,
    "total_unique_recipes": 8
  }},
  "grocery_list": [
    {{
      "store": "Nom du magasin",
      "items": [
        {{"name": "Pois chiches boites 540ml", "qty": "4 boites", "unit_price": 1.25, "total": 5.00}},
        {{"name": "Tofu ferme 454g", "qty": "2 paquets", "unit_price": 2.99, "total": 5.98}}
      ],
      "store_total": 10.98
    }}
  ],
  "grand_total": 70.00,
  "savings_vs_regular": 28.00,
  "alignement_prix": [
    {{
      "item": "Tofu ferme 450g",
      "store_concurrent": "IGA",
      "price": 2.49,
      "unit": "450 g",
      "savings_pct": 38,
      "used_in_plan": true,
      "note": "Utilise Mardi souper — demander alignement chez Maxi (prix regulier ~3.99$)"
    }},
    {{
      "item": "Saumon Atlantique",
      "store_concurrent": "Metro",
      "price": 7.99,
      "unit": "kg",
      "savings_pct": 40,
      "used_in_plan": false,
      "note": "Excellent rabais non utilise cette semaine — peut remplacer la viande planifiee"
    }}
  ],
  "notes": "Conseils: precuire une grande quantite de riz le dimanche; variantes de sauces pour les leftovers"
}}

RAPPEL FORMATAGE JSON (obligatoire) :
- Aucun texte en dehors de l'objet JSON (pas d'introduction, pas de conclusion).
- Aucun bloc markdown (pas de ```json).
- Pas de virgule trainante apres le dernier element d'un tableau ou d'un objet.
- Guillemets internes dans les chaines echappes avec \".
- Pas de retour a la ligne (\\n) dans les valeurs de type chaine.
- Tous les champs numeriques valent 0.0 si inconnus (jamais null).
"""


class MealPlanner:
    """
    Envoie les deals Flipp a Claude et recoit un plan de repas + liste d'epicerie.
    """

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def plan(self, deals: list[Deal]) -> dict[str, Any]:
        """
        Genere un plan de repas 7 jours (Dim->Sam) avec cook-once.
        Retourne le JSON parse de la reponse Claude.
        """
        proteins = [d for d in deals if d.category == "proteins"]
        grains   = [d for d in deals if d.category == "whole_grains"]
        vegs     = [d for d in deals if d.category == "vegetables_fruits"]
        fats     = [d for d in deals if d.category == "good_fats"]

        def sort_key(d: Deal):
            return (-(d.savings_pct or 0), d.price)

        proteins.sort(key=sort_key)
        grains.sort(key=sort_key)
        vegs.sort(key=sort_key)
        fats.sort(key=sort_key)

        def _summarize(deals_list: list[Deal], limit: int) -> str:
            items = [
                {
                    "store": d.store,
                    "name": d.name,
                    "price": d.price,
                    "original_price": d.original_price,
                    "unit": d.unit,
                    "sale_story": d.sale_story,
                    "savings_pct": d.savings_pct,
                }
                for d in deals_list[:limit]
            ]
            return json.dumps(items, ensure_ascii=False, indent=2)

        user_message = _USER_TEMPLATE.format(
            proteins_json=_summarize(proteins, 50),
            grains_json=_summarize(grains, 30),
            veg_json=_summarize(vegs, 25),
            fats_json=_summarize(fats, 20),
        )

        print("  [planner] Envoi a Claude (7 jours Dim-Sam, cook-once + FCEN)...")

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        stop_reason = response.stop_reason
        raw = response.content[0].text.strip()

        if stop_reason == "max_tokens":
            print(f"  [planner] AVERTISSEMENT : reponse tronquee (stop_reason=max_tokens).")

        raw = _extract_json(raw)

        # Dump de debug pour inspecter le JSON brut en cas d'echec
        _DEBUG_PATH.write_text(raw, encoding="utf-8")

        try:
            result = json.loads(raw)
            _DEBUG_PATH.unlink(missing_ok=True)   # nettoyage si OK
            return result
        except json.JSONDecodeError as exc:
            # Montrer le contexte autour de l'erreur (±3 lignes)
            lines = raw.splitlines()
            err_line = exc.lineno - 1
            ctx_start = max(0, err_line - 2)
            ctx = "\n".join(
                f"  {'>>>' if i == err_line else '   '} {lines[i]}"
                for i in range(ctx_start, min(len(lines), err_line + 3))
            )
            raise ValueError(
                f"JSON invalide a la ligne {exc.lineno}, col {exc.colno}: {exc.msg}\n"
                f"Contexte:\n{ctx}\n\n"
                f"JSON brut sauvegarde dans: {_DEBUG_PATH}"
            ) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """
    Extrait et nettoie le JSON brut de la réponse Claude.
    Gère : blocs markdown, texte avant/après, trailing commas, retours à la ligne.
    """
    import re

    # Retirer les blocs ```json ... ``` ou ``` ... ```
    text = re.sub(r"```(?:json)?\s*", "", text)

    # Isoler le premier objet JSON { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    # Supprimer les virgules traînantes avant } ou ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text
