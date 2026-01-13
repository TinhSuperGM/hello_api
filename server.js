const express = require("express");
const cors = require("cors");

const app = express();

// ======================
// MIDDLEWARE
// ======================
app.use(cors());
app.use(express.json());

// ======================
// DATA STORE (RAM)
// ======================
let latestJobId = null;
let lastUpdate = null;

// ======================
// ROUTES
// ======================

// Test endpoint
app.get("/", (req, res) => {
  res.json({ message: "Hello world" });
});

// Health check
app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    uptime: process.uptime(),
    lastJobId: latestJobId,
    updatedAt: lastUpdate
  });
});

// ======================
// DISCORD WEBHOOK → API
// ======================
/*
Discord Webhook gửi POST JSON:
{
  "jobId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
*/
app.post("/webhook", (req, res) => {
  const { jobId } = req.body;

  if (!jobId || typeof jobId !== "string") {
    return res.status(400).json({
      success: false,
      error: "Invalid jobId"
    });
  }

  latestJobId = jobId;
  lastUpdate = Date.now();

  console.log("[WEBHOOK] New JobId:", jobId);

  res.json({
    success: true,
    jobId: latestJobId
  });
});

// ======================
// ROBLOX GET JOBID
// ======================
app.get("/jobid", (req, res) => {
  if (!latestJobId) {
    return res.status(404).json({
      jobId: null,
      message: "No JobId available yet"
    });
  }

  res.json({
    jobId: latestJobId,
    updatedAt: lastUpdate
  });
});

// ======================
// START SERVER
// ======================
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log("API running on port", PORT);
});
