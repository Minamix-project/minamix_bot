import random
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

MAX_DICE = 200
MAX_TOTAL_DRAWS = 10000
MAX_SIDES = 1000000
MAX_EXPRESSION_LENGTH = 1000
MAX_SETS = 20
MAX_PARTS = 4
EXPLODE_CAP = 100
REROLL_CAP = 100


class ParseError(Exception):
    pass


class RollLimitError(ParseError):
    pass


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

    # NcodX - Chronicles of Darkness: N d10, success >= 8, 10 explodes once
    m = re.match(r'^(\d+)cod(\d*)$', e)
    if m:
        n = m.group(1)
        return f"{n}d10 ie10 t8"

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
        step = max(1, min(step, 50))
        return _ED_STEPS.get(step, "1d6")

    return expr  # no alias matched, return as-is


# ─── Single expression roller ─────────────────────────────────────────────────

def _roll_single(expr: str) -> str:
    expr = expr.strip()
    original = expr

    # Flags
    simplified = bool(re.search(r'\bsl?\b', expr))
    no_results = bool(re.search(r'\bnr\b', expr))
    unsorted = bool(re.search(r'\bul\b', expr))
    expr = re.sub(r'\b(nr|ul)\b', '', expr)
    expr = re.sub(r'(?<!\w)s(?!\w)', '', expr).strip()

    # Dice match: XdY or dY
    dice_m = re.match(r'^(\d*)d(\d+)(.*)', expr, re.I)
    if not dice_m:
        raise ParseError(f"Syntaxe invalide : `{original}`")

    n_dice = int(dice_m.group(1)) if dice_m.group(1) else 1
    sides = int(dice_m.group(2))
    rem = dice_m.group(3).strip()

    _validate_count(n_dice)
    if sides < 1:
        raise ParseError("Le dé doit avoir au moins 1 face.")
    if sides > MAX_SIDES:
        raise ParseError(f"Maximum {MAX_SIDES} faces par dé.")

    # Parse modifiers (order matters)
    inf_explode = False
    explode_val = None
    inf_reroll = False
    reroll_val = None
    keep_high = None
    keep_low = None
    drop_low = None
    target = None
    fail_val = None
    botch_val = None
    arith_op = None
    arith_val = 0.0

    def _consume(pattern):
        nonlocal rem
        m = re.search(pattern, rem)
        if m:
            rem = rem[:m.start()] + rem[m.end():]
            rem = rem.strip()
        return m

    m = _consume(r'ie(\d+)?')
    if m:
        inf_explode = True
        explode_val = int(m.group(1)) if m.group(1) else sides

    m = _consume(r'\be(\d+)?')
    if m and not inf_explode:
        explode_val = int(m.group(1)) if m.group(1) else sides

    m = _consume(r'ir(\d+)')
    if m:
        inf_reroll = True
        reroll_val = int(m.group(1))

    m = _consume(r'\br(\d+)')
    if m and not inf_reroll:
        reroll_val = int(m.group(1))

    m = _consume(r'kl(\d+)')
    if m:
        keep_low = int(m.group(1))

    m = _consume(r'\bk(\d+)')
    if m and keep_low is None:
        keep_high = int(m.group(1))

    m = _consume(r'\bd(\d+)')
    if m and keep_high is None and keep_low is None:
        drop_low = int(m.group(1))

    m = _consume(r't(\d+)')
    if m:
        target = int(m.group(1))

    m = _consume(r'f(\d+)')
    if m:
        fail_val = int(m.group(1))

    m = _consume(r'b(\d+)')
    if m:
        botch_val = int(m.group(1))

    m = _consume(r'([+\-])(\d+(?:\.\d+)?)')
    if m:
        arith_op = m.group(1)
        arith_val = float(m.group(2))

    m = _consume(r'([*/])(\d+(?:\.\d+)?)')
    if m:
        arith_op = m.group(1)
        arith_val = float(m.group(2))

    # Roll
    rolls = []
    for _ in range(n_dice):
        r = _draw(sides)
        if reroll_val is not None:
            if inf_reroll:
                count = 0
                while r <= reroll_val and count < REROLL_CAP:
                    r = _draw(sides)
                    count += 1
            else:
                if r <= reroll_val:
                    r = _draw(sides)
        rolls.append(r)

    # Exploding
    extra = []
    if explode_val is not None:
        to_explode = [r for r in rolls if r >= explode_val]
        count = 0
        while to_explode and count < EXPLODE_CAP:
            next_explode = []
            for _ in to_explode:
                new_r = _draw(sides)
                extra.append(new_r)
                if inf_explode and new_r >= explode_val:
                    next_explode.append(new_r)
            to_explode = next_explode if inf_explode else []
            count += 1

    all_rolls = rolls + extra

    # Keep / drop
    kept = list(all_rolls)
    dropped = []

    if keep_high is not None:
        pairs = sorted(enumerate(kept), key=lambda x: -x[1])
        drop_idx = {i for i, _ in pairs[keep_high:]}
        dropped = [v for i, v in enumerate(kept) if i in drop_idx]
        kept = [v for i, v in enumerate(kept) if i not in drop_idx]
    elif keep_low is not None:
        pairs = sorted(enumerate(kept), key=lambda x: x[1])
        drop_idx = {i for i, _ in pairs[keep_low:]}
        dropped = [v for i, v in enumerate(kept) if i in drop_idx]
        kept = [v for i, v in enumerate(kept) if i not in drop_idx]
    elif drop_low is not None:
        pairs = sorted(enumerate(kept), key=lambda x: x[1])
        drop_idx = {i for i, _ in pairs[:drop_low]}
        dropped = [v for i, v in enumerate(kept) if i in drop_idx]
        kept = [v for i, v in enumerate(kept) if i not in drop_idx]

    # Total
    dice_sum = sum(kept)
    if target is not None:
        successes = sum(1 for v in kept if v >= target)
        failures = sum(1 for v in kept if fail_val and v <= fail_val)
        botches = sum(1 for v in kept if botch_val and v <= botch_val)
        total = successes - failures - botches
    else:
        total = dice_sum
        if arith_op == '+':
            total += int(arith_val)
        elif arith_op == '-':
            total -= int(arith_val)
        elif arith_op == '*':
            total = int(total * arith_val)
        elif arith_op == '/':
            total = int(total / arith_val) if arith_val else total

    # Format
    label = f"{n_dice}d{sides}"
    if arith_op in ('+', '-') and target is None:
        label += f" {arith_op}{int(arith_val)}"
    elif arith_op in ('*', '/') and target is None:
        label += f" {arith_op}{int(arith_val)}"

    if simplified:
        if target is not None:
            return f"🎲 {label} → **{total}** succès"
        return f"🎲 {label} → **{total}**"

    if not unsorted:
        display_kept = sorted(kept, reverse=True)
    else:
        display_kept = list(kept)

    if target is not None:
        kept_str = " ".join(f"**{v}**" if v >= target else str(v) for v in display_kept)
    else:
        kept_str = " ".join(str(v) for v in display_kept)

    dropped_str = f" ~~{' '.join(str(v) for v in dropped)}~~" if dropped else ""
    extra_str = f" +({' '.join(str(v) for v in extra)})" if extra else ""

    dice_block = f"`[{kept_str}{dropped_str}{extra_str}]`" if not no_results else ""

    if target is not None:
        result = f"**{total}** succès"
        if fail_val:
            result += f" ({successes}✓ {failures}✗)"
        return f"🎲 {label} {dice_block} → {result}".strip()

    return f"🎲 {label} {dice_block} → **{total}**".strip()


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
    m = re.match(r'(\d+)', args.strip())
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
    m = re.match(r'(\d+)', args.strip())
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
    m = re.match(r'(\d+)', args.strip())
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
    for part in parts:
        if not part:
            continue
        try:
            lines.append(_roll_part(part))
        except RollLimitError:
            raise
        except ParseError as e:
            lines.append(f"❌ {e}")

    output = "\n".join(lines)
    if comment:
        output = f"**{comment}**\n{output}"

    return output, private


def _roll_part(expr: str) -> str:
    expr = expr.strip()
    # Normalize spaces around + and - before dice patterns: "5d6 + 2d10" → "5d6+2d10"
    expr = re.sub(r'\s*([+-])\s*(?=\d)', r'\1', expr)
    low = expr.lower()

    # Special systems
    if low == "dndstats":
        return _roll_dndstats()

    if low == "age":
        return _roll_age()

    m = re.match(r'^(\d+)df$', low)
    if m:
        return _roll_fate(int(m.group(1)))

    m = re.match(r'^wng\s*(.*)', low)
    if m:
        return _roll_wng(m.group(1))

    m = re.match(r'^dh\s*(.*)', low)
    if m:
        return _roll_dh(m.group(1))

    m = re.match(r'^gb\s*(.*)', low)
    if m:
        return _roll_gb(m.group(1))

    m = re.match(r'^(\d+)wh(\d+)\+?$', low)
    if m:
        return _roll_wh(int(m.group(1)), int(m.group(2)))

    # Multiple sets: "N XdY ..."
    m = re.match(r'^(\d+)\s+(\d*d\d+.*)', low)
    if m:
        n_sets = int(m.group(1))
        if not 1 <= n_sets <= MAX_SETS:
            raise ParseError(f"Le nombre de séries doit être compris entre 1 et {MAX_SETS}.")
        sub = m.group(2)
        results = []
        for i in range(n_sets):
            try:
                results.append(f"`#{i+1}` {_roll_single(sub)}")
            except RollLimitError:
                raise
            except ParseError as e:
                results.append(f"❌ {e}")
                break
        return "\n".join(results)

    # Multi-dice groups: "5d6+2d10" or "3d6-1d4+2"
    groups = _split_dice_groups(expr)
    if groups is not None:
        return _roll_dice_groups(groups)

    # Alias expansion
    expanded = _expand_alias(expr)
    if expanded and expanded != expr:
        return _roll_single(expanded)

    return _roll_single(expr)


def _split_dice_groups(expr: str):
    """Split '5d6+2d10' into [('+','5d6'), ('+','2d10')]. Returns None if single group."""
    tokens = re.split(r'(?=[+-]\d*d\d)', expr.strip())
    if len(tokens) <= 1:
        return None
    groups = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token[0] in '+-':
            groups.append((token[0], token[1:].strip()))
        else:
            groups.append(('+', token))
    return groups if len(groups) > 1 else None


def _roll_dice_groups(groups: list) -> str:
    """Roll multiple dice groups and sum them."""
    parts_display = []
    label_parts = []
    grand_total = 0

    for sign, part in groups:
        result_str = _roll_single(part)

        # Extract numeric total
        m = re.search(r'→ \*\*(-?\d+)\*\*', result_str)
        val = int(m.group(1)) if m else 0
        grand_total += val if sign == '+' else -val

        # Extract dice block
        m2 = re.search(r'`\[(.+?)\]`', result_str)
        dice_block = f"`[{m2.group(1)}]`" if m2 else f"`[{val}]`"

        # Flat modifier at the end of the part (e.g. "+50" in "4d8+50")
        mod_m = re.search(r'([+-]\d+)$', part)
        mod_str = f" {mod_m.group(1)}" if mod_m else ""

        block_with_mod = f"{dice_block}{mod_str}"

        if parts_display:
            parts_display.append(f"{sign} {block_with_mod}")
            label_parts.append(f"{sign}{part}")
        else:
            parts_display.append(block_with_mod)
            label_parts.append(part)

    label = "".join(label_parts)
    display = " ".join(parts_display)
    return f"🎲 {label} {display} → **{grand_total}**"


def get_help() -> str:
    return (
        "**Syntaxe de base**\n"
        "`XdY` — lancer X dés à Y faces · `2d6+3` · `1d20-1` · `4d6*2`\n"
        "`N XdY` — N séries (ex: `6 4d6`) · `;` — séparer jusqu'à 4 lancers\n\n"
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
        "Les résultats longs sont résumés, avec le détail complet en fichier joint."
    )
