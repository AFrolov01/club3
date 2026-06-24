import asyncio
import logging
import json
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, WAR_DURATION_DAYS, STARTING_AL, DUEL_INTERVAL_HOURS, LOSE_MULTIPLIER
from db.database import init_db, DB_PATH
from db.clan_queries import (
    create_clan, get_clan, get_all_clans, get_user_clan,
    get_clan_members, join_clan, leave_clan, kick_member,
    transfer_lead, update_al, update_win, update_loss, get_active_war
)
from db.duel_queries import (
    create_duel, get_duel, get_active_duel_for_user,
    mark_player_done, create_session, get_active_session,
    update_session, get_queue, add_to_queue, decrement_attempts,
    get_state, set_state, clear_state
)
from game.mines import (
    generate_field, get_multiplier, get_next_str, get_full_str,
    calc_al, field_keyboard, mines_keyboard
)
from game.matchmaking import get_next_pair
import aiosqlite

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

GROUP_CHAT_ID = None


# ===== UTILS =====

async def save_group(chat_id):
    global GROUP_CHAT_ID
    GROUP_CHAT_ID = chat_id


# ===== START =====

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        await save_group(message.chat.id)
    await message.answer(
        "⚔️ <b>Бот Войны Кланов</b>\n\n"
        "/createclan — создать клан\n"
        "/join — вступить в клан\n"
        "/clan — профиль клана\n"
        "/top — таблица кланов\n"
        "/leaveclan — выйти из клана\n"
        "/kick — кикнуть участника (ответом, лидер)\n"
        "/transferlead — передать лидерство (ответом)\n"
        "/minduel — начать дуэль когда вызван"
    )


@dp.message_handler(content_types=types.ContentTypes.ANY)
async def track_group(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        await save_group(message.chat.id)


# ===== FSM STATES =====
STATE_CLAN_NAME = "clan_name"
STATE_CLAN_AVATAR = "clan_avatar"
STATE_CLAN_DEVIZ = "clan_deviz"
STATE_JOIN = "join"


# ===== СОЗДАНИЕ КЛАНА =====

@dp.message_handler(commands=["createclan"])
async def cmd_createclan(message: types.Message):
    existing = await get_user_clan(message.from_user.id)
    if existing:
        await message.answer(f"⚠️ Ты уже в клане <b>{existing['name']}</b>. Выйди через /leaveclan")
        return
    await set_state(message.from_user.id, STATE_CLAN_NAME)
    await message.answer("⚔️ <b>Создание клана</b>\n\nВведи название клана:")


@dp.message_handler(commands=["join"])
async def cmd_join(message: types.Message):
    existing = await get_user_clan(message.from_user.id)
    if existing:
        await message.answer(f"⚠️ Ты уже в клане <b>{existing['name']}</b>.")
        return
    war = await get_active_war()
    war_id = war["id"] if war else 1
    clans = await get_all_clans(war_id)
    if not clans:
        await message.answer("😔 Нет кланов. Создай первый: /createclan")
        return
    await set_state(message.from_user.id, STATE_JOIN, {"index": 0, "clans": [c["id"] for c in clans]})
    await _show_clan(message, clans[0], 0, len(clans))


async def _show_clan(target, clan, idx, total, edit=False):
    members = await get_clan_members(clan["id"])
    text = (
        f"⚔️ <b>{clan['name']}</b>\n"
        + (f"📜 {clan['deviz']}\n" if clan["deviz"] else "")
        + f"\n👥 Участников: {len(members)}\n"
        f"💠 Al: {clan['al']}\n\n"
        f"{idx+1} / {total}"
    )
    kb = InlineKeyboardMarkup(row_width=3).add(
        InlineKeyboardButton("⬅️", callback_data=f"join_nav_{idx-1}"),
        InlineKeyboardButton("✅ Выбрать", callback_data=f"join_sel_{clan['id']}"),
        InlineKeyboardButton("➡️", callback_data=f"join_nav_{idx+1}"),
    )
    if clan.get("avatar_file_id"):
        await target.answer_photo(clan["avatar_file_id"], caption=text, reply_markup=kb)
    else:
        if edit:
            try:
                await target.edit_text(text, reply_markup=kb)
            except:
                await target.answer(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("join_nav_"))
async def cb_join_nav(call: types.CallbackQuery):
    state, data = await get_state(call.from_user.id)
    if state != STATE_JOIN:
        await call.answer()
        return
    idx = int(call.data.split("_")[2])
    clan_ids = data.get("clans", [])
    idx = max(0, min(idx, len(clan_ids)-1))
    await set_state(call.from_user.id, STATE_JOIN, {"index": idx, "clans": clan_ids})
    clan = await get_clan(clan_ids[idx])
    if clan:
        await _show_clan(call.message, clan, idx, len(clan_ids), edit=True)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("join_sel_"))
async def cb_join_sel(call: types.CallbackQuery):
    clan_id = int(call.data.split("_")[2])
    await clear_state(call.from_user.id)
    existing = await get_user_clan(call.from_user.id)
    if existing:
        await call.answer("Ты уже в клане!", show_alert=True)
        return
    clan = await get_clan(clan_id)
    if not clan:
        await call.answer("Клан не найден.", show_alert=True)
        return
    ok = await join_clan(call.from_user.id, clan_id, call.from_user.username or "", call.from_user.full_name)
    if ok:
        await call.message.edit_text(f"✅ Ты вступил в клан <b>{clan['name']}</b>!\n/clan — посмотреть профиль")
    else:
        await call.answer("Не удалось вступить.", show_alert=True)


# ===== ТЕКСТОВЫЙ FSM =====

@dp.message_handler(lambda m: True, content_types=["text", "photo"])
async def fsm_handler(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        await save_group(message.chat.id)
        return
    if message.text and message.text.startswith("/"):
        return

    state, data = await get_state(message.from_user.id)

    if state == STATE_CLAN_NAME:
        name = message.text.strip() if message.text else ""
        if len(name) < 2 or len(name) > 32:
            await message.answer("❌ Название от 2 до 32 символов:")
            return
        await set_state(message.from_user.id, STATE_CLAN_AVATAR, {"name": name})
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("Пропустить →", callback_data="skip_avatar"))
        await message.answer("🖼 Отправь аватарку клана или нажми <b>Пропустить</b>:", reply_markup=kb)

    elif state == STATE_CLAN_AVATAR:
        if message.photo:
            data["avatar"] = message.photo[-1].file_id
        await set_state(message.from_user.id, STATE_CLAN_DEVIZ, data)
        await message.answer("✍️ Введи девиз клана (или <b>-</b> чтобы пропустить):")

    elif state == STATE_CLAN_DEVIZ:
        deviz = message.text.strip() if message.text else ""
        if deviz == "-":
            deviz = ""
        war = await get_active_war()
        war_id = war["id"] if war else 1
        clan_id = await create_clan(data.get("name",""), deviz, data.get("avatar"), message.from_user.id, war_id)
        await clear_state(message.from_user.id)
        if not clan_id:
            await message.answer("❌ Клан с таким названием уже существует.")
            return
        await join_clan(message.from_user.id, clan_id, message.from_user.username or "", message.from_user.full_name)
        await message.answer(f"✅ Клан <b>{data.get('name')}</b> создан!\nДругие могут вступить через /join")


@dp.callback_query_handler(lambda c: c.data == "skip_avatar")
async def cb_skip_avatar(call: types.CallbackQuery):
    state, data = await get_state(call.from_user.id)
    if state != STATE_CLAN_AVATAR:
        await call.answer()
        return
    await set_state(call.from_user.id, STATE_CLAN_DEVIZ, data)
    await call.message.edit_text("✍️ Введи девиз клана (или <b>-</b> чтобы пропустить):")
    await call.answer()


# ===== ПРОФИЛЬ КЛАНА =====

@dp.message_handler(commands=["clan"])
async def cmd_clan(message: types.Message):
    clan = await get_user_clan(message.from_user.id)
    if not clan:
        await message.answer("😔 Ты не в клане. /join или /createclan")
        return
    members = await get_clan_members(clan["id"])
    lines = []
    for m in members:
        name = f"@{m['username']}" if m["username"] else m["full_name"]
        crown = " 👑" if m["user_id"] == clan["creator_id"] else ""
        lines.append(f"  • {name}{crown}")

    best = ""
    if clan["best_multiplier"] > 1.0 and clan["best_multiplier_username"]:
        best = f"🎰 Лучший множитель: x{clan['best_multiplier']:.2f} (@{clan['best_multiplier_username']})\n"

    text = (
        f"⚔️ <b>{clan['name']}</b>\n"
        + (f"📜 {clan['deviz']}\n" if clan["deviz"] else "")
        + f"\n💠 Al: <b>{clan['al']}</b>\n"
        f"🏆 Побед: {clan['wins']}  💀 Поражений: {clan['losses']}\n"
        f"🔥 Серия: {clan['current_win_streak']}  📈 Макс: {clan['max_win_streak']}\n"
        f"{best}\n"
        f"👥 <b>Участники ({len(members)}):</b>\n" + "\n".join(lines)
    )
    if clan.get("avatar_file_id"):
        await message.answer_photo(clan["avatar_file_id"], caption=text)
    else:
        await message.answer(text)


@dp.message_handler(commands=["top"])
async def cmd_top(message: types.Message):
    war = await get_active_war()
    if not war:
        await message.answer("Война не началась.")
        return
    clans = await get_all_clans(war["id"])
    if not clans:
        await message.answer("Нет кланов.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["💠 <b>Война кланов — таблица Al:</b>\n"]
    for i, c in enumerate(clans):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} <b>{c['name']}</b> — {c['al']} Al")
    await message.answer("\n".join(lines))


@dp.message_handler(commands=["leaveclan"])
async def cmd_leave(message: types.Message):
    clan = await get_user_clan(message.from_user.id)
    if not clan:
        await message.answer("Ты не в клане.")
        return
    if clan["creator_id"] == message.from_user.id:
        members = await get_clan_members(clan["id"])
        if len(members) > 1:
            await message.answer("⚠️ Передай лидерство через /transferlead (ответом на сообщение участника)")
            return
    await leave_clan(message.from_user.id)
    await message.answer(f"Ты вышел из клана <b>{clan['name']}</b>.")


@dp.message_handler(commands=["kick"])
async def cmd_kick(message: types.Message):
    clan = await get_user_clan(message.from_user.id)
    if not clan or clan["creator_id"] != message.from_user.id:
        await message.answer("⛔ Только лидер клана может кикать.")
        return
    if not message.reply_to_message:
        await message.answer("Ответь на сообщение участника.")
        return
    ok = await kick_member(clan["id"], message.reply_to_message.from_user.id, message.from_user.id)
    if ok:
        await message.answer(f"✅ {message.reply_to_message.from_user.full_name} исключён.")
    else:
        await message.answer("❌ Не удалось.")


@dp.message_handler(commands=["transferlead"])
async def cmd_transfer(message: types.Message):
    clan = await get_user_clan(message.from_user.id)
    if not clan or clan["creator_id"] != message.from_user.id:
        await message.answer("⛔ Только лидер может передавать лидерство.")
        return
    if not message.reply_to_message:
        await message.answer("Ответь на сообщение участника.")
        return
    ok = await transfer_lead(clan["id"], message.reply_to_message.from_user.id, message.from_user.id)
    if ok:
        await message.answer(f"👑 Лидерство передано {message.reply_to_message.from_user.full_name}!")
    else:
        await message.answer("❌ Этот участник не в твоём клане.")


# ===== ДУЭЛЬ =====

@dp.message_handler(commands=["minduel"])
async def cmd_minduel(message: types.Message):
    user_id = message.from_user.id
    clan = await get_user_clan(user_id)
    if not clan:
        await message.answer("⚠️ Ты не в клане.")
        return
    duel = await get_active_duel_for_user(user_id)
    if not duel:
        await message.answer("⏳ Нет активной дуэли для тебя.")
        return
    existing = await get_active_session(user_id)
    if existing:
        await message.answer("▶️ У тебя уже есть активная игра!")
        return

    lose_al = max(int(clan["al"] * LOSE_MULTIPLIER), 10)
    rules = (
        f"📋 <b>Правила дуэли:</b>\n"
        f"• Открывай клетки — находи 💎, избегай 💣\n"
        f"• При мине: Al клана ×{LOSE_MULTIPLIER} ({clan['al']} → {lose_al} Al)\n"
        f"• Можно забрать очки в любой момент кнопкой ✅\n"
        f"• Больше мин = выше множители"
    )

    prog_lines = []
    for m in range(1, 7):
        prog_lines.append(f"{'💣'*m} <b>{m} мин:</b>\n{get_full_str(m)}")
    progressions = "\n".join(prog_lines)

    text = (
        f"⚔️ <b>Дуэль #{duel['id']}</b>\n"
        f"💠 Твои Al: <b>{clan['al']}</b>\n\n"
        f"<blockquote>{rules}</blockquote>\n\n"
        f"<blockquote>{progressions}</blockquote>\n\n"
        f"Выбери количество мин:"
    )
    await message.answer(text, reply_markup=mines_keyboard())


@dp.callback_query_handler(lambda c: c.data.startswith("mines_"))
async def cb_mines(call: types.CallbackQuery):
    mines = int(call.data.split("_")[1])
    user_id = call.from_user.id
    clan = await get_user_clan(user_id)
    if not clan:
        await call.answer("Ты не в клане!", show_alert=True)
        return
    duel = await get_active_duel_for_user(user_id)
    if not duel:
        await call.answer("Дуэль завершена.", show_alert=True)
        return
    existing = await get_active_session(user_id)
    if existing:
        await call.answer("Игра уже идёт!", show_alert=True)
        return

    session_id = await create_session(duel["id"], user_id, clan["id"], call.message.chat.id)
    field = generate_field(mines)
    await update_session(
        session_id,
        mines=mines,
        field=json.dumps(field),
        opened=json.dumps([]),
        current_multiplier=1.0,
        step=0,
        status="playing"
    )

    text = (
        f"⚔️ <b>Дуэль #{duel['id']}</b>\n"
        f"{'💣'*mines} Мин: <b>{mines}</b>\n"
        f"💠 Ставка: <b>{clan['al']} Al</b>\n"
        f"📊 Выигрыш: x1.00 / {clan['al']} Al\n\n"
        f"🧮 <b>Прогрессия:</b>\n{get_full_str(mines)}\n\n"
        f"Открывай клетки!"
    )
    await call.message.edit_text(text, reply_markup=field_keyboard(field, []))
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("cell_") or c.data in ("cashout", "noop"))
async def cb_cell(call: types.CallbackQuery):
    if call.data == "noop":
        await call.answer()
        return
    if call.data == "cashout":
        await _cashout(call)
        return

    pos = int(call.data.split("_")[1])
    user_id = call.from_user.id
    session = await get_active_session(user_id)
    if not session or session["status"] != "playing":
        await call.answer("Игра не активна.", show_alert=True)
        return

    clan = await get_user_clan(user_id)
    field = json.loads(session["field"])
    opened = json.loads(session["opened"])
    mines = session["mines"]
    duel = await get_duel(session["duel_id"])

    if pos in opened:
        await call.answer("Уже открыта!")
        return

    opened.append(pos)
    is_mine = field[pos] == 1

    if is_mine:
        new_al = calc_al(clan["al"], session["current_multiplier"], won=False)
        await update_al(clan["id"], new_al)
        await update_loss(clan["id"])
        await update_session(session["id"], status="lost", opened=json.dumps(opened))
        await _finish(duel, user_id, clan["id"])

        text = (
            f"💥 <b>БУМ! Мина!</b>\n\n"
            f"{'💣'*mines} Мин было: {mines}\n"
            f"💠 Al клана: {clan['al']} → <b>{new_al}</b>\n"
            f"📉 (×{LOSE_MULTIPLIER})"
        )
        await call.message.edit_text(text, reply_markup=field_keyboard(field, opened, game_over=True))

        if duel and duel.get("chat_id"):
            uname = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
            await bot.send_message(
                duel["chat_id"],
                f"💥 <b>{uname}</b> ({clan['name']}) подорвался!\nAl: {clan['al']} → {new_al}"
            )
    else:
        step = session["step"] + 1
        mult = get_multiplier(mines, step)
        new_al_preview = int(clan["al"] * mult)
        await update_session(session["id"], opened=json.dumps(opened), step=step, current_multiplier=mult)

        text = (
            f"⚔️ <b>Дуэль #{duel['id']}</b>\n"
            f"{'💣'*mines} Мин: {mines}\n"
            f"💠 Ставка: {clan['al']} Al\n"
            f"📊 Выигрыш: <b>x{mult:.2f} / {new_al_preview} Al</b>\n\n"
            f"🧮 <b>Следующий множитель:</b>\n{get_next_str(mines, step)}"
        )
        await call.message.edit_text(text, reply_markup=field_keyboard(field, opened))

    await call.answer()


async def _cashout(call: types.CallbackQuery):
    user_id = call.from_user.id
    session = await get_active_session(user_id)
    if not session or session["status"] != "playing":
        await call.answer("Игра не активна.", show_alert=True)
        return

    clan = await get_user_clan(user_id)
    mult = session["current_multiplier"]
    mines = session["mines"]
    new_al = calc_al(clan["al"], mult, won=True)
    uname = call.from_user.username or call.from_user.full_name

    await update_al(clan["id"], new_al)
    await update_win(clan["id"], mult, uname)
    await update_session(session["id"], status="done")

    duel = await get_duel(session["duel_id"])
    await _finish(duel, user_id, clan["id"])

    field = json.loads(session["field"])
    opened = json.loads(session["opened"])

    text = (
        f"✅ <b>Выигрыш забран!</b>\n\n"
        f"{'💣'*mines} Мин: {mines}\n"
        f"📊 Множитель: x{mult:.2f}\n"
        f"💠 Al клана: {clan['al']} → <b>{new_al}</b>"
    )
    await call.message.edit_text(text, reply_markup=field_keyboard(field, opened, game_over=True))

    if duel and duel.get("chat_id"):
        mention = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
        await bot.send_message(
            duel["chat_id"],
            f"✅ <b>{mention}</b> ({clan['name']}) забрал выигрыш!\nx{mult:.2f} | Al: {clan['al']} → {new_al}"
        )
    await call.answer()


async def _finish(duel, user_id, clan_id):
    if not duel:
        return
    player_num = 1 if duel["player1_id"] == user_id else 2
    await decrement_attempts(clan_id, user_id)
    await mark_player_done(duel["id"], player_num)


# ===== ПЛАНИРОВЩИК =====

async def scheduler():
    global GROUP_CHAT_ID
    while True:
        await asyncio.sleep(60 * 30)
        if not GROUP_CHAT_ID:
            continue
        try:
            war = await get_active_war()
            if not war:
                continue

            started = datetime.fromisoformat(war["started_at"])
            if datetime.now() - started > timedelta(days=WAR_DURATION_DAYS):
                await end_war(war)
                continue

            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT scheduled_at FROM duels WHERE war_id=? ORDER BY id DESC LIMIT 1",
                    (war["id"],)
                ) as cur:
                    row = await cur.fetchone()

            if row:
                last = datetime.fromisoformat(row[0])
                if datetime.now() - last < timedelta(hours=DUEL_INTERVAL_HOURS):
                    continue

            result = await get_next_pair(war["id"])
            if not result:
                continue

            clan1, clan2, p1_id, p2_id = result
            duel_id = await create_duel(war["id"], clan1["id"], clan2["id"], p1_id, p2_id, GROUP_CHAT_ID)

            p1_mention = f'<a href="tg://user?id={p1_id}">воин {clan1["name"]}</a>'
            p2_mention = f'<a href="tg://user?id={p2_id}">воин {clan2["name"]}</a>'

            await bot.send_message(
                GROUP_CHAT_ID,
                f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b> ⚔️\n\n"
                f"🛡 {p1_mention}\n🗡 против\n🛡 {p2_mention}\n\n"
                f"💠 <b>{clan1['name']}</b>: {clan1['al']} Al\n"
                f"💠 <b>{clan2['name']}</b>: {clan2['al']} Al\n\n"
                f"Напишите боту в личку:\n/minduel — начать игру"
            )
        except Exception as e:
            logging.error(f"Ошибка планировщика: {e}")


async def end_war(war):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE wars SET is_active=0, ended_at=datetime('now') WHERE id=?", (war["id"],))
        await db.commit()

    clans = await get_all_clans(war["id"])
    if not clans or not GROUP_CHAT_ID:
        return

    sorted_clans = sorted(clans, key=lambda c: c["al"], reverse=True)
    winner = sorted_clans[0]
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏁 <b>ВОЙНА ЗАВЕРШЕНА!</b>\n\n👑 Победитель: <b>{winner['name']}</b>!\n\n📊 Итог:"]
    for i, c in enumerate(sorted_clans):
        lines.append(f"{medals[i] if i < 3 else f'{i+1}.'} {c['name']} — {c['al']} Al")
    await bot.send_message(GROUP_CHAT_ID, "\n".join(lines))

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO wars (is_active) VALUES (1)")
        new_war_id = cur.lastrowid
        await db.execute(f"UPDATE clans SET al={STARTING_AL}, war_id=?, current_win_streak=0", (new_war_id,))
        await db.commit()

    await bot.send_message(GROUP_CHAT_ID, f"🔄 <b>Новая война кланов!</b>\nВсе кланы стартуют с {STARTING_AL} Al. Удачи! ⚔️")


async def on_startup(dp):
    await init_db()
    asyncio.create_task(scheduler())
    logging.info("Бот запущен!")


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
