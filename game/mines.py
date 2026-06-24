import random
from config import MULTIPLIERS, FIELD_SIZE, LOSE_MULTIPLIER, MIN_AL


def generate_field(mines):
    total = FIELD_SIZE * FIELD_SIZE
    field = [0] * total
    for pos in random.sample(range(total), mines):
        field[pos] = 1
    return field


def get_multiplier(mines, step):
    mults = MULTIPLIERS.get(mines, MULTIPLIERS[1])
    if step == 0:
        return 1.0
    idx = step - 1
    return mults[min(idx, len(mults)-1)]


def get_next_str(mines, step, count=5):
    mults = MULTIPLIERS.get(mines, MULTIPLIERS[1])
    shown = mults[step:step+count]
    if not shown:
        return "максимум достигнут"
    parts = [f"x{m:.2f}" for m in shown]
    if step + count < len(mults):
        parts.append("...")
    return " ➡️ ".join(parts)


def get_full_str(mines, count=6):
    mults = MULTIPLIERS.get(mines, MULTIPLIERS[1])
    parts = [f"x{m:.2f}" for m in mults[:count]]
    if len(mults) > count:
        parts.append("...")
    return " ➡️ ".join(parts)


def calc_al(current_al, multiplier, won):
    if won:
        return max(int(current_al * multiplier), MIN_AL)
    return max(int(current_al * LOSE_MULTIPLIER), MIN_AL)


def field_keyboard(field, opened, game_over=False):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for row in range(FIELD_SIZE):
        row_btns = []
        for col in range(FIELD_SIZE):
            pos = row * FIELD_SIZE + col
            if pos in opened:
                text = "💣" if field[pos] == 1 else "💎"
                row_btns.append(InlineKeyboardButton(text, callback_data=f"noop"))
            elif game_over and field[pos] == 1:
                row_btns.append(InlineKeyboardButton("💣", callback_data="noop"))
            else:
                row_btns.append(InlineKeyboardButton("❓", callback_data=f"cell_{pos}"))
        buttons.append(row_btns)
    if not game_over:
        buttons.append([InlineKeyboardButton("✅ Забрать очки", callback_data="cashout")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def mines_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    row = [InlineKeyboardButton(f"{i}️⃣", callback_data=f"mines_{i}") for i in range(1, 7)]
    return InlineKeyboardMarkup(inline_keyboard=[row])
