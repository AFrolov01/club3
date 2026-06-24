import aiosqlite
from db.database import DB_PATH


async def create_clan(name, deviz, avatar_file_id, creator_id, war_id):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                "INSERT INTO clans (name, deviz, avatar_file_id, creator_id, war_id) VALUES (?,?,?,?,?)",
                (name, deviz, avatar_file_id, creator_id, war_id)
            )
            await db.commit()
            return cur.lastrowid
        except aiosqlite.IntegrityError:
            return None


async def get_clan(clan_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clans WHERE id=?", (clan_id,)) as cur:
            r = await cur.fetchone()
            return dict(r) if r else None


async def get_all_clans(war_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clans WHERE war_id=? ORDER BY al DESC", (war_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_user_clan(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.* FROM clans c JOIN clan_members m ON c.id=m.clan_id WHERE m.user_id=?
        """, (user_id,)) as cur:
            r = await cur.fetchone()
            return dict(r) if r else None


async def get_clan_members(clan_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clan_members WHERE clan_id=?", (clan_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def join_clan(user_id, clan_id, username, full_name):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (user_id,)) as cur:
            if await cur.fetchone():
                return False
        await db.execute(
            "INSERT INTO clan_members (user_id, clan_id, username, full_name) VALUES (?,?,?,?)",
            (user_id, clan_id, username, full_name)
        )
        await db.commit()
        return True


async def leave_clan(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clan_members WHERE user_id=?", (user_id,))
        await db.commit()


async def kick_member(clan_id, target_id, requester_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT creator_id FROM clans WHERE id=?", (clan_id,)) as cur:
            r = await cur.fetchone()
        if not r or r[0] != requester_id:
            return False
        await db.execute("DELETE FROM clan_members WHERE user_id=? AND clan_id=?", (target_id, clan_id))
        await db.commit()
        return True


async def transfer_lead(clan_id, new_id, requester_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT creator_id FROM clans WHERE id=?", (clan_id,)) as cur:
            r = await cur.fetchone()
        if not r or r[0] != requester_id:
            return False
        async with db.execute("SELECT 1 FROM clan_members WHERE user_id=? AND clan_id=?", (new_id, clan_id)) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("UPDATE clans SET creator_id=? WHERE id=?", (new_id, clan_id))
        await db.commit()
        return True


async def update_al(clan_id, new_al):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET al=? WHERE id=?", (new_al, clan_id))
        await db.commit()


async def update_win(clan_id, multiplier, username):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT current_win_streak, max_win_streak, best_multiplier FROM clans WHERE id=?", (clan_id,)) as cur:
            r = await cur.fetchone()
        if not r:
            return
        streak = r[0] + 1
        max_streak = max(r[1], streak)
        best_mult = max(r[2], multiplier)
        best_user = username if multiplier > r[2] else None
        if best_user:
            await db.execute("""
                UPDATE clans SET wins=wins+1, current_win_streak=?, max_win_streak=?,
                best_multiplier=?, best_multiplier_username=? WHERE id=?
            """, (streak, max_streak, best_mult, best_user, clan_id))
        else:
            await db.execute("""
                UPDATE clans SET wins=wins+1, current_win_streak=?, max_win_streak=? WHERE id=?
            """, (streak, max_streak, clan_id))
        await db.commit()


async def update_loss(clan_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET losses=losses+1, current_win_streak=0 WHERE id=?", (clan_id,))
        await db.commit()


async def get_active_war():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM wars WHERE is_active=1 LIMIT 1") as cur:
            r = await cur.fetchone()
            return dict(r) if r else None
