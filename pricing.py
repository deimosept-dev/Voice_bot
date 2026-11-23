"""Таблица цен (в рублях). Меняйте числа здесь, остальной код трогать не нужно."""

SKIN_TIERS = {
    "supreme": ("Supreme", 4000, 410),
    "grand": ("Grand", 3000, 307),
    "exquisite": ("Exquisite", 2000, 205),
    "deluxe": ("Deluxe", 400, 41),
    "exceptional": ("Exceptional", 200, 20),
    "common": ("Common", 100, 10),
    "painted": ("Painted", 40, 4),
}

RANKS = {
    "below_epic": ("Ниже Epic", 0),
    "epic": ("Epic", 410),
    "legend": ("Legend", 1230),
    "mythic": ("Mythic", 2050),
    "honor": ("Mythical Honor", 3075),
    "glory": ("Mythical Glory", 5122),
    "immortal": ("Mythical Immortal", 10244),
}

BASE_ACCOUNT = 52
HERO_PRICE = 2.56
EMBLEM_PRICE = 128
DIAMOND_PRICE = 0.1
EXTRA_POINTS_PER_10K = 1025

WINRATE_MAX_BONUS = 10250
WINRATE_STEPS = [(60, 0.0), (65, 0.15), (70, 0.5), (75, 1.0)]

ACCESS = {
    "safe": ("Доступ безопасный", 1.0),
    "one_risk": ("Одна недоступная привязка", 0.75),
    "many_risks": ("Несколько рисков по доступу", 0.5),
}


def _num(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _winrate_share(wr):
    if wr <= WINRATE_STEPS[0][0]:
        return 0.0
    if wr >= WINRATE_STEPS[-1][0]:
        return 1.0
    for (x1, y1), (x2, y2) in zip(WINRATE_STEPS, WINRATE_STEPS[1:]):
        if x1 <= wr <= x2:
            return y1 + (y2 - y1) * (wr - x1) / (x2 - x1)
    return 0.0


def calculate(data, access="safe"):
    lines = []

    def add(title, detail, amount):
        if amount > 0:
            lines.append({"title": title, "detail": detail, "amount": round(amount)})

    add("Базовая цена", "", BASE_ACCOUNT)

    skins = data.get("skins") or {}
    covered_points = 0
    for key, (name, points, price) in SKIN_TIERS.items():
        count = int(_num(skins.get(key)))
        covered_points += count * points
        add(f"Скины {name}", f"{count} × {price} ₽", count * price)

    total_points = _num(data.get("collection_points"))
    extra = max(0.0, total_points - covered_points)
    add("Очки коллекции сверх скинов", f"{int(extra)} очков", extra / 10000 * EXTRA_POINTS_PER_10K)

    rank_key = data.get("highest_rank")
    rank_name, rank_price = RANKS.get(rank_key, RANKS["below_epic"])
    add(f"Ранг: {rank_name}", "", rank_price)

    wr = _num(data.get("win_rate"))
    matches = _num(data.get("ranked_matches"))
    if wr >= 60 and matches > 0:
        factor = min(matches / 2000, 1.0)
        add("Винрейт", f"{wr:g}%, {int(matches)} матчей",
            WINRATE_MAX_BONUS * _winrate_share(wr) * factor)

    heroes = int(_num(data.get("heroes_owned")))
    add("Герои", f"{heroes} × {HERO_PRICE} ₽", heroes * HERO_PRICE)

    emblems = int(_num(data.get("maxed_emblems")))
    add("Эмблемы на максимуме", f"{emblems} × {EMBLEM_PRICE} ₽", emblems * EMBLEM_PRICE)

    diamonds = int(_num(data.get("diamonds")))
    add("Алмазы", f"{diamonds}", diamonds * DIAMOND_PRICE)

    subtotal = sum(l["amount"] for l in lines)
    access_name, mult = ACCESS.get(access, ACCESS["safe"])
    total = round(subtotal * mult)
    return {
        "subtotal": subtotal,
        "access": access_name,
        "access_multiplier": mult,
        "total": total,
        "lines": lines,
    }
