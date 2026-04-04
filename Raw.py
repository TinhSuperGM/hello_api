import asyncio
import copy
import importlib
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import discord

from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAM_FILE = os.path.join(BASE_DIR, "Data", "team.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
COOLDOWN_FILE = os.path.join(BASE_DIR, "Data", "fight_cooldown.json")
VN_TZ = timezone(timedelta(hours=7))

MAX_TEAM_SIZE = 3
MAX_ROUNDS = 30
ACTION_DELAY = 1.0
MAX_LOG_LINES = 12
LOVE_DROP_RATE = 0.10
LOVE_RESET_ON_TRANSFER = True
COOLDOWN_HOURS = 8

RANK_ORDER = ["thuong", "anh_hung", "huyen_thoai", "truyen_thuyet", "toi_thuong", "limited"]
RANK_STATS = {
    "thuong": {"hp": 10, "dmg": 2, "speed": 2.0, "luck": 1.00},
    "anh_hung": {"hp": 25, "dmg": 3, "speed": 2.5, "luck": 1.05},
    "huyen_thoai": {"hp": 60, "dmg": 4, "speed": 3.0, "luck": 1.10},
    "truyen_thuyet": {"hp": 120, "dmg": 5, "speed": 3.5, "luck": 1.15},
    "toi_thuong": {"hp": 220, "dmg": 6, "speed": 4.0, "luck": 1.20},
    "limited": {"hp": 450, "dmg": 8, "speed": 4.8, "luck": 1.25},
}


def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_user_obj(ctx):
    return getattr(ctx, "user", None) or getattr(ctx, "author", None)


async def send_like(ctx, content=None, embed=None, view=None, ephemeral=False):
    # ===== SLASH =====
    if hasattr(ctx, "response"):
        if not ctx.response.is_done():
            return await ctx.response.send_message(
                content=content, embed=embed, view=view, ephemeral=ephemeral
            )
        return await ctx.followup.send(
            content=content, embed=embed, view=view, ephemeral=ephemeral
        )

    # ===== PREFIX =====
    if hasattr(ctx, "channel"):
        return await ctx.channel.send(
            content=content, embed=embed, view=view
        )
async def edit_like(message, *, content=None, embed=None, view=None):
    return await message.edit(content=content, embed=embed, view=view)


def get_team_source(team_data: dict, uid: str) -> list:
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


def normalize_team_ids(inv: dict, uid: str, team_data: Optional[dict] = None) -> list:
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
        if len(out) >= MAX_TEAM_SIZE:
            break
    return out


def hp_bar(current: int, max_hp: int, length: int = 10) -> str:
    max_hp = max(1, int(max_hp))
    current = max(0, min(int(current), max_hp))
    filled = round((current / max_hp) * length)
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)


def get_love_value(inv: dict, uid: str, waifu_id: str) -> int:
    user = inv.get(str(uid), {})
    waifus = user.get("waifus", {})
    if isinstance(waifus, list):
        waifus = {w: 0 for w in waifus}
    love = waifus.get(waifu_id, 0)
    if isinstance(love, dict):
        love = love.get("love", love.get("amount", 0))
    elif not isinstance(love, int):
        love = 0
    return int(love)


def set_love_value(inv: dict, uid: str, waifu_id: str, value: int) -> int:
    user = inv.setdefault(str(uid), {})
    waifus = user.setdefault("waifus", {})
    if isinstance(waifus, list):
        waifus = {w: 0 for w in waifus}
        user["waifus"] = waifus
    waifus[waifu_id] = max(0, int(value))
    return waifus[waifu_id]


def apply_love_drop(inv: dict, uid: str, waifu_id: str) -> int:
    old_love = get_love_value(inv, uid, waifu_id)
    new_love = int(old_love * (1.0 - LOVE_DROP_RATE))
    return set_love_value(inv, uid, waifu_id, new_love)


def reset_waifu_progress(inv: dict, uid: str, waifu_id: str) -> int:
    if LOVE_RESET_ON_TRANSFER:
        return set_love_value(inv, uid, waifu_id, 0)
    return get_love_value(inv, uid, waifu_id)


def get_rank_info(waifu_data: dict, waifu_id: str) -> Tuple[str, Dict[str, Any]]:
    meta = waifu_data.get(waifu_id, {})
    rank = meta.get("rank", "thuong")
    if rank not in RANK_STATS:
        rank = "thuong"
    return rank, RANK_STATS[rank]


def waifu_display_name(waifu_data: dict, waifu_id: str) -> str:
    meta = waifu_data.get(waifu_id, {})
    return meta.get("name") or meta.get("display_name") or waifu_id


def build_combatant(uid: str, waifu_id: str, inv: dict, waifu_data: dict) -> dict:
    love = get_love_value(inv, uid, waifu_id)
    rank, rank_stats = get_rank_info(waifu_data, waifu_id)
    level = max(1, 1 + love // 100)

    max_hp = int(rank_stats["hp"] * level + min(love // 4, 1200))
    damage = max(1, int(rank_stats["dmg"] * (1 + level * 0.35) + love // 30))
    speed = max(1, int(rank_stats["speed"] + level * 0.2 + love // 50))
    crit_chance = min(0.30, 0.05 + (rank_stats["luck"] - 1.0) * 0.10 + love / 2000)

    return {
        "user_id": str(uid),
        "waifu_id": waifu_id,
        "name": waifu_display_name(waifu_data, waifu_id),
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
    lines = []
    for c in team:
        hp = max(0, int(c["hp"]))
        max_hp = max(1, int(c["max_hp"]))
        lines.append(f"**{c['name']}** | `{hp}/{max_hp}` `{hp_bar(hp, max_hp)}`")
    return "\n".join(lines)


def trim_lines(lines: Sequence[str], limit: int = MAX_LOG_LINES) -> List[str]:
    lines = list(lines)
    return lines[-limit:]


def get_dodge_chance(attacker_speed: int, defender_speed: int) -> float:
    base = 0.05
    if defender_speed <= attacker_speed:
        return base
    bonus = min(0.20, (defender_speed - attacker_speed) / max(1.0, defender_speed * 4.0))
    return min(0.25, base + bonus)


def get_crit_damage(base_damage: int, combo: bool) -> int:
    bonus_min, bonus_max = (0.40, 0.50) if combo else (0.30, 0.35)
    return int(base_damage + base_damage * random.uniform(bonus_min, bonus_max))


def get_crit_heal(current_hp: int, combo: bool) -> int:
    bonus_min, bonus_max = (0.40, 0.50) if combo else (0.30, 0.35)
    return max(1, int(current_hp * random.uniform(bonus_min, bonus_max)))


def load_cooldowns() -> dict:
    return load_json(COOLDOWN_FILE)


def save_cooldowns(data: dict) -> None:
    save_json(COOLDOWN_FILE, data)


def is_on_cooldown(uid: str, target_id: str, now_ts: Optional[int] = None) -> Tuple[bool, int]:
    now_ts = now_ts or int(time.time())
    cooldowns = load_cooldowns()
    pair_key = ":".join(sorted([str(uid), str(target_id)]))
    until = int(cooldowns.get(pair_key, 0))
    if now_ts < until:
        return True, until - now_ts
    return False, 0


def set_cooldown(uid: str, target_id: str, hours: int = COOLDOWN_HOURS) -> None:
    cooldowns = load_cooldowns()
    now_ts = int(time.time())
    pair_key = ":".join(sorted([str(uid), str(target_id)]))
    cooldowns[pair_key] = now_ts + int(hours * 3600)
    save_cooldowns(cooldowns)


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
        embed.add_field(name=f"🔴 {self.name_a}", value=team_status_text(self.team_a)[:1000] or "Không có waifu.", inline=True)
        embed.add_field(name=f"🔵 {self.name_b}", value=team_status_text(self.team_b)[:1000] or "Không có waifu.", inline=True)
        embed.add_field(name="Diễn biến", value="\n".join(self.logs)[:1000] or "Chưa có diễn biến.", inline=False)
        embed.set_footer(text=f"Turn {self.turn}/{self.max_rounds}")
        return embed

    async def animate_hp_change(self, message, target: dict, start_hp: int, end_hp: int, steps: int = 8):
        steps = max(3, int(steps))
        delay = ACTION_DELAY / steps
        for i in range(1, steps + 1):
            cur = round(start_hp + (end_hp - start_hp) * i / steps)
            target["hp"] = max(0, min(target["max_hp"], cur))
            await edit_like(message, embed=self.render_embed())
            await asyncio.sleep(delay)

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

        if is_crit and random.choice(["damage", "heal"]) == "heal":
            heal_amount = get_crit_heal(attacker["hp"], is_combo)
            start_hp = attacker["hp"]
            end_hp = min(attacker["max_hp"], start_hp + heal_amount)
            actual = end_hp - start_hp
            attacker["combo_ready"] = False
            label = "✨" if is_combo else "💚"
            self.add_log(f"{label} {attacker['name']} đã hồi máu và nhận được {actual}HP.")
            await self.animate_hp_change(message, attacker, start_hp, end_hp)
            return

        damage = base_damage
        if is_crit:
            damage = get_crit_damage(base_damage, is_combo)

        start_hp = defender["hp"]
        end_hp = max(0, start_hp - damage)
        if is_crit and is_combo:
            self.add_log(f"🔥 {attacker['name']} COMBO CRIT {defender['name']} gây {damage} dame!")
        elif is_crit:
            self.add_log(f"💥 {attacker['name']} CRIT {defender['name']} gây {damage} dame!")
        else:
            self.add_log(f"⚔️ {attacker['name']} đánh {defender['name']} gây {damage} dame!")

        attacker["combo_ready"] = False
        await self.animate_hp_change(message, defender, start_hp, end_hp)

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

        for side in ("a", "b"):
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

        if t == 1:
            return "limited"
        if t <= 4:
            return "toi_thuong"
        if t <= 6:
            return "truyen_thuyet"
        if t <= 10:
            return "huyen_thoai"
        if t <= 13:
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

        cap_rank = cap_rank or "thuong"

        # 👉 thứ tự rank từ mạnh → yếu
        rank_order = ["limited", "toi_thuong", "truyen_thuyet", "huyen_thoai", "anh_hung", "thuong"]

        if cap_rank not in rank_order:
            return None

        start_index = rank_order.index(cap_rank)

        # ===== QUÉT TỪ CAP → XUỐNG =====
        for i in range(start_index, len(rank_order)):
            current_rank = rank_order[i]

            candidates = []
            for wid in loser_waifus.keys():
                rank, _ = get_rank_info(self.waifu_data, wid)

                if rank == current_rank:
                    candidates.append(wid)

            if candidates:
                return random.choice(candidates)

        return None

    def transfer_reward_waifu(self, loser_id: str, winner_id: str) -> Tuple[Optional[str], str]:
      t = self.completed_turn()

      # ===== HOÀ =====
      if t >= 30:
          return None, "draw"

      # ===== ROLL RANK =====
      r = random.random()

      if t == 1:
          if r < 0.01: target_rank = "limited"
          elif r < 0.11: target_rank = "toi_thuong"
          elif r < 0.31: target_rank = "truyen_thuyet"
          elif r < 0.61: target_rank = "huyen_thoai"
          else: target_rank = "anh_hung"

      elif t <= 4:
          if r < 0.05: target_rank = "toi_thuong"
          elif r < 0.20: target_rank = "truyen_thuyet"
          elif r < 0.50: target_rank = "huyen_thoai"
          else: target_rank = "anh_hung"

      elif t <= 7:
          if r < 0.10: target_rank = "truyen_thuyet"
          elif r < 0.40: target_rank = "huyen_thoai"
          else: target_rank = "anh_hung"

      elif t <= 10:
          if r < 0.05: target_rank = "truyen_thuyet"
          elif r < 0.30: target_rank = "huyen_thoai"
          else: target_rank = "anh_hung"

      elif t <= 14:
          if r < 0.20: target_rank = "huyen_thoai"
          else: target_rank = "anh_hung"

      else:
          target_rank = "thuong"

      # ===== DATA =====
      loser = self.inv.get(str(loser_id), {})
      winner = self.inv.get(str(winner_id), {})

      loser_waifus = loser.get("waifus", {})
      winner_waifus = winner.get("waifus", {})

      if isinstance(loser_waifus, list):
          loser_waifus = {w: 0 for w in loser_waifus}

      if isinstance(winner_waifus, list):
          winner_waifus = {w: 0 for w in winner_waifus}

      # ===== LỌC THEO RANK =====
      def get_candidates(rank):
          result = []
          for wid in loser_waifus:
              r, _ = get_rank_info(self.waifu_data, wid)
              if r == rank:
                  result.append(wid)
          return result

      # ===== FALLBACK ↓ (RẤT QUAN TRỌNG) =====
      RANK_ORDER_FIX = [
          "limited",
          "toi_thuong",
          "truyen_thuyet",
          "huyen_thoai",
          "anh_hung",
          "thuong"
      ]

      start_idx = RANK_ORDER_FIX.index(target_rank)

      chosen = None
      for i in range(start_idx, len(RANK_ORDER_FIX)):
          pool = get_candidates(RANK_ORDER_FIX[i])
          if pool:
              chosen = random.choice(pool)
              break

      # ===== KHÔNG CÓ WAIFU =====
      if not chosen:
          return None, f"{target_rank} | ❌ Không có waifu"

      # ===== CHUYỂN =====
      loser = self.inv.setdefault(str(loser_id), {})
      winner = self.inv.setdefault(str(winner_id), {})

      loser_waifus = loser.setdefault("waifus", {})
      winner_waifus = winner.setdefault("waifus", {})
      winner_bag = winner.setdefault("bag", {})

      if isinstance(winner_bag, list):
          winner_bag = {}
          winner["bag"] = winner_bag
  
      love = int(loser_waifus.get(chosen, 0))
      loser_waifus.pop(chosen, None)

      if chosen in winner_waifus:
          winner_bag[chosen] = int(winner_bag.get(chosen, 0)) + 1
      else:
          winner_waifus[chosen] = 0 if LOVE_RESET_ON_TRANSFER else love
  
      return chosen, f"{target_rank} | 🎯 Roll thành công"
def _get_luck_from_prayer(user_id: str) -> float:
    try:
        prayer = importlib.import_module("Commands.prayer")
        if hasattr(prayer, "get_luck"):
            return float(prayer.get_luck(user_id))
    except Exception:
        pass
    return 1.0


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
            await edit_like(message, embed=session.render_embed())

        winner_side = session.get_winner_side()

        if winner_side is None:
            session.draw = True
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

        loser_gold = data_user.get_user(loser_id).get("gold", 0)
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
            # 👉 fallback gold
            bonus = int(loser_gold * gold_rate)

            if bonus > 0:
                data_user.add_gold(winner_id, bonus)
                data_user.remove_gold(loser_id, bonus)

            half_gold = bonus
            reward_text = f"💰 Không có waifu → nhận {bonus} gold ({int(gold_rate*100)}%) | {cap_rank}"

        else:
            # 👉 có waifu thì mới chuyển 50% gold
            half_gold = 0
            reward_text = f"🎁 Waifu **{chosen}** | {cap_rank}"

        await session.commit_and_sync()
        save_json(INV_FILE, session.inv)

        win_name = session.get_side_name(winner_side)
        lose_name = session.get_side_name(loser_side)

        result_embed = discord.Embed(
            title="Kết quả",
            description=f"🏆 {win_name} chiến thắng trước {lose_name}!",
            color=discord.Color.green(),
        )
        result_embed.add_field(name="Phần thưởng", value=reward_text, inline=False)
        result_embed.add_field(name="Gold", value=f"💰 Chuyển {half_gold} gold từ người thua sang người thắng.", inline=False)

        await edit_like(message, content=None, embed=result_embed)
        set_cooldown(challenger_id, opponent_id, hours=COOLDOWN_HOURS)

    except Exception as e:
        await send_like(ctx, content=f"❌ Lỗi khi xử lý trận đấu: {e}")


def debug_snapshot(user_id: str) -> dict:
    inv = load_json(INV_FILE)
    team = load_json(TEAM_FILE)
    waifu_data = load_json(WAIFU_FILE)
    user = inv.get(str(user_id), {})
    waifus = user.get("waifus", {})
    if not isinstance(waifus, dict):
        waifus = {w: 0 for w in waifus} if isinstance(waifus, list) else {}
    return {
        "user_id": str(user_id),
        "default_waifu": user.get("default_waifu"),
        "waifus": waifus,
        "team": normalize_team_ids(inv, str(user_id), team),
        "waifu_meta": {wid: waifu_data.get(wid, {}) for wid in waifus},
    }


async def setup(bot):
    return None


print("Loaded fight.py!")
