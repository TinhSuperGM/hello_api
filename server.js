// ================== IMPORT ==================
const { Client, GatewayIntentBits } = require("discord.js");
const express = require("express");

// ================== CONFIG ==================
const DISCORD_TOKEN = process.env.DISCORD_TOKEN;

// map channel -> type
// ví dụ: mỗi channel update 1 loại JobID
const CHANNEL_MAP = {
  moon: process.env.CHANNEL_MOON,
  sword: process.env.CHANNEL_SWORD,
  island: process.env.CHANNEL_ISLAND,
  boss: process.env.CHANNEL_BOSS,
  haki: process.env.CHANNEL_HAKI
};

const PORT = process.env.PORT || 3000;

// ================== DATA STORE ==================
const store = {
  moon:   { jobId: "", updatedAt: null },
  sword:  { jobId: "", updatedAt: null },
  island: { jobId: "", updatedAt: null },
  boss:   { jobId: "", updatedAt: null },
  haki:   { jobId: "", updatedAt: null }
};

// ================== API ==================
const app = express();
app.use(express.json());

// Roblox đọc toàn bộ JobID
app.get("/jobid", (req, res) => {
  res.json(store);
});

// (OPTIONAL) update thủ công bằng POST
app.post("/update/:type", (req, res) => {
  const { type } = req.params;
  const { jobId } = req.body;

  if (!store[type]) {
    return res.status(400).json({ error: "Invalid type" });
  }
  if (!jobId) {
    return res.status(400).json({ error: "Invalid jobId" });
  }

  store[type].jobId = jobId;
  store[type].updatedAt = Date.now();

  console.log(`🆕 [API] ${type.toUpperCase()} = ${jobId}`);
  res.json({ success: true });
});

app.listen(PORT, () => {
  console.log("🌐 API public running on port", PORT);
});

// ================== DISCORD BOT ==================
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent
  ]
});

client.once("ready", () => {
  console.log(`✅ Bot logged in as ${client.user.tag}`);
});

// đọc embed từ nhiều channel
client.on("messageCreate", (message) => {
  if (message.author.id === client.user.id) return;
  if (!message.embeds.length) return;

  const embed = message.embeds[0];
  const jobId = embed.fields?.[2]?.value?.trim(); // field JobID

  if (!jobId) return;

  // xác định type dựa vào channel
  for (const type in CHANNEL_MAP) {
    if (message.channel.id === CHANNEL_MAP[type]) {
      if (store[type].jobId !== jobId) {
        store[type].jobId = jobId;
        store[type].updatedAt = Date.now();

        console.log(`🆕 [${type.toUpperCase()}] JobID = ${jobId}`);
      }
      break;
    }
  }
});

client.login(DISCORD_TOKEN);
