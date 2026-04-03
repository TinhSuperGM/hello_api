import discord
import json
import os
import time
import asyncio
from Data import data_user
from bot_queue import paced_call, auction_signature, get_cached_signature, set_cached_signature

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


# ===== UI =====
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
        title="⚖️ BUỔI ĐẤU GIÁ MỚI HÔM NAY ⚖️",
        description=(
            f"🌹 **Tên Waifu:** {waifu_id}\n"
            f"🎖️ Rank: **{rank}**\n\n"
            f"🛞 <@{uid}> đã đăng bán **{waifu_id} của mình lên sàn đấu giá!**\n\n"
            f"💰 Giá khởi điểm: {auction['min_price']} 🪙\n"
            f"📈 Bước giá: {auction['step']} 🪙\n\n"
            f"🎙️ Giá cao nhất: **{current}** 🪙\n"
            f"🏍️ Người giữ giá: {holder}\n\n"
            f"⏳ Còn: <t:{int(auction['end_time'])}:R>\n"
        ),
        color=get_color(rank)
    )

    if "image" in waifu_data.get(waifu_id, {}):
        embed.set_image(url=waifu_data[waifu_id]["image"])

    embed.set_footer(text=f"🆔 Auction ID: {auction_id}")
    return embed


# ===== BID =====
class BidModal(discord.ui.Modal, title="Đặt số tiền bạn muốn đấu giá!"):
    amount = discord.ui.TextInput(label="Số gold muốn đặt")

    def __init__(self, auction_id):
        super().__init__()
        self.auction_id = auction_id
        self.client = None

    async def on_submit(self, interaction: discord.Interaction):
        self.client = interaction.client
        await interaction.response.send_message("⏳ Đang xử lý...", ephemeral=True)

        auctions = load_json(AUCTION_FILE)
        waifu_data = load_json(WAIFU_FILE)

        auction = auctions.get(self.auction_id)
        uid = str(interaction.user.id)

        if not auction:
            return await interaction.followup.send("❌ Sự kiện đấu giá này không tồn tại!", ephemeral=True)
        if uid == auction["seller"]:
            return await interaction.followup.send("❌ Không thể tham gia buổi đấu giá của chính mình!", ephemeral=True)
        if uid == auction.get("highest_bidder"):
            return await interaction.followup.send("❌ Bạn đang giữ giá rồi!", ephemeral=True)
        if time.time() >= auction["end_time"]:
            return await interaction.followup.send("❌ Sự kiện đấu giá này đã kết thúc!", ephemeral=True)

        try:
            bid = int(self.amount.value)
        except:
            return await interaction.followup.send("❌ Số gold đặt mua không hợp lệ!", ephemeral=True)

        current = auction.get("current_bid", 0)
        if current == 0 and bid < auction["min_price"]:
            return await interaction.followup.send("❌ Giá đặt lần này quá thấp!", ephemeral=True)
        if current != 0 and bid < current + auction["step"]:
            return await interaction.followup.send("❌ Chưa đủ số gold tối thiểu mỗi lần đặt!", ephemeral=True)
        if data_user.get_user(uid)["gold"] < bid:
            return await interaction.followup.send("❌ Không đủ gold!", ephemeral=True)

        prev_bidder = auction.get("highest_bidder")
        prev_amount = auction.get("current_bid", 0)

        if not data_user.remove_gold(uid, bid):
            return await interaction.followup.send("❌ Lỗi trừ gold!", ephemeral=True)
        if prev_bidder and prev_bidder != uid:
            data_user.add_gold(prev_bidder, prev_amount)

        auction["highest_bidder"] = uid
        auction["current_bid"] = bid
        save_json(AUCTION_FILE, auctions)

        await interaction.followup.send(f"💰 Đã đặt {bid} gold cho phiên đấu giá này!", ephemeral=True)

        asyncio.create_task(self.update_messages(auction, waifu_data))

    async def update_messages(self, auction, waifu_data):
        tasks = []
        for msg_info in auction.get("messages", []):
            channel = self.client.get_channel(int(msg_info["channel_id"]))
            if not channel:
                continue

            async def edit_message(mi=msg_info, ch=channel):
                try:
                    message = await paced_call(lambda: ch.fetch_message(int(mi["message_id"])))
                    await paced_call(lambda: message.edit(embed=build_embed(auction, waifu_data, self.auction_id), view=BidView(self.auction_id)))
                except:
                    pass

            tasks.append(edit_message())

        if tasks:
            await asyncio.gather(*tasks)


# ===== VIEW =====
class BidView(discord.ui.View):
    def __init__(self, auction_id):
        super().__init__(timeout=None)
        self.auction_id = auction_id

    @discord.ui.button(label="💰 Đặt gold đấu giá", style=discord.ButtonStyle.green, custom_id="bid_button")
    async def bid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BidModal(self.auction_id))


# ===== COMMAND LOGIC =====
async def dau_gia_logic(interaction, waifu_id: str, min_price: int, step: int):
    channels = load_channels()
    guild_id = str(interaction.guild.id)

    if guild_id not in channels or not channels[guild_id].get("auction_channel_id"):
        return await interaction.response.send_message("❌ Server chưa setup kênh!", ephemeral=True)

    waifu_data = load_json(WAIFU_FILE)
    inv = load_json(INV_FILE)
    auctions = load_json(AUCTION_FILE)
    uid = str(interaction.user.id)

    if waifu_id not in inv.get(uid, {}).get("waifus", {}):
        return await interaction.response.send_message("❌ Bạn không có waifu này!", ephemeral=True)

    rank = waifu_data.get(waifu_id, {}).get("rank")
    if rank not in ["truyen_thuyet", "toi_thuong", "limited"]:
        return await interaction.response.send_message("❌ Rank không đủ!", ephemeral=True)

    inv[uid]["waifus"].pop(waifu_id, None)

    auction_id = str(int(time.time()))
    auctions[auction_id] = {
        "waifu_id": waifu_id,
        "seller": uid,
        "min_price": min_price,
        "step": step,
        "current_bid": 0,
        "highest_bidder": None,
        "end_time": time.time() + 259200,
        "messages": []
    }

    tasks = []
    for gid, data in channels.items():
        channel_id = data.get("auction_channel_id")
        if not channel_id:
            continue

        channel = interaction.client.get_channel(channel_id)
        if not channel:
            continue

        async def post_message(gid=gid, ch=channel):
            try:
                msg = await paced_call(lambda: ch.send(embed=build_embed(auctions[auction_id], waifu_data, auction_id), view=BidView(auction_id)))
                auctions[auction_id]["messages"].append({
                    "guild_id": gid,
                    "channel_id": ch.id,
                    "message_id": msg.id
                })
                set_cached_signature(auction_id, gid, auction_signature(auctions[auction_id]))
            except:
                pass

        tasks.append(post_message())

    if tasks:
        await asyncio.gather(*tasks)

    save_json(INV_FILE, inv)
    save_json(AUCTION_FILE, auctions)

    await interaction.response.send_message("✅ Đã đăng đấu giá!", ephemeral=True)


# ===== LOOP =====
async def auction_realtime_loop(bot):
    await bot.wait_until_ready()

    while not bot.is_closed():
        auctions = load_json(AUCTION_FILE)
        waifu_data = load_json(WAIFU_FILE)
        inv = load_json(INV_FILE)

        tasks = []
        ended_auctions = []

        for auction_id, auction in auctions.items():
            now = time.time()
            if now < auction.get("end_time", 0):
                for msg_info in auction.get("messages", []):
                    channel = bot.get_channel(int(msg_info["channel_id"]))
                    if not channel:
                        continue

                    async def update_message(mi=msg_info, ch=channel, aid=auction_id):
                        try:
                            message = await paced_call(lambda: ch.fetch_message(int(mi["message_id"])))
                            await paced_call(lambda: message.edit(embed=build_embed(auction, waifu_data, aid), view=BidView(aid)))
                        except:
                            pass

                    tasks.append(update_message())
            else:
                ended_auctions.append(auction_id)

                highest = auction.get("highest_bidder")
                seller = auction.get("seller")
                waifu_id = auction.get("waifu_id")
                final_bid = auction.get("current_bid", 0)

                for msg_info in auction.get("messages", []):
                    channel = bot.get_channel(int(msg_info["channel_id"]))
                    if not channel:
                        continue

                    async def end_message(mi=msg_info, ch=channel):
                        try:
                            if highest:
                                inv.setdefault(highest, {}).setdefault("waifus", {})
                                inv[highest]["waifus"][waifu_id] = 1
                                if final_bid > 0:
                                    data_user.add_gold(seller, final_bid)

                                desc = f"<@{highest}> đã thắng và nhận **{waifu_id}** với {final_bid} gold."
                            else:
                                inv.setdefault(seller, {}).setdefault("waifus", {})
                                inv[seller]["waifus"][waifu_id] = 1
                                desc = f"Không ai đấu giá **{waifu_id}**, trả lại cho <@{seller}>."

                            embed = discord.Embed(title="🏁 KẾT THÚC ĐẤU GIÁ 🏁", description=desc, color=0x00FF00)

                            if "image" in waifu_data.get(waifu_id, {}):
                                embed.set_image(url=waifu_data[waifu_id]["image"])

                            message = await paced_call(lambda: ch.fetch_message(int(mi["message_id"])))
                            await paced_call(lambda: message.edit(embed=embed, view=None))
                        except:
                            pass

                    tasks.append(end_message())

        if ended_auctions:
            for aid in ended_auctions:
                auctions.pop(aid, None)

            save_json(AUCTION_FILE, auctions)
            save_json(INV_FILE, inv)

        if tasks:
            await asyncio.gather(*tasks)

        await asyncio.sleep(10)


# ===== SETUP =====
async def setup(bot):
    auctions = load_json(AUCTION_FILE)

    for auction_id in auctions:
        bot.add_view(BidView(auction_id))

    bot.loop.create_task(auction_realtime_loop(bot))


print("Loaded dau_gia_logic.py!")
