prefix.py:
from __future__ import annotations

import asyncio
import shlex
from typing import Optional

import discord

from Commands.bag import bag_logic
from Commands.baucua import baucua_logic
from Commands.code import code_logic
from Commands.coinflip import coinflip_logic
from Commands.couple import (
    couple_cancel_logic,
    couple_gift_logic,
    couple_info_logic,
    couple_logic,
    couple_release_logic,
)
from Commands.daily import daily_logic
from Commands.dau_gia import dau_gia_logic
from Commands.gift_waifu_ad import gift_waifu_ad_logic
from Commands.give import gift_logic
from Commands.gold import gold_logic
from Commands.huy_dau_gia import huy_dau_gia_logic
from Commands.roll_waifu import roll_waifu_logic
from Commands.select_waifu import select_waifu_logic
from Commands.sell import sell_logic
from Commands.setup import setup_channel_logic
from Commands.shop import send_shop_embed_logic
from Commands.use import use_logic
from Commands.view_waifu import view_waifu_logic
from Commands.waifu_list import waifu_list_run
from Commands.work import work_run
from Commands.help import help_prefix
from Commands.profile import get_profile_embed
from Commands.prayer import prayer_logic
from Commands.fight import fight_logic
from Commands.team import team_logic


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _parse_mention_id(token: str) -> Optional[int]:
    if not token:
        return None
    token = token.strip()
    if token.startswith("<@") and token.endswith(">"):
        token = token[2:-1]
        if token.startswith("!"):
            token = token[1:]
    if token.startswith("<#") and token.endswith(">"):
        token = token[2:-1]
    try:
        return int(token)
    except Exception:
        return None


async def _resolve_user(bot, message: discord.Message, token: Optional[str]) -> Optional[discord.abc.User]:
    if not token:
        return None

    uid = _parse_mention_id(token)
    if uid is None:
        return None

    if message.guild:
        member = message.guild.get_member(uid)
        if member:
            return member

    user = bot.get_user(uid)
    if user:
        return user

    try:
        return await bot.fetch_user(uid)
    except Exception:
        return None


async def _resolve_replied_user(message: discord.Message) -> Optional[discord.abc.User]:
    if not message.reference:
        return None

    try:
        if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
            return message.reference.resolved.author

        if message.reference.message_id:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            return ref_msg.author
    except Exception:
        return None

    return None


async def _smart_target(
    bot,
    message: discord.Message,
    args,
    *,
    fallback_author: bool = True,
):
    """
    Ưu tiên:
    1) mention trong message
    2) người đang được reply
    3) token trong args (mention / ID)
    4) fallback về author hoặc None
    """
    if message.mentions:
        return message.mentions[0]

    replied = await _resolve_replied_user(message)
    if replied:
        return replied

    for token in args or []:
        user = await _resolve_user(bot, message, token)
        if user:
            return user

    return message.author if fallback_author else None


def _resolve_channel(message: discord.Message, token: Optional[str]) -> Optional[discord.abc.GuildChannel]:
    if not token or not message.guild:
        return None
    cid = _parse_mention_id(token)
    if cid is None:
        return None
    return message.guild.get_channel(cid)


class _PrefixResponse:
    def __init__(self, ctx: "PrefixContext"):
        self.ctx = ctx
        self.last_message: Optional[discord.Message] = None

    async def send_message(self, *args, **kwargs):
        kwargs.pop("ephemeral", None)
        self.last_message = await self.ctx.channel.send(*args, **kwargs)
        return self.last_message

    async def edit_message(self, *args, **kwargs):
        if not self.last_message:
            raise RuntimeError("No message to edit")
        return await self.last_message.edit(*args, **kwargs)

    async def defer(self, *args, **kwargs):
        return None

    async def send_modal(self, modal):
        raise RuntimeError("Modal không hỗ trợ trong prefix command")


class _PrefixFollowup:
    def __init__(self, ctx: "PrefixContext"):
        self.ctx = ctx

    async def send(self, *args, **kwargs):
        kwargs.pop("ephemeral", None)
        return await self.ctx.channel.send(*args, **kwargs)


class PrefixContext:
    def __init__(self, bot: discord.Client, message: discord.Message):
        self.bot = bot
        self.client = bot
        self.message = message
        self.user = message.author
        self.author = message.author
        self.guild = message.guild
        self.channel = message.channel
        self.response = _PrefixResponse(self)
        self.followup = _PrefixFollowup(self)

    async def original_response(self):
        return self.response.last_message

    async def send(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)


async def _send_embed_like(ctx: PrefixContext, embed_data: dict):
    embed = discord.Embed(
        title=embed_data.get("title", ""),
        description=embed_data.get("description", ""),
        color=discord.Color.pink(),
    )
    image = embed_data.get("image")
    footer = embed_data.get("footer")
    if image:
        embed.set_image(url=image)
    if footer:
        embed.set_footer(text=footer)
    return await ctx.channel.send(embed=embed)


async def setup(bot):
    """
    Install the prefix listener.
    """
    if getattr(bot, "_prefix_listener_ready", False):
        return
    bot._prefix_listener_ready = True

    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        if not message.content.startswith("."):
            return

        try:
            parts = shlex.split(message.content[1:])
        except ValueError:
            return

        if not parts:
            return

        raw_name = _normalize_name(parts[0])
        args = parts[1:]
        ctx = PrefixContext(bot, message)

        async def reply(msg, ephemeral=False):
            return await ctx.response.send_message(msg, ephemeral=ephemeral)

        async def reply_embed(embed_data):
            return await _send_embed_like(ctx, embed_data)

        # ===== alias map =====
        aliases = {
            "setup": "setup",
            "gold": "gold",
            "daily": "daily",
            "work": "work",
            "roll-waifu": "roll-waifu",
            "select-waifu": "select-waifu",
            "waifu-list": "waifu-list",
            "view-waifu": "view-waifu",
            "bag": "bag",
            "shop": "shop",
            "use": "use",
            "sell": "sell",
            "give": "give",
            "couple": "couple",
            "couple-release": "couple-release",
            "couple-cancel": "couple-cancel",
            "couple-info": "couple-info",
            "couple-gift": "couple-gift",
            "coinflip": "coinflip",
            "baucua": "baucua",
            "code": "code",
            "dau-gia": "dau-gia",
            "huy-dau-gia": "huy-dau-gia",
            "gift-waifu-ad": "gift-waifu-ad",
            "help": "help",
            "profile": "profile",
            # 🔥 short alias
            "bc": "baucua",
            "bau": "baucua",
            "cf": "coinflip",
            "wl": "waifu-list",
            "vw": "view-waifu",
            "rw": "roll-waifu",
            "dg": "dau-gia",
            "hdg": "huy-dau-gia",
            "cp": "couple",
            "cpr": "couple-release",
            "cpc": "couple-cancel",
            "cpi": "couple-info",
            "cpg": "couple-gift",
            "gwa": "gift-waifu-ad",
            "h": "help",
            "s": "sell",
            "gift": "give",
            "coin": "coinflip",
            "ws": "select-waifu",
            "me": "profile",
            "pf": "profile",
            "prayer": "prayer",
            "pray": "prayer",
            "team": "team",
            "fight": "fight",
        }

        # ===== SMART PARSER =====
        cmd = None
        used_len = 1

        # thử 3 từ → 2 từ → 1 từ
        for i in (3, 2, 1):
            if len(parts) >= i:
                name = _normalize_name("-".join(parts[:i]))
                if name in aliases:
                    cmd = aliases[name]
                    used_len = i
                    break

        if cmd is None:
            return

        args = parts[used_len:]

        # ===== dispatch =====
        try:
            if cmd == "setup":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .setup <auction|ranking> <channel_id>")
                ch = _parse_mention_id(args[1])
                channel_id = str(ch) if ch is not None else args[1]
                return await setup_channel_logic(ctx, args[0], channel_id)

            if cmd == "gold":
                target = await _smart_target(bot, message, args, fallback_author=True)
                return await gold_logic(ctx, target)

            if cmd == "daily":
                return await daily_logic(ctx)

            if cmd == "work":
                return await work_run(ctx)

            if cmd == "roll-waifu":
                if not args:
                    return await reply("❌ Cú pháp: .roll-waifu <free|200|500|1000|2000>")
                return await roll_waifu_logic(ctx, args[0])

            if cmd == "select-waifu":
                if not args:
                    return await reply("❌ Cú pháp: .select-waifu <waifu_id>")
                return await select_waifu_logic(ctx, args[0])

            if cmd == "waifu-list":
                target = None
                if args or message.mentions or message.reference:
                    target = await _smart_target(bot, message, args, fallback_author=False)
                return await waifu_list_run(ctx, target)

            if cmd == "view-waifu":
                if not args:
                    return await reply("❌ Cú pháp: .view-waifu <waifu_id>")

                # Hỗ trợ thêm: .view-waifu @user <waifu_id>
                # Không phá cú pháp cũ .view-waifu <waifu_id>
                if message.mentions and len(args) >= 2:
                    return await view_waifu_logic(message.mentions[0], reply, reply_embed, args[1])

                return await view_waifu_logic(message.author, reply, reply_embed, args[0])

            if cmd == "bag":
                target = None

                if message.mentions:
                    target = message.mentions[0]
                elif args:
                    target = await _resolve_user(bot, message, args[0])
                elif message.reference:
                    ref = message.reference.resolved
                    if ref:
                        target = ref.author

                return await bag_logic(ctx, target)
            if cmd == "shop":
                if not args:
                    return await reply("❌ Cú pháp: .shop <channel_id>")
                ch = _parse_mention_id(args[0])
                channel_id = str(ch) if ch is not None else args[0]
                return await send_shop_embed_logic(ctx, channel_id)

            if cmd == "use":
                waifu_id = None
                item_id = None
                qty = 1

                if not args:
                    return await reply("❌ Cú pháp: .use <waifu_id>|item <item_id> [qty]")

                if args[0].lower() in {"waifu", "item"}:
                    mode = args[0].lower()
                    if mode == "waifu":
                        if len(args) < 2:
                            return await reply("❌ Cú pháp: .use waifu <waifu_id>")
                        waifu_id = args[1]
                    else:
                        if len(args) < 2:
                            return await reply("❌ Cú pháp: .use item <item_id> [qty]")
                        item_id = args[1]
                        if len(args) >= 3:
                            qty = int(args[2])
                else:
                    candidate = args[0]
                    if len(args) >= 2 and args[1].isdigit():
                        item_id = candidate
                        qty = int(args[1])
                    else:
                        waifu_id = candidate
                return await use_logic(message.author, reply, waifu_id, item_id, qty)

            if cmd == "sell":
                if not args:
                    return await reply("❌ Cú pháp: .sell <waifu_id> [bag|collection] [amount]")
                waifu_id = args[0]
                source = None
                amount = 1
                if len(args) >= 2:
                    if args[1].lower() in {"bag", "collection"}:
                        source = args[1].lower()
                        if len(args) >= 3:
                            amount = int(args[2])
                    elif args[1].isdigit():
                        amount = int(args[1])
                return await sell_logic(ctx, waifu_id, source, amount)

            if cmd == "give":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .give <gold|waifu> <user> <amount>")
                type_ = args[0]
                target = await _smart_target(bot, message, args[1:], fallback_author=False)
                if target is None:
                    return await reply("❌ Không tìm thấy người nhận.")
                amount = None
                waifu_id = None
                if type_ == "gold":
                    if len(args) < 3:
                        return await reply("❌ Cú pháp: .give gold <user> <amount>")
                    amount = int(args[2])
                elif type_ == "waifu":
                    if len(args) < 3:
                        return await reply("❌ Cú pháp: .give waifu <user> <waifu_id>")
                    waifu_id = args[2]
                else:
                    return await reply("❌ Type phải là gold hoặc waifu.")
                return await gift_logic(ctx, type_, target, amount, waifu_id)

            if cmd == "couple":
                if not args:
                    return await reply("❌ Cú pháp: .couple <user> | .couple release | .couple cancel | .couple info | .couple gift <rose|cake>")
                sub = _normalize_name(args[0])

                if sub == "release":
                    return await couple_release_logic(bot, ctx)
                if sub == "cancel":
                    return await couple_cancel_logic(ctx)
                if sub == "info":
                    return await couple_info_logic(ctx)
                if sub == "gift":
                    if len(args) < 2:
                        return await reply("❌ Cú pháp: .couple gift <rose|cake>")
                    return await couple_gift_logic(ctx, args[1])

                target = await _smart_target(bot, message, args, fallback_author=False)
                if target is None:
                    return await reply("❌ Không tìm thấy người dùng.")
                return await couple_logic(bot, ctx, target)

            if cmd == "couple-release":
                return await couple_release_logic(bot, ctx)

            if cmd == "couple-cancel":
                return await couple_cancel_logic(ctx)

            if cmd == "couple-info":
                return await couple_info_logic(ctx)

            if cmd == "couple-gift":
                if not args:
                    return await reply("❌ Cú pháp: .couple-gift <rose|cake>")
                return await couple_gift_logic(ctx, args[0])

            if cmd == "coinflip":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .coinflip <ngua|sap> <amount>")
                return await coinflip_logic(ctx, args[0], int(args[1]))

            if cmd == "baucua":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .baucua <nai|bau|ga|ca|cua|tom> <amount>")
                return await baucua_logic(ctx, args[0], int(args[1]))

            if cmd == "code":
                if not args:
                    return await reply("❌ Cú pháp: .code <mã>")
                return await code_logic(ctx, args[0])

            if cmd == "dau-gia":
                if len(args) < 3:
                    return await reply("❌ Cú pháp: .dau-gia <waifu_id> <min_price> <step>")
                return await dau_gia_logic(ctx, args[0], int(args[1]), int(args[2]))

            if cmd == "huy-dau-gia":
                if not args:
                    return await reply("❌ Cú pháp: .huy-dau-gia <auction_id>")
                return await huy_dau_gia_logic(ctx, args[0])

            if cmd == "gift-waifu-ad":
                if not args:
                    return await reply("❌ Cú pháp: .gift-waifu-ad <waifu_id> [user]")
                target = None
                if len(args) >= 2:
                    target = await _smart_target(bot, message, args[1:], fallback_author=False)
                return await gift_waifu_ad_logic(ctx, args[0], target)

            if cmd == "profile":
                target = await _smart_target(bot, message, args, fallback_author=True)
                embed = get_profile_embed(bot, target)
                return await ctx.send(embed=embed)
            if cmd == "prayer":
                return await prayer_logic(ctx)

            if cmd == "help":
                await help_prefix(message)
                return
            if cmd == "fight":
                await fight_logic(ctx, opponent)
            # ===== TEAM =====
            if cmd == "team":
                if len(args) < 2:
                    return await message.channel.send(
                        "❌ Dùng: .team waifu1 [waifu2] [waifu3]"
                    )
    
                w1 = args[1]
                w2 = args[2] if len(args) > 2 else None
                w3 = args[3] if len(args) > 3 else None

                await team_logic(message, [w1, w2, w3])

        except ValueError:
            return await reply("❌ Tham số số không hợp lệ.")
        except Exception as exc:
            print(f"[PREFIX ERROR] {cmd}: {exc}")
            return await reply("❌ Có lỗi khi xử lý lệnh.")

    bot.add_listener(on_message, "on_message")
fight.py:
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
team.py:
from __future__ import annotations

import json
import os
from typing import Optional, Sequence

import discord

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
TEAM_FILE = os.path.join(BASE_DIR, "Data", "team.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
LEVEL_FILE = os.path.join(BASE_DIR, "Data", "level.json")


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_user_obj(ctx):
    return ctx.user if hasattr(ctx, "user") else ctx.author


async def send_like(ctx, content: str, *, embed: Optional[discord.Embed] = None, ephemeral: bool = False):
    if hasattr(ctx, "response") and hasattr(ctx.response, "send_message"):
        is_done = getattr(ctx.response, "is_done", None)
        if callable(is_done) and is_done():
            if hasattr(ctx, "followup") and hasattr(ctx.followup, "send"):
                return await ctx.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            return await ctx.send(content=content, embed=embed)

        await ctx.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        try:
            return await ctx.original_response()
        except Exception:
            return None

    return await ctx.send(content=content, embed=embed)


def normalize_team_input(team_input: Optional[Sequence[str] | str]) -> list[str]:
    if team_input is None:
        return []

    if isinstance(team_input, str):
        raw = team_input.replace(",", " ").split()
        return [x.strip() for x in raw if x.strip()]

    out: list[str] = []
    for item in team_input:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def get_level(level_data: dict, user_id: str, waifu_id: str) -> int:
    return int(level_data.get(user_id, {}).get(waifu_id, 0))


def get_love(inv: dict, user_id: str, waifu_id: str) -> int:
    user_inv = inv.get(user_id, {})
    waifus = user_inv.get("waifus", {})

    value = waifus.get(waifu_id, 0)
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return int(value.get("love", 0))
    return 0


def get_rank(waifu_data: dict, waifu_id: str) -> str:
    return str(waifu_data.get(waifu_id, {}).get("rank", "thuong")).lower()


def get_current_team(team_data: dict, user_id: str) -> list[str]:
    raw = team_data.get(user_id)
    if not raw:
        return []

    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]

    if isinstance(raw, dict):
        for key in ("team", "waifus", "list", "members"):
            val = raw.get(key)
            if isinstance(val, list):
                return [str(x) for x in val if str(x).strip()]

    return []


def set_team(team_data: dict, user_id: str, team_ids: list[str]) -> None:
    team_data[user_id] = team_ids


def clear_team(team_data: dict, user_id: str) -> None:
    if user_id in team_data:
        team_data.pop(user_id, None)


def build_team_embed_for_user(
    user_id: str,
    user_name: str,
    team_ids: list[str],
    inv: dict,
    waifu_data: dict,
    level_data: dict,
):
    embed = discord.Embed(
        title=f"🛡️ Team của {user_name}",
        color=discord.Color.blurple(),
    )

    if not team_ids:
        embed.description = "Chưa có waifu nào trong team."
        return embed

    desc_lines = []
    for idx, wid in enumerate(team_ids, start=1):
        rank = get_rank(waifu_data, wid)
        love = get_love(inv, user_id, wid)
        lv = get_level(level_data, user_id, wid)

        desc_lines.append(
            f"**{idx}. {wid}**\n"
            f"Rank: `{rank}` | Love: `{love}` | Lv: `{lv}`"
        )

    embed.description = "\n\n".join(desc_lines)
    return embed


async def team_logic(ctx, team_input: Optional[Sequence[str] | str] = None):
    """
    Dùng từ slash.py hoặc prefix.py.

    Ví dụ:
        await team_logic(interaction, ["zero_two", "rem"])
        await team_logic(ctx, "zero_two rem")
        await team_logic(ctx, ["clear"])
        await team_logic(ctx)  # xem team hiện tại
    """
    user = get_user_obj(ctx)
    user_id = str(user.id)

    inv = load_json(INV_FILE)
    team_data = load_json(TEAM_FILE)
    waifu_data = load_json(WAIFU_FILE)
    level_data = load_json(LEVEL_FILE)

    if user_id not in inv:
        inv[user_id] = {"waifus": {}, "bag": {}, "bag_item": {}, "default_waifu": None}

    current_team = get_current_team(team_data, user_id)
    tokens = normalize_team_input(team_input)

    # ===== SHOW TEAM =====
    if not tokens:
        embed = build_team_embed_for_user(user_id, user.name, current_team, inv, waifu_data, level_data)
        return await send_like(ctx, content="📋 Team hiện tại của bạn:", embed=embed, ephemeral=False)

    # ===== CLEAR TEAM =====
    if len(tokens) == 1 and tokens[0].lower() in {"clear", "reset", "remove", "xoa", "xoá"}:
        clear_team(team_data, user_id)
        save_json(TEAM_FILE, team_data)

        embed = discord.Embed(
            title=f"🧹 Team của {user.name} đã được xoá",
            description="Bạn chưa có waifu nào trong team.",
            color=discord.Color.orange(),
        )
        return await send_like(ctx, content="✅ Đã xoá team.", embed=embed, ephemeral=True)

    # ===== VALIDATE =====
    if len(tokens) > 3:
        return await send_like(
            ctx,
            "❌ Team chỉ được tối đa 3 waifu.",
            ephemeral=True
        )

    # unique preserve order
    seen = set()
    team_ids: list[str] = []
    for wid in tokens:
        wid = wid.strip()
        if wid in seen:
            continue
        seen.add(wid)
        team_ids.append(wid)

    if not team_ids:
        return await send_like(ctx, "❌ Team không hợp lệ.", ephemeral=True)

    owned = inv.get(user_id, {}).get("waifus", {})
    missing = [wid for wid in team_ids if wid not in owned]
    if missing:
        return await send_like(
            ctx,
            f"❌ Bạn không có các waifu này trong inventory: `{', '.join(missing)}`",
            ephemeral=True
        )

    set_team(team_data, user_id, team_ids)
    save_json(TEAM_FILE, team_data)

    embed = build_team_embed_for_user(user_id, user.name, team_ids, inv, waifu_data, level_data)
    embed.title = f"🛡️ Team mới của {user.name}"
    embed.color = discord.Color.green()
    embed.set_footer(text="Team đã được lưu vào team.json")

    return await send_like(
        ctx,
        content=f"✅ Đã cập nhật team gồm **{len(team_ids)}** waifu.",
        embed=embed,
        ephemeral=True
    )


def get_team(user_id: str) -> list[str]:
    team_data = load_json(TEAM_FILE)
    return get_current_team(team_data, user_id)


def set_team_file(user_id: str, team_ids: Sequence[str]) -> None:
    team_data = load_json(TEAM_FILE)
    set_team(team_data, user_id, list(team_ids))
    save_json(TEAM_FILE, team_data)


def clear_team_file(user_id: str) -> None:
    team_data = load_json(TEAM_FILE)
    clear_team(team_data, user_id)
    save_json(TEAM_FILE, team_data)


print("Loaded team.py!"),
