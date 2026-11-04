"""Strict dice-expression parsing and exact arithmetic, without Python eval."""

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
import re


class ParseError(Exception):
    pass


class RollLimitError(ParseError):
    pass


@dataclass(frozen=True)
class DiceSpec:
    count: int
    sides: int
    kind: str = "standard"
    explode: int | None = None
    infinite_explode: bool = False
    reroll: int | None = None
    infinite_reroll: bool = False
    selection: str | None = None
    selection_count: int = 0
    target: int | None = None
    fail: int | None = None
    botch: int | None = None

    def validate(self, max_dice: int, max_sides: int):
        if self.count < 1:
            raise ParseError("Il faut lancer au moins 1 dé.")
        if self.count > max_dice:
            raise ParseError(f"Maximum {max_dice} dés par groupe.")
        if not 1 <= self.sides <= max_sides:
            raise ParseError(f"Le nombre de faces par dé doit être compris entre 1 et {max_sides}.")
        if self.kind == "fate" and any(value is not None for value in (self.explode, self.reroll, self.target, self.fail, self.botch)):
            raise ParseError("Les dés Fate acceptent les calculs, k/kl/d et les options s/nr/ul, sans seuils de relance, explosion ou succès.")
        if self.explode is not None and not 1 <= self.explode <= self.sides:
            raise ParseError(f"Le seuil d'explosion doit être compris entre 1 et {self.sides}.")
        if self.reroll is not None and not 0 <= self.reroll <= self.sides:
            raise ParseError(f"Le seuil de relance doit être compris entre 0 et {self.sides}.")
        if self.infinite_reroll and self.reroll >= self.sides:
            raise ParseError("Relance sans fin impossible à terminer : le seuil doit être inférieur au nombre de faces.")
        minimum = self.reroll + 1 if self.infinite_reroll else 1
        if self.infinite_explode and self.explode <= minimum:
            raise ParseError("Explosion sans fin impossible à terminer : aucun résultat ne peut arrêter la chaîne avec ces seuils.")
        if self.selection in {"k", "kl"} and self.selection_count < 1:
            raise ParseError("Il faut garder au moins 1 dé avec k ou kl.")
        if self.selection and self.explode is None:
            self.validate_selection(self.count)
        if self.target is None and (self.fail is not None or self.botch is not None):
            raise ParseError("Les modificateurs f et b nécessitent un seuil de succès, par exemple `5d10 t8 f1`.")

    def validate_selection(self, available: int):
        if self.selection in {"k", "kl"} and self.selection_count > available:
            raise ParseError(f"Impossible de garder {self.selection_count} dés : ce groupe ne contient que {available} dé(s).")
        if self.selection == "d" and self.selection_count >= available:
            raise ParseError(f"Impossible d'écarter {self.selection_count} dés sur {available} : il faut conserver au moins un dé.")


def _apply(operator: str, left: Fraction, right: Fraction) -> Fraction:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if right == 0:
        raise ParseError("Division par zéro : le jet est annulé. Vérifie le nombre ou l'expression après `/`.")
    return left / right


def format_number(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    places = max(twos, fives)
    if denominator != 1 or places > 9:
        return f"{value.numerator}/{value.denominator}"
    scaled = abs(value.numerator) * 10 ** places // value.denominator
    whole, decimal = divmod(scaled, 10 ** places)
    sign = "-" if value < 0 else ""
    return f"{sign}{whole}.{decimal:0{places}d}".rstrip("0").rstrip(".")


@dataclass
class PoolResult:
    spec: DiceSpec
    kept: list[int]
    dropped: list[int]
    total: int
    extra_count: int

    def details(self, *, unsorted: bool) -> str:
        values = self.kept if unsorted else sorted(self.kept, reverse=True)
        def display(value):
            return {-1: "−", 0: "□", 1: "+"}[value] if self.spec.kind == "fate" else str(value)
        kept = " ".join(display(value) for value in values)
        dropped = " · Écartés : ~~`[" + " ".join(display(value) for value in self.dropped) + "]`~~" if self.dropped else ""
        return f"`[{kept}]`{dropped}"


def roll_pool(spec: DiceSpec, draw: Callable[[int], int], *, explode_cap: int, reroll_cap: int) -> PoolResult:
    def die():
        value = draw(spec.sides)
        if spec.kind == "fate":
            return value - 2
        if spec.reroll is None:
            return value
        if not spec.infinite_reroll:
            return draw(spec.sides) if value <= spec.reroll else value
        attempts = 0
        while value <= spec.reroll:
            if attempts >= reroll_cap:
                raise RollLimitError(
                    f"Jet annulé : limite de {reroll_cap} relances consécutives atteinte. "
                    "Aucun résultat partiel n'est validé. Réduis le seuil de relance."
                )
            value = draw(spec.sides)
            attempts += 1
        return value

    rolls = [die() for _ in range(spec.count)]
    extra = []
    if spec.explode is not None:
        pending = sum(value >= spec.explode for value in rolls)
        generations = 0
        while pending:
            if generations >= explode_cap:
                raise RollLimitError(
                    f"Jet annulé : limite de {explode_cap} explosions en chaîne atteinte. "
                    "Aucun résultat partiel n'est validé. Augmente le seuil d'explosion."
                )
            values = [die() for _ in range(pending)]
            extra.extend(values)
            pending = sum(value >= spec.explode for value in values) if spec.infinite_explode else 0
            generations += 1
    values = rolls + extra
    if spec.selection:
        spec.validate_selection(len(values))
    kept_indices = set(range(len(values)))
    if spec.selection:
        ordered = sorted(range(len(values)), key=lambda index: values[index], reverse=spec.selection == "k")
        if spec.selection == "d":
            kept_indices.difference_update(ordered[:spec.selection_count])
        else:
            kept_indices = set(ordered[:spec.selection_count])
    kept = [value for index, value in enumerate(values) if index in kept_indices]
    dropped = [value for index, value in enumerate(values) if index not in kept_indices]
    if spec.target is None:
        total = sum(kept)
    else:
        total = sum(value >= spec.target for value in kept)
        if spec.fail is not None:
            total -= sum(value <= spec.fail for value in kept)
        if spec.botch is not None:
            total -= sum(value <= spec.botch for value in kept)
    return PoolResult(spec, kept, dropped, total, len(extra))


@dataclass
class ParsedExpression:
    label: str
    tokens: list[DiceSpec | Fraction | str]
    flags: set[str]
    successes: bool

    def roll(self, draw: Callable[[int], int], *, explode_cap: int, reroll_cap: int) -> str:
        stack = []
        pools = []
        for token in self.tokens:
            if isinstance(token, DiceSpec):
                pool = roll_pool(token, draw, explode_cap=explode_cap, reroll_cap=reroll_cap)
                pools.append(pool)
                stack.append(Fraction(pool.total))
            elif isinstance(token, Fraction):
                stack.append(token)
            elif token == "neg":
                stack[-1] = -stack[-1]
            else:
                right, left = stack.pop(), stack.pop()
                stack.append(_apply(token, left, right))
        result = format_number(stack[0])
        if all(pool.spec.kind == "fate" for pool in pools) and stack[0] >= 0:
            result = "+" + result
        suffix = " succès" if self.successes else ""
        blocks = ""
        if not self.flags.intersection({"s", "sl", "nr"}):
            blocks = " " + " · ".join(pool.details(unsorted="ul" in self.flags) for pool in pools)
        explosions = sum(pool.extra_count for pool in pools)
        note = f" · {explosions} dé(s) d'explosion" if explosions else ""
        return f"🎲 {self.label}{blocks} → **{result}**{suffix}{note}"


def extract_flags(expression: str) -> tuple[str, set[str]]:
    flags = {flag.lower() for flag in re.findall(r"\b(nr|ul|sl|s)\b", expression, flags=re.I)}
    body = re.sub(r"\b(nr|ul|sl|s)\b", "", expression, flags=re.I)
    return re.sub(r"\s+", " ", body).strip(), flags


class ExpressionParser:
    """Parse to a flat postfix program, preserving standard operator precedence."""

    def __init__(self, expression: str, *, max_dice: int, max_sides: int,
                 alias_expander: Callable[[str], str | None] | None = None, flags: set[str] | None = None):
        body, extracted = extract_flags(expression)
        self.flags = extracted | (flags or set())
        self.expression = body.lower()
        self.position = 0
        self.tokens = []
        self.max_dice, self.max_sides = max_dice, max_sides
        self.alias_expander = alias_expander

    def skip_space(self):
        while self.position < len(self.expression) and self.expression[self.position].isspace():
            self.position += 1

    def take(self, choices: str) -> str | None:
        self.skip_space()
        if self.position < len(self.expression) and self.expression[self.position] in choices:
            value = self.expression[self.position]
            self.position += 1
            return value
        return None

    def parse(self) -> ParsedExpression:
        self.sum(0)
        self.skip_space()
        if self.position != len(self.expression):
            self.unknown()
        pools = [token for token in self.tokens if isinstance(token, DiceSpec)]
        if not pools:
            raise ParseError("L'expression doit contenir au moins un dé, par exemple `1d20+5`.")
        types = {pool.target is not None for pool in pools}
        if len(types) > 1:
            raise ParseError("Ne mélange pas un comptage de succès et une somme de dés. Sépare les jets avec `;`.")
        # Catch constant zero divisors before consuming any randomness.
        known = []
        for token in self.tokens:
            if isinstance(token, DiceSpec):
                known.append(None)
            elif isinstance(token, Fraction):
                known.append(token)
            elif token == "neg":
                if known[-1] is not None:
                    known[-1] = -known[-1]
            else:
                right, left = known.pop(), known.pop()
                if token == "/" and right == 0:
                    _apply(token, Fraction(1), right)
                known.append(_apply(token, left, right) if left is not None and right is not None else None)
        return ParsedExpression(self.expression, self.tokens, self.flags, True in types)

    def sum(self, depth: int):
        self.product(depth)
        while (operator := self.take("+-")) is not None:
            self.product(depth)
            self.tokens.append(operator)

    def product(self, depth: int):
        self.atom(depth)
        while (operator := self.take("*/")) is not None:
            self.atom(depth)
            self.tokens.append(operator)

    def atom(self, depth: int):
        if depth > 32:
            raise ParseError("Maximum 32 niveaux de parenthèses ou de signes imbriqués.")
        self.skip_space()
        if (sign := self.take("+-")) is not None:
            self.atom(depth + 1)
            if sign == "-":
                self.tokens.append("neg")
            return
        if self.take("("):
            self.sum(depth + 1)
            if not self.take(")"):
                raise ParseError("Il manque une parenthèse fermante `)`.")
            return
        match = re.match(r"(\d+)df", self.expression[self.position:])
        if match:
            self.position += match.end()
            self.tokens.append(self.dice(int(match[1]), 3, kind="fate"))
            return
        match = re.match(r"ed\d+(?:e\d+)?|sr\d+|\d+(?:cod|wod)\d*|(?:attack|skill|save)\s*[+-]?\d+",
                         self.expression[self.position:])
        if match and self.alias_expander is not None:
            expanded = self.alias_expander(match[0])
            if expanded is not None and expanded != match[0]:
                nested = ExpressionParser(expanded, max_dice=self.max_dice, max_sides=self.max_sides)
                parsed = nested.parse()
                self.tokens.extend(parsed.tokens)
                self.flags.update(parsed.flags)
                self.position += match.end()
                return
        match = re.match(r"(\d*)d(\d+)", self.expression[self.position:])
        if match:
            self.position += match.end()
            self.tokens.append(self.dice(int(match[1]) if match[1] else 1, int(match[2])))
            return
        match = re.match(r"\d+(?:\.\d+)?", self.expression[self.position:])
        if match:
            self.position += match.end()
            self.tokens.append(Fraction(match[0]))
            return
        self.unknown()

    def dice(self, count: int, sides: int, *, kind: str = "standard") -> DiceSpec:
        values = {"count": count, "sides": sides, "kind": kind}
        seen = set()
        while True:
            self.skip_space()
            match = re.match(r"(ie\d*|ir\d+|kl\d+|nr|ul|sl|e\d*|[kdrtfb]\d+|s)", self.expression[self.position:])
            if not match:
                break
            text = match[0]
            self.position += match.end()
            parts = re.fullmatch(r"([a-z]+)(\d*)", text)
            key, number = parts[1], int(parts[2]) if parts[2] else None
            if key in {"s", "sl", "nr", "ul"}:
                self.flags.add(key)
                continue
            group = {"ie": "explode", "e": "explode", "ir": "reroll", "r": "reroll",
                     "k": "selection", "kl": "selection", "d": "selection",
                     "t": "target", "f": "fail", "b": "botch"}[key]
            if group in seen:
                raise ParseError(f"Modificateurs répétés ou incompatibles près de `{text}`. Choisis une seule règle de ce type par groupe.")
            seen.add(group)
            if group == "selection":
                values.update(selection=key, selection_count=number)
            elif group in {"explode", "reroll"}:
                values[group] = sides if number is None else number
                values[f"infinite_{group}"] = key.startswith("i")
            else:
                values[group] = number
        spec = DiceSpec(**values)
        spec.validate(self.max_dice, self.max_sides)
        return spec

    def unknown(self):
        fragment = self.expression[self.position:self.position + 60] or "fin de l'expression"
        raise ParseError(
            f"Élément non reconnu près de `{fragment}`. Vérifie les opérateurs et modificateurs. "
            "Pour ajouter un commentaire, utilise `! texte`. Aide : `/roll help`."
        )


def parse_expression(expression: str, *, max_dice: int, max_sides: int,
                     alias_expander: Callable[[str], str | None] | None = None,
                     flags: set[str] | None = None) -> ParsedExpression:
    return ExpressionParser(expression, max_dice=max_dice, max_sides=max_sides,
                            alias_expander=alias_expander, flags=flags).parse()
