from __future__ import annotations

import asyncio
import json
import os
import random
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

import discord

# ===== OPTIONAL LEVEL SYNC =====
try:
    from Data.level import sync_one as _sync_one
except Exception:
    try:
        from Data.level import check_and_update_level as _sync_one
    except Exception:
        def _sync_one(user_id: str, waifu_id: str):
            return None


# ===== FILE PATHS =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, 'Data', 'inventory.json')
LEVEL_FILE = os.path.join(BASE_DIR, 'Data', 'level.json')
WAIFU_FILE = os.path.join(BASE_DIR, 'Data', 'waifu_data.json')
TEAM_FILE = os.path.join(BASE_DIR, 'Data', 'team.json')
FIGHT_CD_FILE = os.path.join(BASE_DIR, 'Data', 'fight_cooldown.json')

# ===== DEBUG / BATTLE CONFIG =====
DEBUG_FIGHT = False
MAX_ROUNDS = 30
ACTION_DELAY = 2.0
MAX_LOG_LINES = 12
MAX_TEAM_SIZE = 3
LOVE_DROP_RATE = 0.10
LOVE_RESET_ON_TRANSFER = True
PAIR_COOLDOWN_SECONDS = 8 * 60 * 60

# ===== RANK ORDER =====
RANK_ORDER = [
    'thuong',
    'anh_hung',
    'huyen_thoai',
    'truyen_thuyet',
    'toi_thuong',
    'limited',
]

RANK_HP = {
    'thuong': 10,
    'anh_hung': 50,
    'huyen_thoai': 100,
    'truyen_thuyet': 300,
    'toi_thuong': 600,
    'limited': 900,
}

RANK_DMG = {
    'thuong': 2,
    'anh_hung': 4,
    'huyen_thoai': 6,
    'truyen_thuyet': 10,
    'toi_thuong': 12,
    'limited': 15,
}


# ===== JSON HELPERS =====
def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ===== SMALL HELPERS =====
def debug(*args):
    if DEBUG_FIGHT:
        print('[FIGHT DEBUG]', *args)


def rank_index(rank: str) -> int:
    try:
        return RANK_ORDER.index((rank or 'thuong').lower())
    except ValueError:
        return 0


def rank_leq(rank: str, cap_rank: str) -> bool:
    return rank_index(rank) <= rank_index(cap_rank)


def get_turn_rank_cap(turn: int) -> str:
    if turn <= 1:
        return 'limited'
    if turn <= 4:
        return 'toi_thuong'
    if turn <= 7:
        return 'truyen_thuyet'
    if turn <= 10:
        return 'huyen_thoai'
    if turn <= 14:
        return 'anh_hung'
    return 'thuong'


def hp_bar(current: int, max_hp: int, length: int = 12) -> str:
    if max_hp <= 0:
        return '░' * length
    ratio = max(0.0, min(1.0, current / max_hp))
    filled = int(round(ratio * length))
    filled = max(0, min(length, filled))
    return '█' * filled + '░' * (length - filled)


def get_user_obj(ctx):
    return ctx.user if hasattr(ctx, 'user') else ctx.author


def waifu_display_name(waifu_data: dict, waifu_id: str) -> str:
    meta = waifu_data.get(waifu_id, {})
    return str(meta.get('name') or meta.get('display_name') or waifu_id)


async def send_like(
    ctx,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    view=None,
    ephemeral: bool = False,
):
    kwargs = {}
    if content is not None:
        kwargs['content'] = content
    if embed is not None:
        kwargs['embed'] = embed
    if view is not None:
        kwargs['view'] = view
    if ephemeral:
        kwargs['ephemeral'] = True

    if hasattr(ctx, 'response') and hasattr(ctx.response, 'send_message'):
        is_done = getattr(ctx.response, 'is_done', None)
        if callable(is_done) and is_done():
            if hasattr(ctx, 'followup') and hasattr(ctx.followup, 'send'):
                return await ctx.followup.send(**kwargs)
            return await ctx.send(**kwargs)

        await ctx.response.send_message(**kwargs)
        try:
            return await ctx.original_response()
        except Exception:
            return None

    return await ctx.send(**kwargs)


async def edit_like(message: discord.Message, *, content: Optional[str] = None, embed: Optional[discord.Embed] = None, view=None):
    kwargs = {}
    if content is not None:
        kwargs['content'] = content
    if embed is not None:
        kwargs['embed'] = embed
    if view is not None:
        kwargs['view'] = view
    return await message.edit(**kwargs)


def get_inv_user(inv, user_id: str):
    if not inv:
        return {}

    user = inv.get(str(user_id))
    if not user:
        return {}

    if 'waifus' not in user:
        user['waifus'] = {}
    if 'bag' not in user:
        user['bag'] = {}
    if 'bag_item' not in user:
        user['bag_item'] = {}

    return user


def get_love_value(user_inv: dict, waifu_id: str) -> int:
    val = user_inv.get('waifus', {}).get(waifu_id, 0)
    if isinstance(val, int):
        return val
    if isinstance(val, dict):
        return int(val.get('love', 0))
    return 0


def set_love_value(user_inv: dict, waifu_id: str, love: int) -> None:
    user_inv.setdefault('waifus', {})
    user_inv['waifus'][waifu_id] = max(0, int(love))


def resolve_level_from_love(love: int) -> int:
    return max(1, love // 100)


def get_team_source(team_data: dict, user_id: str) -> Sequence[str]:
    if not team_data:
        return []

    raw = team_data.get(user_id)
    if not raw:
        return []

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):
        for key in ('team', 'waifus', 'list', 'members'):
            if isinstance(raw.get(key), list):
                return raw[key]

    return []


def normalize_team_ids(user_id: str, inv: dict, team_data: dict, explicit_team: Optional[Sequence[str]] = None) -> List[str]:
    user_inv = inv.get(user_id, {})
    waifus = user_inv.get('waifus', {})

    source = list(explicit_team or [])
    if not source:
        source = list(get_team_source(team_data, user_id))

    if not source:
        default_waifu = user_inv.get('default_waifu')
        if default_waifu:
            source = [default_waifu]
        elif isinstance(waifus, dict) and waifus:
            source = [next(iter(waifus.keys()))]

    out: List[str] = []
    seen = set()
    for wid in source:
        if not wid or wid in seen:
            continue
        if wid in waifus:
            out.append(wid)
            seen.add(wid)
        if len(out) >= MAX_TEAM_SIZE:
            break

    return out


def trim_lines(lines: List[str], limit: int = MAX_LOG_LINES) -> List[str]:
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def get_battle_crit_chance(luck: float) -> float:
    bonus = max(0.0, luck - 1.0)
    return min(0.30, 0.05 + bonus * 0.01)


def get_dodge_chance(attacker_speed: int, defender_speed: int) -> float:
    total = max(1, attacker_speed + defender_speed)
    ratio = defender_speed / total
    return min(0.25, 0.05 + ratio * 0.20)


def get_initiative_score(team: List[dict]) -> float:
    if not team:
        return 0.0
    total_speed = sum(max(1, c['speed']) for c in team if c['hp'] > 0)
    return total_speed + random.uniform(0, max(1.0, total_speed * 0.15))


def choose_weighted_attacker(team: List[dict]) -> Optional[dict]:
    living = [c for c in team if c['hp'] > 0]
    if not living:
        return None
    weights = [max(1, c['speed']) for c in living]
    return random.choices(living, weights=weights, k=1)[0]


def choose_random_target(team: List[dict]) -> Optional[dict]:
    living = [c for c in team if c['hp'] > 0]
    if not living:
        return None
    return random.choice(living)


def get_available_ranks_from_data(waifu_data: dict) -> List[str]:
    ranks = []
    seen = set()
    for meta in waifu_data.values():
        rank = str(meta.get('rank', 'thuong')).lower()
        if rank not in seen:
            seen.add(rank)
            ranks.append(rank)

    ordered = [r for r in RANK_ORDER if r in seen]
    extras = [r for r in ranks if r not in set(RANK_ORDER)]
    return ordered + extras


def choose_reward_waifu_by_rank(
    inv: dict,
    owner_id: str,
    waifu_data: dict,
    cap_rank: str,
) -> Optional[str]:
    user_inv = inv.get(owner_id, {})
    waifus = user_inv.get('waifus', {})
    if not isinstance(waifus, dict) or not waifus:
        return None

    available_ranks = get_available_ranks_from_data(waifu_data)
    if not available_ranks:
        available_ranks = list(RANK_ORDER)

    ranks_to_try = [r for r in available_ranks if rank_leq(r, cap_rank)]
    ranks_to_try.sort(key=rank_index, reverse=True)

    for rank in ranks_to_try:
        candidates = [
            wid for wid in waifus.keys()
            if str(waifu_data.get(wid, {}).get('rank', 'thuong')).lower() == rank
        ]
        if candidates:
            return random.choice(candidates)
    return None


def apply_love_drop(user_inv: dict, waifu_id: str) -> int:
    old_love = get_love_value(user_inv, waifu_id)
    new_love = int(old_love * (1 - LOVE_DROP_RATE))
    set_love_value(user_inv, waifu_id, new_love)
    return new_love


def reset_waifu_progress(user_inv: dict, waifu_id: str) -> None:
    if LOVE_RESET_ON_TRANSFER:
        set_love_value(user_inv, waifu_id, 0)


def add_waifu_to_bag(user_inv: dict, waifu_id: str) -> None:
    bag = user_inv.setdefault('bag', {})

    # Preferred format: bag['waifus'] = {waifu_id: amount}
    if isinstance(bag, dict):
        waifu_bag = bag.get('waifus')
        if waifu_bag is None:
            bag['waifus'] = {waifu_id: 1}
            return
        if isinstance(waifu_bag, dict):
            waifu_bag[waifu_id] = int(waifu_bag.get(waifu_id, 0)) + 1
            return
        if isinstance(waifu_bag, list):
            waifu_bag.append(waifu_id)
            return
        bag['waifus'] = {waifu_id: 1}
        return

    if isinstance(bag, list):
        bag.append(waifu_id)
        return

    user_inv['bag'] = {'waifus': {waifu_id: 1}}


def build_combatant(user_id: str, waifu_id: str, inv: dict, waifu_data: dict, luck: float) -> dict:
    user_inv = get_inv_user(inv, user_id)
    love = get_love_value(user_inv, waifu_id)
    level = resolve_level_from_love(love)

    rank = str(waifu_data.get(waifu_id, {}).get('rank', 'thuong')).lower()
    base_hp = RANK_HP.get(rank, 10)
    base_dmg = RANK_DMG.get(rank, 2)

    max_hp = base_hp * max(1, level) + min(love // 10, 1000)
    damage = max(1, int(level * base_dmg * 3))
    speed = max(1, int(level * base_dmg + love // 20))
    crit_chance = get_battle_crit_chance(luck)

    return {
        'user_id': user_id,
        'waifu_id': waifu_id,
        'name': waifu_display_name(waifu_data, waifu_id),
        'rank': rank,
        'love': love,
        'level': level,
        'max_hp': max_hp,
        'hp': max_hp,
        'damage': damage,
        'speed': speed,
        'crit_chance': crit_chance,
        'combo_ready': False,
        'alive': True,
    }


def team_status_text(team: List[dict]) -> str:
    if not team:
        return 'Không có waifu.'

    out = []
    for c in team:
        hp = max(0, c['hp'])
        max_hp = max(1, int(c['max_hp']))
        bar = hp_bar(hp, max_hp)
        out.append(f"**{c['name']}** | HP: `{hp}/{c['max_hp']}`\n"
                   f"{bar}")
    return '\n'.join(out)


# ===== COOLDOWN HELPERS =====
def pair_key(a: str, b: str) -> str:
    return '::'.join(sorted([str(a), str(b)]))


def load_battle_cooldowns() -> dict:
    data = load_json(FIGHT_CD_FILE)
    return data if isinstance(data, dict) else {}


def save_battle_cooldowns(data: dict) -> None:
    save_json(FIGHT_CD_FILE, data)


def get_pair_cooldown_remaining(user_a: str, user_b: str) -> int:
    data = load_battle_cooldowns()
    ts = data.get(pair_key(user_a, user_b))
    if ts is None:
        return 0
    try:
        last_ts = float(ts)
    except Exception:
        return 0
    remaining = int(PAIR_COOLDOWN_SECONDS - (time.time() - last_ts))
    return max(0, remaining)


def mark_pair_cooldown(user_a: str, user_b: str) -> None:
    data = load_battle_cooldowns()
    data[pair_key(user_a, user_b)] = time.time()
    save_battle_cooldowns(data)


class FightSession:
    def __init__(
        self,
        challenger_name: str,
        defender_name: str,
        challenger_id: str,
        defender_id: str,
        team_a_ids: List[str],
        team_b_ids: List[str],
        inv: dict,
        waifu_data: dict,
        luck_a: float = 1.0,
        luck_b: float = 1.0,
    ):
        self.challenger_name = challenger_name
        self.defender_name = defender_name
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.inv = inv
        self.waifu_data = waifu_data
        self.luck_a = luck_a
        self.luck_b = luck_b

        self.team_a = [build_combatant(challenger_id, wid, inv, waifu_data, luck_a) for wid in team_a_ids]
        self.team_b = [build_combatant(defender_id, wid, inv, waifu_data, luck_b) for wid in team_b_ids]

        self.turn = 1
        self.logs: List[str] = []
        self.affected_pairs: set[Tuple[str, str]] = set()
        self.draw = False
        self.elapsed_seconds = 0

    def completed_turn(self) -> int:
        return max(1, self.turn - 1)

    def is_over(self) -> bool:
        a_alive = any(c['hp'] > 0 for c in self.team_a)
        b_alive = any(c['hp'] > 0 for c in self.team_b)
        return not (a_alive and b_alive)

    def side_name(self, side: str) -> str:
        return self.challenger_name if side == 'a' else self.defender_name

    def side_id(self, side: str) -> str:
        return self.challenger_id if side == 'a' else self.defender_id

    def total_speed(self, side: str) -> float:
        team = self.team_a if side == 'a' else self.team_b
        return sum(max(1, c['speed']) for c in team if c['hp'] > 0)

    def choose_attacker(self, side: str) -> Optional[dict]:
        team = self.team_a if side == 'a' else self.team_b
        return choose_weighted_attacker(team)

    def choose_defender(self, side: str) -> Optional[dict]:
        team = self.team_b if side == 'a' else self.team_a
        return choose_random_target(team)

    def add_log(self, line: str) -> None:
        self.logs.append(line)
        debug(line)

    def stamp(self, text):
        return text

    def attack(self, attacker: dict, defender: dict) -> str:
        if attacker['hp'] <= 0 or defender['hp'] <= 0:
            return ''

        dodge_chance = get_dodge_chance(attacker['speed'], defender['speed'])
        if random.random() < dodge_chance:
            defender['combo_ready'] = True
            return self.stamp(f"💨 {attacker['name']} đánh hụt {defender['name']}.")

        base_damage = int(attacker['damage'] * random.uniform(0.90, 1.10))
        is_crit = random.random() < attacker['crit_chance']
        is_combo = bool(attacker['combo_ready'] and is_crit)

        if is_crit and random.choice(['damage', 'heal']) == 'heal':
            bonus_min, bonus_max = (0.40, 0.50) if is_combo else (0.30, 0.35)
            heal_amount = max(1, int(attacker['hp'] * random.uniform(bonus_min, bonus_max)))
            before_hp = attacker['hp']
            attacker['hp'] = min(attacker['max_hp'], attacker['hp'] + heal_amount)
            actual_heal = attacker['hp'] - before_hp
            attacker['combo_ready'] = False

            if is_combo:
                return self.stamp(f"💚 {attacker['name']} đã hồi máu combo và nhận được {actual_heal}HP.")
            return self.stamp(f"🩸 {attacker['name']} đã hồi máu và nhận được {actual_heal}HP.")

        damage = base_damage
        if is_crit:
            bonus_min, bonus_max = (0.40, 0.50) if is_combo else (0.30, 0.35)
            damage = int(base_damage + base_damage * random.uniform(bonus_min, bonus_max))

        defender['hp'] -= damage
        attacker['combo_ready'] = False

        if defender['hp'] <= 0:
            defender['hp'] = 0
            defender['alive'] = False
            target_user_inv = get_inv_user(self.inv, defender['user_id'])
            old_love = get_love_value(target_user_inv, defender['waifu_id'])
            new_love = apply_love_drop(target_user_inv, defender['waifu_id'])
            self.affected_pairs.add((defender['user_id'], defender['waifu_id']))
            return self.stamp(
                f"☠️ {attacker['name']} đánh {defender['name']} gây {damage} dame. {defender['name']} đã bị hạ gục. Love giảm từ {old_love} còn {new_love}."
            )

        return self.stamp(f"💥 {attacker['name']} đánh {defender['name']} gây {damage} dame.")

    async def render_step(self, message: discord.Message, log_line: str) -> None:
        if log_line:
            self.add_log(log_line)
        try:
            await edit_like(message, embed=self.render_embed())
        except Exception as e:
            debug('edit failed:', e)
            raise

    async def sleep_step(self) -> None:
        self.elapsed_seconds += int(ACTION_DELAY)
        await asyncio.sleep(ACTION_DELAY)

    async def play_round(self, message: discord.Message) -> None:
        score_a = self.total_speed('a')
        score_b = self.total_speed('b')
        if score_a <= 0 or score_b <= 0:
            return

        if get_initiative_score(self.team_a) >= get_initiative_score(self.team_b):
            first_side, second_side = 'a', 'b'
        else:
            first_side, second_side = 'b', 'a'

        for side in (first_side, second_side):
            if self.is_over():
                break

            attacker = self.choose_attacker(side)
            defender = self.choose_defender(side)

            if not attacker or not defender:
                break

            line = self.attack(attacker, defender)
            await self.render_step(message, line)

            if self.is_over():
                break

            await self.sleep_step()

        self.turn += 1

    def get_winner_side(self) -> Optional[str]:
        a_alive = any(c['hp'] > 0 for c in self.team_a)
        b_alive = any(c['hp'] > 0 for c in self.team_b)

        if a_alive and not b_alive:
            return 'a'
        if b_alive and not a_alive:
            return 'b'
        return None

    def render_embed(self) -> discord.Embed:
        title = f'The battle giữa {self.challenger_name} và {self.defender_name}'

        emb = discord.Embed(
            title=title,
            color=0xFF4D4D if self.completed_turn() < MAX_ROUNDS else 0xFFD700,
        )

        emb.add_field(
            name=f'🔴 {self.challenger_name}',
            value=team_status_text(self.team_a)[:1000] or 'Không có waifu.',
            inline=True,
        )
        emb.add_field(
            name=f'🔵 {self.defender_name}',
            value=team_status_text(self.team_b)[:1000] or 'Không có waifu.',
            inline=True,
        )

        log_text = '\n'.join(trim_lines(self.logs, MAX_LOG_LINES)) or 'Chưa có diễn biến.'
        emb.add_field(
            name='Diễn biến',
            value=log_text[:1024],
            inline=False,
        )

        emb.set_footer(text=f'Turn hiện tại: {self.completed_turn()}')
        return emb

    def commit_and_sync(self) -> None:
        save_json(INV_FILE, self.inv)
        for user_id, waifu_id in self.affected_pairs:
            try:
                _sync_one(str(user_id), str(waifu_id))
            except Exception as e:
                debug('sync_one failed:', user_id, waifu_id, e)

    def _move_waifu_to_winner(self, loser_id: str, winner_id: str, waifu_id: str) -> str:
        loser_inv = get_inv_user(self.inv, loser_id)
        winner_inv = get_inv_user(self.inv, winner_id)

        love_before = get_love_value(loser_inv, waifu_id)
        loser_inv.get('waifus', {}).pop(waifu_id, None)

        if waifu_id in winner_inv.get('waifus', {}):
            add_waifu_to_bag(winner_inv, waifu_id)
            self.affected_pairs.add((winner_id, waifu_id))
            self.affected_pairs.add((loser_id, waifu_id))
            return f'Waifu **{waifu_display_name(self.waifu_data, waifu_id)}** bị trùng nên đã chuyển vào bag.'

        set_love_value(winner_inv, waifu_id, 0)
        self.affected_pairs.add((winner_id, waifu_id))
        self.affected_pairs.add((loser_id, waifu_id))
        return f'Chuyển waifu **{waifu_display_name(self.waifu_data, waifu_id)}** (love cũ {love_before}) sang người thắng.'

    def transfer_reward_waifu(self, from_user: str, to_user: str, cap_rank: str) -> str:
        chosen = choose_reward_waifu_by_rank(self.inv, from_user, self.waifu_data, cap_rank)
        if not chosen:
            return 'Không có waifu phù hợp để chuyển.'
        return self._move_waifu_to_winner(from_user, to_user, chosen)

    def transfer_gold(self, loser_id: str, winner_id: str) -> Tuple[int, int]:
        loser_inv = get_inv_user(self.inv, loser_id)
        winner_inv = get_inv_user(self.inv, winner_id)

        loser_gold = int(loser_inv.get('gold', 0))
        gain = loser_gold // 2
        loser_inv['gold'] = max(0, loser_gold - gain)
        winner_inv['gold'] = int(winner_inv.get('gold', 0)) + gain
        return gain, loser_inv['gold']

    def apply_final_rewards(self) -> List[str]:
        logs: List[str] = []
        winner_side = self.get_winner_side()
        if winner_side is None:
            return logs

        winner_id = self.side_id(winner_side)
        loser_id = self.defender_id if winner_side == 'a' else self.challenger_id
        cap_rank = get_turn_rank_cap(self.completed_turn())

        note = self.transfer_reward_waifu(loser_id, winner_id, cap_rank)
        logs.append(f'🎁 {note} | Rank cap: **{cap_rank}**')

        gold_gain, gold_left = self.transfer_gold(loser_id, winner_id)
        logs.append(f'💰 Chuyển {gold_gain} gold từ người thua sang người thắng. Gold còn lại của người thua: {gold_left}.')

        return logs


async def fight_logic(
    ctx: Any,
    opponent: Any,
    *,
    team_a: Optional[Sequence[str]] = None,
    team_b: Optional[Sequence[str]] = None,
):
    challenger = get_user_obj(ctx)
    defender = opponent

    if defender is None:
        return await send_like(
            ctx,
            '❌ Bạn phải chọn một người để khiêu chiến.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )

    if challenger.id == defender.id:
        return await send_like(
            ctx,
            '❌ Bạn không thể tự khiêu chiến chính mình.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )

    inv = load_json(INV_FILE)
    waifu_data = load_json(WAIFU_FILE)
    team_data = load_json(TEAM_FILE) or {}

    challenger_id = str(challenger.id)
    defender_id = str(defender.id)

    cooldown_left = get_pair_cooldown_remaining(challenger_id, defender_id)
    if cooldown_left > 0:
        hours = cooldown_left // 3600
        minutes = (cooldown_left % 3600) // 60
        seconds = cooldown_left % 60
        return await send_like(
            ctx,
            f'⏳ Cặp đấu này đang hồi chiêu. Còn {hours}h {minutes}m {seconds}s nữa mới có thể đấu lại.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )

    if challenger_id not in inv:
        return await send_like(
            ctx,
            '❌ Bạn chưa có waifu nào trong inventory.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )
    if defender_id not in inv:
        return await send_like(
            ctx,
            '❌ Đối thủ chưa có waifu nào trong inventory.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )

    resolved_team_a = normalize_team_ids(challenger_id, inv, team_data, team_a)
    resolved_team_b = normalize_team_ids(defender_id, inv, team_data, team_b)

    if not resolved_team_a:
        return await send_like(
            ctx,
            '❌ Bạn chưa có team hợp lệ để khiêu chiến.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )
    if not resolved_team_b:
        return await send_like(
            ctx,
            '❌ Đối thủ chưa có team hợp lệ để khiêu chiến.',
            ephemeral=True if hasattr(ctx, 'response') else False,
        )

    luck_a = 1.0
    luck_b = 1.0
    try:
        from Commands.prayer import get_luck
        luck_a = float(get_luck(challenger.id))
    except Exception:
        pass

    try:
        from Commands.prayer import get_luck
        luck_b = float(get_luck(defender.id))
    except Exception:
        pass

    original_inv = deepcopy(inv)
    inv_working = deepcopy(inv)

    session = FightSession(
        challenger_name=challenger.name,
        defender_name=defender.name,
        challenger_id=challenger_id,
        defender_id=defender_id,
        team_a_ids=resolved_team_a,
        team_b_ids=resolved_team_b,
        inv=inv_working,
        waifu_data=waifu_data,
        luck_a=luck_a,
        luck_b=luck_b,
    )

    message = await send_like(ctx, content='⚔️ Trận chiến bắt đầu!', embed=session.render_embed())
    if message is None:
        await send_like(ctx, '❌ Không lấy được message để cập nhật trận đấu.', ephemeral=True if hasattr(ctx, 'response') else False)
        return

    # Set cooldown as soon as the match actually starts.
    mark_pair_cooldown(challenger_id, defender_id)

    while session.completed_turn() <= MAX_ROUNDS and not session.is_over():
        try:
            await session.play_round(message)
        except Exception as e:
            debug('fight loop failed:', e)
            await send_like(ctx, f'❌ Fight bị lỗi: `{e}`', ephemeral=True if hasattr(ctx, 'response') else False)
            return

    winner_side = session.get_winner_side()

    if winner_side is None:
        session.draw = True
        save_json(INV_FILE, original_inv)
        draw_text = f'Trận chiến giữa {challenger.name} và {defender.name} chưa được phân thắng bại. Đã xử hoà!'
        try:
            await edit_like(message, content=draw_text, embed=session.render_embed(), view=None)
        except Exception as e:
            debug('final draw edit failed:', e)
        return

    final_logs = session.apply_final_rewards()
    for line in final_logs:
        session.add_log(line)

    session.commit_and_sync()

    winner_id = session.side_id(winner_side)
    loser_id = challenger_id if winner_id == defender_id else defender_id
    winner_name = challenger.name if winner_id == challenger_id else defender.name
    loser_name = defender.name if loser_id == defender_id else challenger.name

    result_embed = session.render_embed()
    result_embed.color = 0x00FF00
    result_embed.add_field(
        name='Kết quả',
        value=f'🏆 **{winner_name}** chiến thắng trước **{loser_name}**!',
        inline=False,
    )

    try:
        await edit_like(message, content=None, embed=result_embed, view=None)
    except Exception as e:
        debug('final win edit failed:', e)


# ===== DEBUG SNAPSHOT =====
def debug_snapshot(user_id: str):
    inv = load_json(INV_FILE)
    waifu_data = load_json(WAIFU_FILE)
    levels = load_json(LEVEL_FILE)
    user = inv.get(user_id, {})
    out = {
        'user_id': user_id,
        'default_waifu': user.get('default_waifu'),
        'waifus': user.get('waifus', {}),
        'levels': levels.get(user_id, {}),
        'available_team': normalize_team_ids(user_id, inv, load_json(TEAM_FILE)),
        'waifu_meta': {wid: waifu_data.get(wid, {}) for wid in user.get('waifus', {}).keys()},
    }
    return out


print('Loaded fight.py!')
