import aiosqlite
import json
from db.database import DB_PATH


async def create_duel(war_id, clan1_id, clan2_id, p1_id, p2_id, chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO duels (war_id,clan1_id,clan2_id,player1_id,player2_id,chat_id) VALUES (?,?,?,?,?,?)",
            (war_id, clan1_id, clan2_id, p1_id, p2_id, chat_id)
        )
        await db.commit()
        return cur.lastrowid


async def get_duel(duel_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM duels WHERE id=?", (duel_id,)) as cur:
            r = await cur.fetchone()
            return dict(r) if r else None


async def get_active_duel_for_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM duels WHERE (player1_id=? OR player2_id=?)
            AND status IN ('announced','in_progress') ORDER BY id DESC LIMIT 1
        """, (user_id, user_id)) as cur:
            r = await cur.fetchone()
            return dict(r) if r else None


async def mark_player_done(duel_id, player_num):
    col = f"player{player_num}_done"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE duels SET {col}=1 WHERE id=?", (duel_id,))
        async with db.execute("SELECT player1_done,player2_done FROM duels WHERE id=?", (duel_id,)) as cur:
            r = await cur.fetchone()
        if r and r[0] == 1 and r[1] == 1:
            await db.execute("UPDATE duels SET status='completed' WHERE id=?", (duel_id,))
        await db.commit()


async def create_session(duel_id, user_id, clan_id, chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO duel_sessions (duel_id,user_id,clan_id,chat_id) VALUES (?,?,?,?)",
            (duel_id, user_id, clan_id, chat_id)
        )
        await db.commit()
        return cur.lastrowid


async def get_active_session(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM duel_sessions WHERE user_id=? AND status NOT IN ('done','lost')
            ORDER BY id DESC LIMIT 1
        """, (user_id,)) as cur:
            r = await cur.fetchone()
            return dict(r) if r else None


async def update_session(session_id, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [session_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE duel_sessions SET {sets} WHERE id=?", vals)
        await db.commit()


async def get_queue(clan_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM duel_queue WHERE clan_id=? AND attempts_left>0 ORDER BY rowid",
            (clan_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_to_queue(clan_id, user_id, attempts=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO duel_queue (clan_id, user_id, attempts_left) VALUES (?,?,?)
            ON CONFLICT(clan_id,user_id) DO UPDATE SET attempts_left=attempts_left+?
        """, (clan_id, user_id, attempts, attempts))
        await db.commit()


async def decrement_attempts(clan_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE duel_queue SET attempts_left=attempts_left-1 WHERE clan_id=? AND user_id=?",
            (clan_id, user_id)
        )
        await db.execute(
            "DELETE FROM duel_queue WHERE clan_id=? AND user_id=? AND attempts_left<=0",
            (clan_id, user_id)
        )
        await db.commit()


# Simple FSM storage in DB
async def get_state(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT state, data FROM fsm_data WHERE user_id=?", (user_id,)) as cur:
            r = await cur.fetchone()
            if r:
                import json
                return r[0], json.loads(r[1])
            return None, {}


async def set_state(user_id, state, data=None):
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO fsm_data (user_id, state, data) VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET state=?, data=?
        """, (user_id, state, json.dumps(data or {}), state, json.dumps(data or {})))
        await db.commit()


async def clear_state(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM fsm_data WHERE user_id=?", (user_id,))
        await db.commit()
