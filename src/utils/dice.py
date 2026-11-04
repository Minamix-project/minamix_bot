import random
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from src.utils.dice_expression import ParseError, RollLimitError, parse_expression

MAX_DICE = 200
MAX_TOTAL_DRAWS = 10000
MAX_SIDES = 1000000
MAX_EXPRESSION_LENGTH = 1000
MAX_SETS = 20
MAX_PARTS = 4
EXPLODE_CAP = 100
REROLL_CAP = 100


@dataclass
class RollBudget:
    draws: int = 0

    def consume(self):
        if self.draws >= MAX_TOTAL_DRAWS:
            raise RollLimitError(
                f"Maximum {MAX_TOTAL_DRAWS} tirages par commande, relances et explosions comprises. "
                "Réduis le nombre de dés ou de séries."
            )
        self.draws += 1


_ROLL_BUDGET: ContextVar[RollBudget | None] = ContextVar("dice_roll_budget", default=None)


def _d(sides: int) -> int:
    return random.randint(1, max(1, sides))


def _draw(sides: int) -> int:
    budget = _ROLL_BUDGET.get()
    if budget is not None:
        budget.consume()
    return _d(sides)


def _validate_count(count: int):
    if count < 1:
        raise ParseError("Il faut lancer au moins 1 dé.")
    if count > MAX_DICE:
        raise ParseError(f"Maximum {MAX_DICE} dés par groupe.")


# ─── Earthdawn step table ─────────────────────────────────────────────────────

_ED_STEPS = {
    1: "1d4-2", 2: "1d4-1", 3: "1d4", 4: "1d6", 5: "1d8", 6: "1d10",
    7: "1d12", 8: "2d6", 9: "1d8+1d6", 10: "2d8", 11: "1d10+1d8",
    12: "2d10", 13: "1d12+1d10", 14: "2d12", 15: "1d10+2d6+1d4",
    16: "1d10+1d8+1d6", 17: "1d10+2d8", 18: "1d10+1d8+1d6+1",
    19: "2d10+1d8", 20: "3d10",
}
for _i in range(21, 51):
    _base = _ED_STEPS[20]
    _bonus = (_i - 20)
    _ED_STEPS[_i] = f"{_base}+{_bonus}"


# ─── Alias expander ───────────────────────────────────────────────────────────

def _expand_alias(expr: str) -> Optional[str]:
    e = expr.strip().lower()

    # dndstats
    if e == "dndstats":
        return None  # handled specially

    # advantage / disadvantage
    if e == "+d20":
        return "2d20 k1"
    if e == "-d20":
        return "2d20 kl1"

    # attack / skill / save +/-N
    m = re.match(r'^(attack|skill|save)\s*([+-]?\d+)$', e)
    if m:
        mod = int(m.group(2))
        sign = "+" if mod >= 0 else ""
        return f"1d20{sign}{mod}"

    # NcodX - N d10, success >= X (default 8), exploding tens.
    m = re.match(r'^(\d+)cod(\d*)$', e)
    if m:
        n = m.group(1)
        target = m.group(2) or "8"
        return f"{n}d10 ie10 t{target}"

    # NwodX - World of Darkness: N d10, success >= X (default 8)
    m = re.match(r'^(\d+)wod(\d+)?$', e)
    if m:
        n = m.group(1)
        target = m.group(2) or "8"
        return f"{n}d10 t{target}"

    # Ndf - Fate/Fudge dice
    m = re.match(r'^(\d+)df$', e)
    if m:
        return None  # handled specially

    # NwhX(+) - Warhammer Fantasy: N d100, success <= X
    m = re.match(r'^(\d+)wh(\d+)\+?$', e)
    if m:
        n, target = m.group(1), m.group(2)
        return f"{n}d100 t1 r{target}"  # handled specially

    # age - AGE system: 3d6 (one is the "dragon die")
    if e == "age":
        return None  # handled specially

    # srN - Shadowrun: N d6, success >= 5
    m = re.match(r'^sr(\d+)$', e)
    if m:
        return f"{m.group(1)}d6 t5"

    # edN or edNeX - Earthdawn step
    m = re.match(r'^ed(\d+)(e\d+)?$', e)
    if m:
        step = int(m.group(1))
        if m.group(2):
            raise ParseError("L'alias Earthdawn accepte `edN` sans suffixe. Pour personnaliser les explosions, utilise directement une expression de dés.")
        if not 1 <= step <= 50:
            raise ParseError("Le pas Earthdawn doit être compris entre 1 et 50.")
        return _ED_STEPS.get(step, "1d6")

    return expr  # no alias matched, return as-is


def _parse_math(expression: str):
    return parse_expression(expression, max_dice=MAX_DICE, max_sides=MAX_SIDES)


def _render_math(parsed) -> str:
    return parsed.roll(_draw, explode_cap=EXPLODE_CAP, reroll_cap=REROLL_CAP)


# ─── Special handlers ─────────────────────────────────────────────────────────

def _roll_dndstats() -> str:
    sets = []
    for _ in range(6):
        rolls = [_draw(6) for _ in range(4)]
        kept = sorted(rolls, reverse=True)[:3]
        total = sum(kept)
        dropped = min(rolls)
        sets.append(f"`[{' '.join(str(r) for r in sorted(rolls, reverse=True)[:3])} ~~{dropped}~~]` → **{total}**")
    return "🎲 DnD Stats (4d6 drop lowest × 6)\n" + "\n".join(sets)


def _roll_fate(n: int) -> str:
    _validate_count(n)
    symbols = {-1: "**-**", 0: "**□**", 1: "**+**"}
    rolls = [_draw(3) - 2 for _ in range(n)]
    total = sum(rolls)
    display = " ".join(symbols[r] for r in rolls)
    sign = "+" if total >= 0 else ""
    return f"🎲 {n}dF `[{display}]` → **{sign}{total}**"


def _roll_age() -> str:
    d1, dragon, d2 = _draw(6), _draw(6), _draw(6)
    total = d1 + dragon + d2
    return (
        f"🎲 AGE `[{d1} **{dragon}** {d2}]` → **{total}**\n"
        f"*(dé du dragon : **{dragon}**)*"
    )


def _roll_wng(args: str) -> str:
    m = re.fullmatch(r'(\d+)', args.strip())
    if not m:
        raise ParseError("Usage : `wng <dés>` — ex: `wng 6`")
    n = int(m.group(1))
    _validate_count(n)
    rolls = [_draw(6) for _ in range(n)]
    wrath = rolls[0]
    pool = rolls[1:]

    successes = sum(1 for r in pool if r >= 4) + (2 if wrath >= 6 else 1 if wrath >= 4 else 0)
    icons = []
    for r in pool:
        icons.append(f"**{r}**" if r >= 4 else str(r))
    wrath_icon = f"[W:**{wrath}**]"

    result = f"🎲 Wrath & Glory {wrath_icon} `[{' '.join(icons)}]` → **{successes}** succès"
    if wrath == 1:
        result += "\n⚠️ *Complication du Destin !*"
    elif wrath == 6:
        result += "\n✨ *Gloire !*"
    return result


def _roll_dh(args: str) -> str:
    m = re.fullmatch(r'(\d+)', args.strip())
    if not m:
        raise ParseError("Usage : `dh <compétence>` — ex: `dh 45`")
    skill = int(m.group(1))
    roll = _draw(100)
    success = roll <= skill
    icon = "✅" if success else "❌"
    result = f"🎲 Dark Heresy `[{roll}]` vs {skill} → {icon} {'Succès' if success else 'Échec'}"
    if roll % 11 == 0:
        result += f"\n{'⚡ Fureur du Juste !' if success else '💀 Désastre !'}"
    return result


def _roll_gb(args: str) -> str:
    m = re.fullmatch(r'(\d+)', args.strip())
    if args.strip() and not m:
        raise ParseError("Usage : `gb <dés>` — ex: `gb 3`")
    n = int(m.group(1)) if m else 1
    _validate_count(n)
    rolls = [_draw(6) for _ in range(n)]
    total = sum(rolls)
    # Godbound damage chart
    if total <= 3:
        dmg = 1
    elif total <= 5:
        dmg = 2
    elif total <= 9:
        dmg = 4
    elif total <= 11:
        dmg = 6
    else:
        dmg = 8
    kept_str = " ".join(str(r) for r in sorted(rolls, reverse=True))
    return f"🎲 Godbound `[{kept_str}]` (total {total}) → **{dmg}** dégâts"


# ─── Warhammer Fantasy ────────────────────────────────────────────────────────

def _roll_wh(n: int, target: int) -> str:
    _validate_count(n)
    rolls = [_draw(100) for _ in range(n)]
    successes = sum(1 for r in rolls if r <= target)
    kept_str = " ".join(f"**{r}**" if r <= target else str(r) for r in rolls)
    return f"🎲 {n}d100 (seuil {target}) `[{kept_str}]` → **{successes}** succès"


# ─── Main entry point ─────────────────────────────────────────────────────────

def roll(expression: str) -> tuple[str, bool]:
    """Returns (output_text, is_private)."""
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ParseError(f"Maximum {MAX_EXPRESSION_LENGTH} caractères par commande.")
    if not expression.strip():
        raise ParseError("Indique un lancer, par exemple `2d6`.")
    # Bound integer conversion and arithmetic before parsing aliases/modifiers.
    if any(len(number) > 9 for number in re.findall(r"\d+", expression.split("!", 1)[0])):
        raise ParseError("Les nombres sont limités à 9 chiffres.")
    token = _ROLL_BUDGET.set(RollBudget())
    try:
        return _evaluate(expression)
    finally:
        _ROLL_BUDGET.reset(token)


def _evaluate(expression: str) -> tuple[str, bool]:
    expression = expression.strip()

    # Private flag
    private = False
    if expression.lower().startswith("p "):
        private = True
        expression = expression[2:].strip()

    # Comment
    comment = ""
    if "!" in expression:
        idx = expression.index("!")
        comment = expression[idx + 1:].strip()
        expression = expression[:idx].strip()

    parts = [p.strip() for p in expression.split(";") if p.strip()]
    if not parts:
        raise ParseError("Indique un lancer, par exemple `2d6`.")
    if len(parts) > MAX_PARTS:
        raise ParseError(f"Maximum {MAX_PARTS} lancers séparés par des points-virgules.")

    lines = []
    valid_parts = 0
    for part in parts:
        if not part:
            continue
        try:
            lines.append(_roll_part(part))
            valid_parts += 1
        except RollLimitError:
            raise
        except ParseError as e:
            lines.append(f"❌ {e}")

    output = "\n".join(lines)
    if comment:
        output = f"**{comment}**\n{output}"

    return output, private or valid_parts == 0


def _roll_part(expr: str) -> str:
    expr = expr.strip()
    low = expr.lower()
    if low == "dndstats":
        return _roll_dndstats()
    if low == "age":
        return _roll_age()
    match = re.fullmatch(r"(\d+)df", low)
    if match:
        return _roll_fate(int(match[1]))
    for name, handler in (("wng", _roll_wng), ("dh", _roll_dh), ("gb", _roll_gb)):
        match = re.fullmatch(name + r"\s*(\d*)", low)
        if match:
            return handler(match[1])
    match = re.fullmatch(r"(\d+)wh(\d+)\+?", low)
    if match:
        return _roll_wh(int(match[1]), int(match[2]))

    # Parse the complete expression once before evaluating any repeated sets.
    match = re.fullmatch(r"(\d+)\s+((?:\d*d\d+|\().*)", low)
    if match:
        n_sets = int(match[1])
        if not 1 <= n_sets <= MAX_SETS:
            raise ParseError(f"Le nombre de séries doit être compris entre 1 et {MAX_SETS}.")
        parsed = _parse_math(match[2])
        return "\n".join(f"`#{index + 1}` {_render_math(parsed)}" for index in range(n_sets))

    expanded = _expand_alias(expr)
    return _render_math(_parse_math(expanded if expanded is not None else expr))


def get_help() -> str:
    return (
        "**Syntaxe de base**\n"
        "`XdY` — lancer X dés à Y faces · `2d6+3` · `1d20-1` · `4d6*2`\n"
        "Calcul : `+ - * /` et parenthèses ; `* /` sont prioritaires\n"
        "Exemples : `1d6+5+2` · `(1d6+2)*3` · `1d6/2` (résultat exact)\n"
        "`N XdY...` — N séries, ex: `6 4d6` ou `2 1d6+1d20`\n"
        "`;` — séparer jusqu'à 4 lancers\n\n"
        "**Modificateurs**\n"
        "`k3` garder 3 hauts · `kl3` garder 3 bas · `d1` drop 1 bas\n"
        "`e6` exploser sur 6 · `ie6` exploser infiniment · `e` exploser sur max\n"
        "`r2` relancer si ≤ 2 · `ir2` relancer infiniment\n"
        "`t7` succès sur ≥ 7 · `f1` échec sur ≤ 1 · `b1` botch sur ≤ 1\n"
        "`s` résultat simplifié · `nr` sans détail · `ul` non trié · `p` privé\n"
        "`! texte` ajouter un commentaire\n\n"
        "**Alias**\n"
        "`NcodX` Chronicles of Darkness · `NwodX` World of Darkness\n"
        "`Ndf` dés Fate/Fudge · `NwhX` Warhammer Fantasy\n"
        "`srN` Shadowrun · `edN` Earthdawn (pas N) · `age` AGE system\n"
        "`dndstats` 6×4d6 drop lowest · `attack/skill/save ±N`\n"
        "`+d20` avantage · `-d20` désavantage\n\n"
        "**Systèmes**\n"
        "`wng N` Wrath & Glory · `dh N` Dark Heresy 2e · `gb N` Godbound\n\n"
        "**Limites**\n"
        f"{MAX_DICE} dés par groupe · {MAX_SETS} séries · {MAX_PARTS} lancers par commande\n"
        f"{MAX_TOTAL_DRAWS} tirages au total, relances et explosions comprises\n"
        "Les résultats longs sont résumés, avec le détail complet en fichier joint.\n"
        "Un jet interrompu par une limite est annulé, sans résultat partiel validé.\n"
        "Les seuils qui imposent une boucle sans fin et les divisions par zéro sont refusés."
    )
