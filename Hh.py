ranking.py:
import discord
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

TOP_FILE = os.path.join(MODULE_DIR, "top.json")
STATE_FILE = os.path.join(MODULE_DIR, "top_state.json")
REWARD_FILE = os.path.join(MODULE_DIR, "reward_state.json")

INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
CHANNEL_FILE = os.path.join(BASE_DIR, "Data", "auction_channels.json")
COUPLE_FILE = os.path.join(BASE_DIR, "Data", "couple.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")

VN_TZ = timezone(timedelta(hours=7))


# ===== SAFE LOAD =====
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ===== INIT =====
def ensure_file(path, default):
    data = load_json(path)
    if not data:
        save_json(path, default)
        return default
    return data


def load_top():
    return ensure_file(TOP_FILE, {"gold": {}, "couple": {}, "love": {}})


def save_top(data):
    save_json(TOP_FILE, data)


def load_state():
    return ensure_file(STATE_FILE, {"gold": {}, "couple": {}, "love": {}})


def save_state(data):
    save_json(STATE_FILE, data)


def load_reward():
    return ensure_file(REWARD_FILE, {"last_week": None})


def save_reward(data):
    save_json(REWARD_FILE, data)


# ===== HELPERS =====
def get_default_love(inv, uid):
    user = inv.get(uid, {})
    default_id = user.get("default_waifu")

    if not default_id:
        return None, 0

    waifus = user.get("waifus", {})
    love = waifus.get(default_id, 0)

    if isinstance(love, dict):
        love = love.get("amount", 0)

    return default_id, int(love)


def seconds_until_next_half_hour():
    now = datetime.now(VN_TZ)
    if now.minute < 30:
        target = now.replace(minute=30, second=0, microsecond=0)
    else:
        target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    return max(1, int((target - now).total_seconds()))


# ===== TOP =====
def get_top(category):
    top = load_top().get(category, {})
    ranked = sorted(top.items(), key=lambda x: x[1], reverse=True)
    return ranked[:3]


def get_top_couple():
    top = load_top().get("couple", {})
    couples = load_json(COUPLE_FILE)

    visited = set()
    result = []

    for uid, points in top.items():
        info = couples.get(uid)
        if not info:
            continue

        partner = info.get("partner")
        if not partner:
            continue

        pair_key = tuple(sorted([uid, partner]))
        if pair_key in visited:
            continue

        visited.add(pair_key)
        result.append((uid, partner, points))

    return sorted(result, key=lambda x: x[2], reverse=True)[:3]


# ===== UPDATE TOP =====
def update_top():
    try:
        top = load_top()
        state = load_state()

        users = data_user.load_data()
        inv = load_json(INV_FILE)
        couples = load_json(COUPLE_FILE)

        # GOLD
        for uid, data in users.items():
            current = int(data.get("gold", 0))
            prev = state["gold"].get(uid)

            if prev is None:
                state["gold"][uid] = current
                top["gold"].setdefault(uid, 0)
            elif current > prev:
                top["gold"][uid] += (current - prev)
                state["gold"][uid] = current
            else:
                state["gold"][uid] = current

        # LOVE
        for uid in inv:
            _, current = get_default_love(inv, uid)
            prev = state["love"].get(uid)

            if prev is None:
                state["love"][uid] = current
                top["love"].setdefault(uid, 0)
            elif current > prev:
                top["love"][uid] += (current - prev)
                state["love"][uid] = current
            else:
                state["love"][uid] = current

        # COUPLE
        for uid, info in couples.items():
            current = int(info.get("points", 0))
            prev = state["couple"].get(uid)

            if prev is None:
                state["couple"][uid] = current
                top["couple"].setdefault(uid, 0)
            elif current > prev:
                top["couple"][uid] += (current - prev)
                state["couple"][uid] = current
            else:
                state["couple"][uid] = current

        save_top(top)
        save_state(state)

    except Exception as e:
        print(f"[UPDATE ERROR] {e}")


# ===== EMBED =====
def build_embed(title, desc, color):
    embed = discord.Embed(title=title, description=desc, color=color)
    return embed


# ===== LOOP =====
async def ranking_loop(bot):
    await bot.wait_until_ready()

    async def update_task():
        while True:
            update_top()
            await asyncio.sleep(5)  # giảm spam

    async def embed_task():
        while True:
            await asyncio.sleep(seconds_until_next_half_hour())

            try:
                channels = load_json(CHANNEL_FILE)
                top_gold = get_top("gold")

                desc = "\n".join(
                    [f"🥇 <@{uid}>: {val}" for uid, val in top_gold]
                ) or "Không có dữ liệu"

                embed = build_embed("💰 Top Gold", desc, discord.Color.gold())

                for gid, data in channels.items():
                    # ✅ FIX dict/int
                    ch_id = data.get("leaderboard_channel_id") if isinstance(data, dict) else data

                    if not ch_id:
                        continue

                    channel = bot.get_channel(int(ch_id))
                    if not channel:
                        continue

                    await channel.send(embed=embed)

            except Exception as e:
                print(f"[EMBED ERROR] {e}")

    bot.loop.create_task(update_task())
    bot.loop.create_task(embed_task())


# ===== SETUP =====
async def setup(bot):
    bot.loop.create_task(ranking_loop(bot))

print("✅ Loaded ranking FIXED!")
reward_state.json:
{
    "last_week": "2026-13"
}

top_state.json:
{
    "gold": {
        "1257617565409083427": 30160,
        "1220291333982257255": 20188,
        "1159805084599857173": 685,
        "851471646870732800": 14272,
        "810876072568160318": 3012,
        "1340391807900582039": 1,
        "1332663946099953710": 0,
        "1166722225966157874": 1472,
        "1041387215122600066": 347,
        "1489169391495938058": 10910,
        "1488145103943110746": 4611,
        "1059280512998453249": 523
    },
    "couple": {
        "1257617565409083427": 15,
        "851471646870732800": 15,
        "1220291333982257255": 0,
        "1059280512998453249": 0
    },
    "love": {
        "1257617565409083427": 2472,
        "1220291333982257255": 0,
        "851471646870732800": 1689,
        "1166722225966157874": 291,
        "1041387215122600066": 88,
        "1059280512998453249": 375,
        "810876072568160318": 0,
        "1340391807900582039": 0,
        "1332663946099953710": 0,
        "1489169391495938058": 0
    }
}
top.json:
{
    "gold": {},
    "couple": {},
    "love": {}
}
