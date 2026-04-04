import asyncio
import copy
import importlib
import json
import os
import random
from typing import Dict, List, Optional, Set, Tuple

import discord

from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
TEAM_FILE = os.path.join(BASE_DIR, "Data", "team.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")

MAX_ROUNDS = 30
ACTION_DELAY = 2.0
MAX_LOG_LINES = 12
COOLDOWN_HOURS = 8
LOVE_DROP_RATE = 0.10
LOVE_RESET_ON_TRANSFER = True

RANK_ORDER = ["limited", "toi_thuong", "truyen_thuyet", "huyen_thoai", "anh_hung", "thuong"]

INV_LOCK = asyncio.Lock()
BATTLE_STATE_LOCK = asyncio.Lock()
ACTIVE_BATTLE_USERS: Set[str] = set()

COOLDOWNS: Dict[Tuple[str, str], float] = {}


# ===== LOAD / SAVE =====
def load_json(path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ===== SMALL HELPERS =====
def get_user_obj(ctx):
    return getattr(ctx, "user", None) or getattr(ctx, "author", None)


async def send_like(ctx, content=None, embed=None, view=None, ephemeral=False):
    if hasattr(ctx, "response"):
        if not ctx.response.is_done():
            await ctx.response.send_message(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
            )
            try:
                return await ctx.original_response()
            except Exception:
                return None
        msg = await ctx.followup.send(
            content=content,
            embed=embed,
            view=view,
            ephemeral=ephemeral,
        )
        return msg

    if hasattr(ctx, "channel"):
        return await ctx.channel.send(content=content, embed=embed, view=view)

    return None


async def edit_like(message, *, content=None, embed=None, view=None):
    return await message.edit(content=content, embed=embed, view=view)


def trim_lines(lines: List[str], max_lines: int) -> List[str]:
    if len(lines) <= max_lines:
        return lines
    return lines[-max_lines:]


def hp_bar(current, max_hp, length=10):
    max_hp = max(1, int(max_hp))
    current = max(0, min(int(current), max_hp))
    ratio = current / max_hp
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)


def get_rank_info(waifu_data: dict, waifu_id: str) -> Tuple[str, dict]:
    meta = waifu_data.get(waifu_id, {}) or {}
    rank = meta.get("rank", "thuong")
    if rank not in RANK_ORDER:
        rank = "thuong"
    return rank, meta


def get_battle_crit_chance(luck: float) -> float:
    try:
        luck = float(luck)
    except Exception:
        luck = 1.0
    base = 0.05
    bonus = max(0.0, luck - 1.0) * 0.01
    return min(0.30, base + bonus)


def get_dodge_chance(attacker_speed: int, defender_speed: int) -> float:
    attacker_speed = max(1, int(attacker_speed))
    defender_speed = max(1, int(defender_speed))
    base = 0.05
    bonus = min(0.20, defender_speed / max(1, attacker_speed * 12))
    return min(0.25, base + bonus)


def get_crit_damage(base_damage: int, is_combo: bool) -> int:
    base_damage = max(1, int(base_damage))
    if is_combo:
        return max(1, int(base_damage * random.uniform(1.40, 1.50)))
    return max(1, int(base_damage * random.uniform(1.30, 1.35)))


def get_crit_heal(current_hp: int, is_combo: bool) -> int:
    current_hp = max(1, int(current_hp))
    if is_combo:
        return max(1, int(current_hp * random.uniform(0.40, 0.50)))
    return max(1, int(current_hp * random.uniform(0.30, 0.35)))


def get_love_value(inv: dict, uid: str, waifu_id: str) -> int:
    user = inv.get(str(uid), {})
    waifus = user.get("waifus", {})
    if isinstance(waifus, list):
        waifus = {wid: 0 for wid in waifus}
    value = waifus.get(waifu_id, 0)
    if isinstance(value, dict):
        value = value.get("love", value.get("amount", 0))
    if not isinstance(value, int):
        try:
            value = int(value)
        except Exception:
            value = 0
    return max(0, value)


def set_love_value(inv: dict, uid: str, waifu_id: str, value: int):
    user = inv.setdefault(str(uid), {})
    waifus = user.setdefault("waifus", {})
    if isinstance(waifus, list):
        waifus = {wid: 0 for wid in waifus}
        user["waifus"] = waifus
    waifus[waifu_id] = max(0, int(value))


def apply_love_drop(inv: dict, uid: str, waifu_id: str) -> int:
    old = get_love_value(inv, uid, waifu_id)
    new = int(old * (1 - LOVE_DROP_RATE))
    set_love_value(inv, uid, waifu_id, new)
    return new


def get_team_source(team_data, uid):
    user_data = team_data.get(str(uid), team_data.get(uid, {}))
    if isinstance(user_data, list):
        return list(user_data)
    if not isinstance(user_data, dict):
        return []
    for key in ("team", "waifus", "members", "list"):
        value = user_data.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def normalize_team_ids(inv, uid, team_data=None):
    team_data = team_data or {}
    source = get_team_source(team_data, uid)

    user = inv.get(str(uid), {})
    waifus = user.get("waifus", {})
    if isinstance(waifus, list):
        waifus = {w: 0 for w in waifus}

    if not source:
        default_id = user.get("default_waifu")
        if default_id:
            source = [default_id]
        elif isinstance(waifus, dict):
            source = list(waifus.keys())

    out = []
    seen = set()
    for wid in source:
        wid = str(wid)
        if wid in seen:
            continue
        if isinstance(waifus, dict) and wid in waifus:
            out.append(wid)
            seen.add(wid)
        if len(out) >= 3:
            break
    return out


def _as_waifu_dict(inv: dict, uid: str) -> dict:
    user = inv.setdefault(str(uid), {})
    waifus = user.setdefault("waifus", {})
    if isinstance(waifus, list):
        waifus = {wid: 0 for wid in waifus}
        user["waifus"] = waifus
    return waifus


def _as_bag_dict(inv: dict, uid: str) -> dict:
    user = inv.setdefault(str(uid), {})
    bag = user.setdefault("bag", {})
    if isinstance(bag, list):
        bag = {}
        user["bag"] = bag
    return bag


def is_on_cooldown(uid1: str, uid2: str) -> Tuple[bool, int]:
    key = tuple(sorted((str(uid1), str(uid2))))
    expiry = COOLDOWNS.get(key)
    if not expiry:
        return False, 0
    remain = int(expiry - asyncio.get_event_loop().time())
    if remain <= 0:
        COOLDOWNS.pop(key, None)
        return False, 0
    return True, remain


def set_cooldown(uid1: str, uid2: str, hours: int = 8):
    key = tuple(sorted((str(uid1), str(uid2))))
    COOLDOWNS[key] = asyncio.get_event_loop().time() + hours * 3600


# ===== BUILD COMBATANT =====
def build_combatant(user_id: str, waifu_id: str, inv: dict, waifu_data: dict) -> dict:
    meta = waifu_data.get(waifu_id, {}) or {}
    rank = meta.get("rank", "thuong")
    if rank not in RANK_ORDER:
        rank = "thuong"

    love = get_love_value(inv, user_id, waifu_id)
    level = max(1, int(love // 100) + 1)

    base_stats = {
        "thuong": (10, 2),
        "anh_hung": (35, 4),
        "huyen_thoai": (80, 6),
        "truyen_thuyet": (150, 8),
        "toi_thuong": (300, 10),
        "limited": (500, 15),
    }
    base_hp, base_dmg = base_stats.get(rank, (10, 2))

    max_hp = max(1, base_hp * level + min(love // 10, 1000))
    damage = max(1, int(level * base_dmg * 3))
    speed = max(1, int(level * base_dmg + love // 20))
    crit_chance = get_battle_crit_chance(love / 100.0)

    name = meta.get("name") or meta.get("display_name") or waifu_id

    return {
        "user_id": str(user_id),
        "waifu_id": waifu_id,
        "name": name,
        "rank": rank,
        "love": love,
        "level": level,
        "hp": max_hp,
        "max_hp": max_hp,
        "damage": damage,
        "speed": speed,
        "crit_chance": crit_chance,
        "combo_ready": False,
        "alive": True,
    }


def team_status_text(team: List[dict]) -> str:
    if not team:
        return "Không có waifu."

    out = []
    for c in team:
        hp = max(0, int(c["hp"]))
        max_hp = max(1, int(c["max_hp"]))
        out.append(f"**{c['name']}** | `{hp}/{max_hp}` `{hp_bar(hp, max_hp)}`")
    return "\n".join(out)


# ===== FIGHT SESSION =====
class FightSession:
    def __init__(
        self,
        ctx,
        challenger_id: str,
        opponent_id: str,
        team_a_ids: List[str],
        team_b_ids: List[str],
        inv: dict,
        waifu_data: dict,
        name_a: str,
        name_b: str,
        luck_a: float = 1.0,
        luck_b: float = 1.0,
    ):
        self.ctx = ctx
        self.inv = inv
        self.waifu_data = waifu_data
        self.challenger_id = str(challenger_id)
        self.opponent_id = str(opponent_id)
        self.name_a = name_a
        self.name_b = name_b
        self.luck_a = float(luck_a or 1.0)
        self.luck_b = float(luck_b or 1.0)

        self.team_a = [build_combatant(self.challenger_id, wid, inv, waifu_data) for wid in team_a_ids]
        self.team_b = [build_combatant(self.opponent_id, wid, inv, waifu_data) for wid in team_b_ids]

        self.turn = 1
        self.logs: List[str] = []
        self.affected_pairs = set()
        self.draw = False
        self.max_rounds = MAX_ROUNDS

    def add_log(self, text: str):
        self.logs.append(text)
        self.logs = trim_lines(self.logs, MAX_LOG_LINES)

    def completed_turn(self) -> int:
        return max(1, self.turn - 1)

    def is_over(self) -> bool:
        a_alive = any(c["alive"] and c["hp"] > 0 for c in self.team_a)
        b_alive = any(c["alive"] and c["hp"] > 0 for c in self.team_b)
        return not (a_alive and b_alive)

    def get_alive_team(self, side: str) -> List[dict]:
        return [c for c in (self.team_a if side == "a" else self.team_b) if c["alive"] and c["hp"] > 0]

    def choose_attacker(self, side: str) -> Optional[dict]:
        alive = self.get_alive_team(side)
        if not alive:
            return None
        if len(alive) == 1:
            return alive[0]
        weights = [max(1, c["speed"]) for c in alive]
        return random.choices(alive, weights=weights, k=1)[0]

    def choose_defender(self, side: str) -> Optional[dict]:
        enemy = self.get_alive_team("b" if side == "a" else "a")
        if not enemy:
            return None
        return random.choice(enemy)

    def get_side_name(self, side: str) -> str:
        return self.name_a if side == "a" else self.name_b

    def get_side_id(self, side: str) -> str:
        return self.challenger_id if side == "a" else self.opponent_id

    def render_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"The battle giữa {self.name_a} và {self.name_b}",
            color=discord.Color.red() if self.turn < self.max_rounds else discord.Color.gold(),
        )
        embed.add_field(
            name=f"🔴 {self.name_a}",
            value=team_status_text(self.team_a)[:1000] or "Không có waifu.",
            inline=True,
        )
        embed.add_field(
            name=f"🔵 {self.name_b}",
            value=team_status_text(self.team_b)[:1000] or "Không có waifu.",
            inline=True,
        )
        embed.add_field(
            name="Diễn biến",
            value="\n".join(self.logs)[:1000] or "Chưa có diễn biến.",
            inline=False,
        )
        embed.set_footer(text=f"Turn {self.turn}/{self.max_rounds}")
        return embed

    async def attack(self, message, attacker: dict, defender: dict) -> None:
        if not attacker or not defender or attacker["hp"] <= 0 or defender["hp"] <= 0:
            return

        dodge_chance = get_dodge_chance(attacker["speed"], defender["speed"])
        if random.random() < dodge_chance:
            defender["combo_ready"] = True
            self.add_log(f"💨 {defender['name']} né đòn của {attacker['name']}!")
            await edit_like(message, embed=self.render_embed())
            await asyncio.sleep(ACTION_DELAY)
            return

        base_damage = int(attacker["damage"] * random.uniform(0.90, 1.10))
        is_crit = random.random() < attacker["crit_chance"]
        is_combo = bool(attacker.get("combo_ready") and is_crit)

        # Heal crit
        if is_crit and random.choice(["damage", "heal"]) == "heal":
            heal_amount = get_crit_heal(attacker["hp"], is_combo)
            start_hp = attacker["hp"]
            end_hp = min(attacker["max_hp"], start_hp + heal_amount)
            actual = end_hp - start_hp

            attacker["hp"] = end_hp
            attacker["combo_ready"] = False

            label = "✨" if is_combo else "💚"
            self.add_log(f"{label} {attacker['name']} đã hồi máu và nhận được {actual}HP.")
            await edit_like(message, embed=self.render_embed())
            return

        # Damage
        damage = get_crit_damage(base_damage, is_combo) if is_crit else base_damage
        start_hp = defender["hp"]
        end_hp = max(0, start_hp - damage)
        defender["hp"] = end_hp
        attacker["combo_ready"] = False

        if is_crit and is_combo:
            self.add_log(f"🔥 {attacker['name']} COMBO CRIT {defender['name']} gây {damage} dame!")
        elif is_crit:
            self.add_log(f"💥 {attacker['name']} CRIT {defender['name']} gây {damage} dame!")
        else:
            self.add_log(f"⚔️ {attacker['name']} đánh {defender['name']} gây {damage} dame!")

        if end_hp <= 0:
            defender["alive"] = False
            old_love = get_love_value(self.inv, defender["user_id"], defender["waifu_id"])
            new_love = apply_love_drop(self.inv, defender["user_id"], defender["waifu_id"])
            self.affected_pairs.add((defender["user_id"], defender["waifu_id"]))
            self.add_log(f"☠️ {defender['name']} đã bị hạ gục. Love giảm từ {old_love} còn {new_love}.")

        await edit_like(message, embed=self.render_embed())

    async def play_round(self, message):
        if self.is_over():
            return

        # Initiative: team nào total speed cao hơn sẽ đi trước
        speed_a = sum(c["speed"] for c in self.get_alive_team("a"))
        speed_b = sum(c["speed"] for c in self.get_alive_team("b"))
        roll_a = speed_a + random.randint(0, max(1, speed_a // 5 + 1))
        roll_b = speed_b + random.randint(0, max(1, speed_b // 5 + 1))

        order = ("a", "b") if roll_a >= roll_b else ("b", "a")

        for side in order:
            if self.is_over():
                break
            attacker = self.choose_attacker(side)
            defender = self.choose_defender(side)
            if not attacker or not defender:
                continue
            await self.attack(message, attacker, defender)
            if self.is_over():
                break

        self.turn += 1

    def get_winner_side(self) -> Optional[str]:
        a_alive = any(c["alive"] and c["hp"] > 0 for c in self.team_a)
        b_alive = any(c["alive"] and c["hp"] > 0 for c in self.team_b)
        if a_alive and not b_alive:
            return "a"
        if b_alive and not a_alive:
            return "b"
        return None

    def get_turn_rank_cap(self) -> str:
        t = self.completed_turn()
        if t <= 1:
            return "limited"
        if t <= 4:
            return "toi_thuong"
        if t <= 7:
            return "truyen_thuyet"
        if t <= 10:
            return "huyen_thoai"
        if t <= 14:
            return "anh_hung"
        return "thuong"

    def choose_reward_waifu(self, loser_id: str, winner_id: str, cap_rank: Optional[str] = None) -> Optional[str]:
        loser = self.inv.get(str(loser_id), {})
        winner = self.inv.get(str(winner_id), {})
        loser_waifus = loser.get("waifus", {})
        winner_waifus = winner.get("waifus", {})

        if isinstance(loser_waifus, list):
            loser_waifus = {w: 0 for w in loser_waifus}
        if isinstance(winner_waifus, list):
            winner_waifus = {w: 0 for w in winner_waifus}

        if not isinstance(loser_waifus, dict):
            return None
        if not isinstance(winner_waifus, dict):
            winner_waifus = {}

        cap_rank = cap_rank or "thuong"
        cap_idx = RANK_ORDER.index(cap_rank) if cap_rank in RANK_ORDER else 0

        candidates = []
        for wid in loser_waifus.keys():
            if wid in winner_waifus:
                continue
            rank = self.waifu_data.get(wid, {}).get("rank", "thuong")
            if rank not in RANK_ORDER:
                rank = "thuong"
            rank_idx = RANK_ORDER.index(rank)
            if rank_idx <= cap_idx:
                candidates.append(wid)

        return random.choice(candidates) if candidates else None

    def transfer_reward_waifu(self, loser_id: str, winner_id: str) -> Tuple[Optional[str], str]:
        cap_rank = self.get_turn_rank_cap()

        # ===== DROP RATE =====
        t = self.completed_turn()

        if t == 1:
            drop_rate = 1.0
        elif t <= 5:
            drop_rate = 0.8
        elif t <= 10:
            drop_rate = 0.6
        else:
            drop_rate = 0.4

        # ===== ROLL =====
        if random.random() > drop_rate:
            return None, f"{cap_rank} | ❌ Không drop ({int(drop_rate * 100)}%)"

        chosen = self.choose_reward_waifu(loser_id, winner_id, cap_rank=cap_rank)

        if not chosen:
            return None, f"{cap_rank} | ❌ Không có waifu phù hợp"

        loser = self.inv.setdefault(str(loser_id), {})
        winner = self.inv.setdefault(str(winner_id), {})

        loser_waifus = loser.setdefault("waifus", {})
        winner_waifus = winner.setdefault("waifus", {})
        winner_bag = winner.setdefault("bag", {})

        if isinstance(loser_waifus, list):
            loser_waifus = {w: 0 for w in loser_waifus}
            loser["waifus"] = loser_waifus

        if isinstance(winner_waifus, list):
            winner_waifus = {w: 0 for w in winner_waifus}
            winner["waifus"] = winner_waifus

        if isinstance(winner_bag, list):
            winner_bag = {}
            winner["bag"] = winner_bag

        love = int(loser_waifus.get(chosen, 0))
        loser_waifus.pop(chosen, None)

        if chosen in winner_waifus:
            winner_bag[chosen] = int(winner_bag.get(chosen, 0)) + 1
        else:
            winner_waifus[chosen] = 0 if LOVE_RESET_ON_TRANSFER else love

        return chosen, f"{cap_rank} | ✅ Drop ({int(drop_rate * 100)}%)"

    def transfer_gold(self, loser_id: str, winner_id: str, loser_points: int) -> int:
        amount = max(0, int(loser_points))
        half = amount // 2

        if half > 0:
            data_user.add_gold(str(winner_id), half)
            try:
                data_user.remove_gold(str(loser_id), half)
            except Exception:
                pass

        return half

    async def commit_and_sync(self):
        # Save an toàn: chỉ merge các user bị ảnh hưởng để tránh battle khác đè nhau
        async with INV_LOCK:
            latest = load_json(INV_FILE)

            touched_users = {self.challenger_id, self.opponent_id}
            touched_users.update(uid for uid, _ in self.affected_pairs)

            for uid in touched_users:
                uid = str(uid)
                if uid in self.inv:
                    latest[uid] = self.inv[uid]

            save_json(INV_FILE, latest)
              self.inv = latest

        try:
            level_mod = importlib.import_module("Data.level")
            if hasattr(level_mod, "sync_one"):
                for uid, wid in self.affected_pairs:
                    try:
                        level_mod.sync_one(uid, wid)
                    except Exception:
                        pass
            elif hasattr(level_mod, "check_and_update_level"):
                for uid, wid in self.affected_pairs:
                    try:
                        level_mod.check_and_update_level(uid, wid)
                    except Exception:
                        pass
        except Exception:
            pass


# ===== LUCK HELPER =====
def _get_luck_from_prayer(user_id: str) -> float:
    try:
        from Commands.prayer import get_luck  # type: ignore
        return float(get_luck(str(user_id)) or 1.0)
    except Exception:
        return 1.0


# ===== COOLDOWN HELPERS =====
def _battle_key(uid1: str, uid2: str) -> Tuple[str, str]:
    return tuple(sorted((str(uid1), str(uid2))))


# ===== MAIN LOGIC =====
async def fight_logic(ctx, opponent):
    challenger = get_user_obj(ctx)
    if challenger is None:
        return await send_like(ctx, content="❌ Không xác định được người dùng.")

    if opponent is None:
        return await send_like(ctx, content="❌ Chọn đối thủ đã.")

    if hasattr(opponent, "id"):
        opponent_id = str(opponent.id)
        opponent_name = getattr(opponent, "display_name", getattr(opponent, "name", f"<@{opponent_id}>"))
    else:
        opponent_id = str(opponent)
        opponent_name = str(opponent)

    challenger_id = str(challenger.id)
    challenger_name = getattr(challenger, "display_name", getattr(challenger, "name", f"<@{challenger_id}>"))

    if challenger_id == opponent_id:
        return await send_like(ctx, content="❌ Không thể đấu với chính mình.")

    on_cd, remain = is_on_cooldown(challenger_id, opponent_id)
    if on_cd:
        hrs = remain // 3600
        mins = (remain % 3600) // 60
        return await send_like(ctx, content=f"⏳ Hai người đã đấu gần đây. Còn cooldown {hrs}h {mins}p.")

    inv = load_json(INV_FILE)
    waifu_data = load_json(WAIFU_FILE)
    team_data = load_json(TEAM_FILE)

    if str(challenger_id) not in inv or str(opponent_id) not in inv:
        return await send_like(ctx, content="❌ Một trong hai người chưa có inventory.")

    team_a_ids = normalize_team_ids(inv, challenger_id, team_data)
    team_b_ids = normalize_team_ids(inv, opponent_id, team_data)

    if not team_a_ids:
        return await send_like(ctx, content="❌ Bạn chưa có waifu hợp lệ để đấu.")
    if not team_b_ids:
        return await send_like(ctx, content="❌ Đối thủ chưa có waifu hợp lệ để đấu.")

    luck_a = _get_luck_from_prayer(challenger_id)
    luck_b = _get_luck_from_prayer(opponent_id)

    original_inv = copy.deepcopy(inv)
    working_inv = copy.deepcopy(inv)

    # Chặn 1 user không bị kéo vào nhiều battle cùng lúc
    async with BATTLE_STATE_LOCK:
        if challenger_id in ACTIVE_BATTLE_USERS or opponent_id in ACTIVE_BATTLE_USERS:
            return await send_like(ctx, content="⏳ Một trong hai người đang ở trong trận khác.")
        ACTIVE_BATTLE_USERS.add(challenger_id)
        ACTIVE_BATTLE_USERS.add(opponent_id)

    try:
        session = FightSession(
            ctx=ctx,
            challenger_id=challenger_id,
            opponent_id=opponent_id,
            team_a_ids=team_a_ids,
            team_b_ids=team_b_ids,
            inv=working_inv,
            waifu_data=waifu_data,
            name_a=challenger_name,
            name_b=opponent_name,
            luck_a=luck_a,
            luck_b=luck_b,
        )

        message = await send_like(ctx, content="⚔️ Trận chiến bắt đầu!", embed=session.render_embed())
        if not message:
            return

        try:
            for _ in range(MAX_ROUNDS):
                if session.is_over():
                    break
                await session.play_round(message)

            winner_side = session.get_winner_side()

            if winner_side is None:
                session.draw = True
                async with INV_LOCK:
                    save_json(INV_FILE, original_inv)
                await edit_like(
                    message,
                    content=f"Trận chiến giữa {challenger_name} và {opponent_name} chưa được phân thắng bại. Đã xử hoà!",
                    embed=session.render_embed(),
                )
                return

            winner_id = session.get_side_id(winner_side)
            loser_side = "b" if winner_side == "a" else "a"
            loser_id = session.get_side_id(loser_side)

            chosen, cap_rank = session.transfer_reward_waifu(loser_id, winner_id)

            loser_gold = (data_user.get_user(loser_id) or {}).get("gold", 0)
            t = session.completed_turn()

            # ===== GOLD RATE THEO TURN =====
            if t == 1:
                gold_rate = 0.9
            elif t <= 4:
                gold_rate = 0.7
            elif t <= 7:
                gold_rate = 0.6
            elif t <= 10:
                gold_rate = 0.5
            elif t <= 13:
                gold_rate = 0.4
            else:
                gold_rate = 0.2

            if t >= 30:
                gold_rate = 0.0

            # ===== XỬ LÝ REWARD =====
            if not chosen:
                bonus = int(loser_gold * gold_rate)
                if bonus > 0:
                    data_user.add_gold(winner_id, bonus)
                    try:
                        data_user.remove_gold(loser_id, bonus)
                    except Exception:
                        pass
                reward_text = f"💰 Không có waifu → nhận {bonus} gold ({int(gold_rate * 100)}%) | {cap_rank}"
            else:
                reward_text = f"🎁 Waifu **{chosen}** | {cap_rank}"

            await session.commit_and_sync()

            win_name = session.get_side_name(winner_side)
            lose_name = session.get_side_name(loser_side)

            result_embed = discord.Embed(
                title="Kết quả",
                description=f"🏆 {win_name} chiến thắng trước {lose_name}!",
                color=discord.Color.green(),
            )
            result_embed.add_field(name="Phần thưởng", value=reward_text, inline=False)

            await edit_like(message, content=None, embed=result_embed)
            set_cooldown(challenger_id, opponent_id, hours=COOLDOWN_HOURS)

        except Exception as e:
            await send_like(ctx, content=f"❌ Lỗi khi xử lý trận đấu: {e}")

    finally:
        async with BATTLE_STATE_LOCK:
            ACTIVE_BATTLE_USERS.discard(challenger_id)
            ACTIVE_BATTLE_USERS.discard(opponent_id)


# ===== SETUP =====
async def setup(bot):
    return None


print("Loaded fight.py (FAST / NO SMOOTH / CONCURRENT SAFE)!")
