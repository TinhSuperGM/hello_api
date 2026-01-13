// ================== IMPORT ==================
const { Client, GatewayIntentBits } = require("discord.js");
const express = require("express");

// ================== CONFIG ==================
const DISCORD_TOKEN = process.env.DISCORD_TOKEN;
const CHANNEL_ID = process.env.CHANNEL_ID;
const PORT = process.env.PORT || 3000;

// ================== API ==================
let latestJobId = null;

const app = express();
app.use(express.json());

// API cho Roblox đọc
app.get("/jobid", (req, res) => {
  res.json({
    jobId: latestJobId,
    updatedAt: Date.now()
  });
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

client.on("messageCreate", (message) => {
  // chỉ bỏ bot của chính mình
  if (message.author.id === client.user.id) return;
  if (message.channel.id !== CHANNEL_ID) return;
  if (!message.embeds.length) return;

  const embed = message.embeds[0];
  const jobId = embed.fields?.[2]?.value?.trim(); // field JobId

  if (!jobId) return;

  if (jobId !== latestJobId) {
    latestJobId = jobId; // 🔥 GHI ĐÈ
    console.log("🆕 JobId cập nhật:", latestJobId);
  }
});

client.login(DISCORD_TOKEN);
