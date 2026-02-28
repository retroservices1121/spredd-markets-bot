import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;
const API_URL = process.env.API_URL || "http://localhost:8000";

// Proxy /api requests to the backend
app.use(
  "/api",
  createProxyMiddleware({
    target: API_URL,
    changeOrigin: true,
    timeout: 10000,
    proxyTimeout: 10000,
    onError: (err, req, res) => {
      console.error(`Proxy error: ${err.message}`);
      res.status(502).json({ detail: "Backend unavailable" });
    },
  })
);

// Also proxy the root-level platform endpoints used by the backend
for (const path of ["/polymarket", "/kalshi", "/platforms", "/markets", "/arbitrage", "/health"]) {
  app.use(
    path,
    createProxyMiddleware({
      target: API_URL,
      changeOrigin: true,
      timeout: 10000,
      proxyTimeout: 10000,
      onError: (err, req, res) => {
        console.error(`Proxy error: ${err.message}`);
        res.status(502).json({ detail: "Backend unavailable" });
      },
    })
  );
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
