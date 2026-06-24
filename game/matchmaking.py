import random
from db.clan_queries import get_all_clans, get_clan_members
from db.duel_queries import get_queue, add_to_queue


async def get_next_pair(war_id):
    clans = await get_all_clans(war_id)
    if len(clans) < 2:
        return None
    sorted_clans = sorted(clans, key=lambda c: c["al"])
    clan1 = sorted_clans[0]
    clan2 = sorted_clans[-1]
    if clan1["id"] == clan2["id"]:
        clan1, clan2 = sorted_clans[0], sorted_clans[1]

    p1 = await _pick(clan1["id"])
    p2 = await _pick(clan2["id"])
    if not p1 or not p2:
        return None
    return clan1, clan2, p1, p2


async def _pick(clan_id):
    queue = await get_queue(clan_id)
    if not queue:
        members = await get_clan_members(clan_id)
        for m in members:
            await add_to_queue(clan_id, m["user_id"], 1)
        queue = await get_queue(clan_id)
    return queue[0]["user_id"] if queue else None
