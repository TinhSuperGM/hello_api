import discord
import json
import os
import time
import asyncio
from Data import data_user
from bot_queue import paced_call, auction_signature, set_cached_signature

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
AUCTION_FILE = os.path.join(BASE_DIR, "Data", "auction.json")
CHANNEL_FILE = os.path.join(BASE_DIR, "Data", "auction_channels.json")


# ===== LOAD/SAVE =====
def load_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_channels():
    return load_json(CHANNEL_FILE)


# ===== EMBED =====
def get_color(rank):
    return {
        "truyen_thuyet": 0x00FFFF,
        "toi_thuong": 0xFF0000,
        "limited": 0xFF00FF
    }.get(rank, 0xFFD700)


def build_embed(auction, waifu_data, auction_id=None):
    waifu_id = auction["waifu_id"]
    uid = auction["seller"]
    rank = waifu_data.get(waifu_id, {}).get("rank")

    current = auction.get("current_bid", 0)
    highest = auction.get("highest_bidder")
    holder = f"<@{highest}>" if highest else "Chưa có ai"

    embed = discord.Embed(
        title="⚖️ BUỔI ĐẤU GIÁ ⚖️",
        description=(
            f"🌹 Waifu: **{waifu_id}**\n"
            f"🎖️ Rank: **{rank}**\n\n"
            f"👤 Seller: <@{uid}>\n\n"
            f"💰 Giá: {current} 🪙\n"
            f"🏆 Người giữ: {holder}\n\n"
            f"⏳ <t:{int(auction['end_time'])}:R>"
        ),
        color=get_color(rank)
    )

    if "image" in waifu_data.get(waifu_id, {}):
        embed.set_image(url=waifu_data[waifu_id]["image"])

    return embed


# ===== BID =====
class BidModal(discord.ui.Modal, title="Đặt giá"):
    amount = discord.ui.TextInput(label="Gold")

    def __init__(self, auction_id):
        super().__init__()
        self.auction_id = auction_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        auctions = load_json(AUCTION_FILE)
        auction = auctions.get(self.auction_id)
        uid = str(interaction.user.id)

        if not auction:
            return await interaction.followup.send("❌ Không tồn tại")

        try:
            bid = int(self.amount.value)
        except:
            return await interaction.followup.send("❌ Sai số")

        current = auction.get("current_bid", 0)

        if bid <= current:
            return await interaction.followup.send("❌ Giá thấp")

        if data_user.get_user(uid)["gold"] < bid:
            return await interaction.followup.send("❌ Không đủ gold")

        prev = auction.get("highest_bidder")
        prev_bid = auction.get("current_bid", 0)

        if not data_user.remove_gold(uid, bid):
            return await interaction.followup.send("❌ Lỗi trừ gold")

        if prev and prev != uid:
            data_user.add_gold(prev, prev_bid)

        auction["highest_bidder"] = uid
        auction["current_bid"] = bid

        save_json(AUCTION_FILE, auctions)

        await interaction.followup.send(f"✅ Bid {bid} gold")


# ===== VIEW =====
class BidView(discord.ui.View):
    def __init__(self, auction_id):
        super().__init__(timeout=None)
        self.auction_id = auction_id

    @discord.ui.button(label="Đấu giá", style=discord.ButtonStyle.green)
    async def bid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BidModal(self.auction_id))


# ===== CREATE AUCTION =====
async def dau_gia_logic(interaction, waifu_id: str, min_price: int, step: int):
    inv = load_json(INV_FILE)
    auctions = load_json(AUCTION_FILE)

    uid = str(interaction.user.id)

    if waifu_id not in inv.get(uid, {}).get("waifus", {}):
        return await interaction.response.send_message("❌ Không có waifu", ephemeral=True)

    # 👉 LƯU LOVE
    love = inv[uid]["waifus"].pop(waifu_id)

    auction_id = str(int(time.time()))
    auctions[auction_id] = {
        "waifu_id": waifu_id,
        "seller": uid,
        "love": love,  # 🔥 FIX QUAN TRỌNG
        "min_price": min_price,
        "step": step,
        "current_bid": 0,
        "highest_bidder": None,
        "end_time": time.time() + 86400,
        "messages": []
    }

    save_json(INV_FILE, inv)
    save_json(AUCTION_FILE, auctions)

    await interaction.response.send_message("✅ Đã tạo đấu giá")


# ===== LOOP =====
async def auction_realtime_loop(bot):
    await bot.wait_until_ready()

    while not bot.is_closed():
        auctions = load_json(AUCTION_FILE)
        inv = load_json(INV_FILE)

        remove = []

        for aid, a in auctions.items():
            if time.time() < a["end_time"]:
                continue

            waifu = a["waifu_id"]
            love = a.get("love", 1)
            seller = a["seller"]
            winner = a.get("highest_bidder")

            if winner:
                inv.setdefault(winner, {}).setdefault("waifus", {})
                inv[winner]["waifus"][waifu] = love
                data_user.add_gold(seller, a["current_bid"])
            else:
                inv.setdefault(seller, {}).setdefault("waifus", {})
                inv[seller]["waifus"][waifu] = love

            remove.append(aid)

        for aid in remove:
            auctions.pop(aid, None)

        save_json(INV_FILE, inv)
        save_json(AUCTION_FILE, auctions)

        await asyncio.sleep(10)


# ===== SETUP =====
async def setup(bot):
    bot.loop.create_task(auction_realtime_loop(bot))

print("Loaded dau_gia FIXED!")
