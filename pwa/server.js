import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;
const API_URL = process.env.API_URL || "http://localhost:8000";

console.log(`[config] API_URL = ${API_URL}`);
console.log(`[config] PORT = ${PORT}`);

// Debug endpoint to verify server is working
app.get("/_debug", (req, res) => {
  res.json({ api_url: API_URL, port: PORT, status: "ok" });
});

// Request logger for /api routes
app.use("/api", (req, res, next) => {
  console.log(`[proxy] ${req.method} ${req.originalUrl} → ${API_URL}${req.originalUrl}`);
  next();
});

// Proxy /api requests to the backend
const apiProxy = createProxyMiddleware({
  target: API_URL,
  changeOrigin: true,
  timeout: 15000,
  proxyTimeout: 15000,
  on: {
    proxyReq: (proxyReq, req) => {
      console.log(`[proxy] Forwarding: ${req.method} ${req.originalUrl}`);
    },
    proxyRes: (proxyRes, req) => {
      console.log(`[proxy] Response: ${proxyRes.statusCode} for ${req.originalUrl}`);
    },
    error: (err, req, res) => {
      console.error(`[proxy] Error: ${err.message} for ${req.originalUrl}`);
      res.status(502).json({ detail: "Backend unavailable", error: err.message });
    },
  },
});

app.use("/api", apiProxy);

// Also proxy the root-level platform endpoints used by the backend
const platformProxy = createProxyMiddleware({
  target: API_URL,
  changeOrigin: true,
  timeout: 15000,
  proxyTimeout: 15000,
  on: {
    error: (err, req, res) => {
      console.error(`[proxy] Error: ${err.message}`);
      res.status(502).json({ detail: "Backend unavailable" });
    },
  },
});

for (const path of ["/polymarket", "/kalshi", "/platforms", "/arbitrage", "/health"]) {
  app.use(path, platformProxy);
}

// Serve static files from dist/
app.use(express.static(join(__dirname, "dist")));

// SPA fallback — serve index.html for all other routes
app.get("*", (req, res) => {
  res.sendFile(join(__dirname, "dist", "index.html"));
});

app.listen(PORT, () => {
  console.log(`PWA server running on port ${PORT}`);
  console.log(`API proxy → ${API_URL}`);
});
