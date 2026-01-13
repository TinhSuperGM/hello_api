const express = require("express");
const cors = require("cors");

const app = express();
app.use(cors());
app.use(express.json());

app.get("/", (req, res) => {
  res.json({ message: "Hello world" });
});

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    uptime: process.uptime()
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log("API running on port", PORT);
});
