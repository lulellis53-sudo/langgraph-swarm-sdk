/**
 * Xeon MCP Server — High-Throughput Remote Compute Worker
 * Runs on Dual Xeon Broadwell-EP (32GB RAM)
 * Source: DeepResearch.md Part IX (Directive B).
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import express from "express";
import { Pool } from "pg";
import { chromium, Browser, BrowserContext } from "playwright";
import os from "os";

// 1. PostgreSQL Connection Pool on Xeon Node
const pgPool = new Pool({
  host: process.env.PGHOST || "localhost",
  port: parseInt(process.env.PGPORT || "5432"),
  user: process.env.PGUSER || "postgres",
  password: process.env.PGPASSWORD || "postgres",
  database: process.env.PGDATABASE || "swarm_rag",
  max: 30, // Exploit Xeon high concurrency
  idleTimeoutMillis: 30000,
});

// 2. Playwright Headless Browser Pool
class BrowserFarm {
  private browser: Browser | null = null;

  async init() {
    if (!this.browser) {
      this.browser = await chromium.launch({
        headless: true,
        args: [
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-dev-shm-usage", // Exploit 32GB system RAM instead of /dev/shm limits
          "--disable-gpu",
          "--no-zygote",
        ],
      });
    }
    return this.browser;
  }

  async scrapeUrl(
    url: string,
    waitSelector?: string,
  ): Promise<{ title: string; content: string }> {
    const browser = await this.init();
    const context: BrowserContext = await browser.newContext({
      userAgent:
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.8037.97 Safari/537.36",
    });

    // Abort image and font requests to save network & compute
    await context.route(
      "**/*.{png,jpg,jpeg,webp,svg,woff,woff2,ttf,gif}",
      (route) => route.abort(),
    );

    const page = await context.newPage();
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
      if (waitSelector) {
        await page
          .waitForSelector(waitSelector, { timeout: 5000 })
          .catch(() => {});
      }
      const title = await page.title();
      const content = await page.evaluate(() => {
        // Remove scripts, styles, and navigational junk
        const scripts = document.querySelectorAll(
          "script, style, nav, footer, noscript, iframe",
        );
        scripts.forEach((s) => s.remove());

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "xeon_scrape_web",
        description:
          "Scrape single web page using remote headless Chromium on Xeon node.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "URL to scrape" },
            wait_selector: {
              type: "string",
              description: "Optional CSS selector to wait for",
            },
          },
          required: ["url"],
        },
      },
      {
        name: "xeon_pgvector_query",
        description:
          "Execute high-speed HNSW ANN search against remote pgvector on Xeon node.",
        inputSchema: {
          type: "object",
          properties: {
            query_vector: {
              type: "array",
              items: { type: "number" },
              description: "Embedding vector",
            },
            k: {
              type: "number",
              description: "Top-k nearest neighbors",
              default: 5,
            },
            collection: {
              type: "string",
              description: "Collection/table name",
              default: "embeddings",
            },
          },
          required: ["query_vector"],
        },
      },
      {
        name: "xeon_sql_query",
        description:
          "Execute analytical SQL query against remote database on Xeon node.",
        inputSchema: {
          type: "object",
          properties: {
            sql: { type: "string", description: "SQL query statement" },
            params: {
              type: "array",
              items: {},
              description: "Query parameters",
            },
          },
          required: ["sql"],
        },
      },
      {
        name: "xeon_system_telemetry",
        description:
          "Get real-time CPU, RAM, and load telemetry from Xeon server.",
        inputSchema: { type: "object", properties: {} },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "xeon_scrape_web": {
        const { url, wait_selector } = args as {
          url: string;
          wait_selector?: string;
        };
        const result = await farm.scrapeUrl(url, wait_selector);
        return {
          content: [
            { type: "text" as const, text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      case "xeon_pgvector_query": {
        const {
          query_vector,
          k = 5,
          collection = "embeddings",
        } = args as {
          query_vector: number[];
          k?: number;
          collection?: string;
        };
        const vecStr = `[${query_vector.join(",")}]`;
        const res = await pgPool.query(
          `SELECT id, content, metadata, 1 - (embedding <=> $1) AS cosine_similarity
           FROM ${collection}
           ORDER BY embedding <=> $1
           LIMIT $2;`,
          [vecStr, k],
        );
        return {
          content: [
            { type: "text" as const, text: JSON.stringify(res.rows, null, 2) },
          ],
        };
      }

      case "xeon_sql_query": {
        const { sql, params = [] } = args as { sql: string; params?: unknown[] };
        const res = await pgPool.query(sql, params);
        return {
          content: [
            { type: "text" as const, text: JSON.stringify(res.rows, null, 2) },
          ],
        };
      }

      case "xeon_system_telemetry": {
        const totalMem = os.totalmem();
        const freeMem = os.freemem();
        const telemetry = {
          hostname: os.hostname(),
          platform: os.platform(),
          cpus: os.cpus().length,
          loadavg: os.loadavg(),
          total_memory_gb: (totalMem / 1024 ** 3).toFixed(2),
          free_memory_gb: (freeMem / 1024 ** 3).toFixed(2),
          used_memory_pct:
            (((totalMem - freeMem) / totalMem) * 100).toFixed(1) + "%",
        };
        return {
          content: [
            { type: "text" as const, text: JSON.stringify(telemetry, null, 2) },
          ],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      isError: true,
      content: [
        {
          type: "text" as const,
          text: `Xeon Tool Error [${name}]: ${message}`,
        },
      ],
    };
  }
});

// 4. Transport Setup (Express SSE on port 8080)
const app = express();
let transport: SSEServerTransport | undefined;

app.get("/sse", async (_req, res) => {
  transport = new SSEServerTransport("/message", res);
  await server.connect(transport);
});

app.post("/message", async (req, res) => {
  if (transport) {
    await transport.handlePostMessage(req, res);
  } else {
    res.status(400).send("Transport not initialized");
  }
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
  console.log(`Xeon MCP Server listening on http://0.0.0.0:${PORT}/sse`);
});

        return document.body.innerText || "";
      });
      return { title, content: content.trim().replace(/\n{3,}/g, "\n\n") };
    } finally {
      await context.close();
    }
  }
}

const farm = new BrowserFarm();

// 3. Initialize MCP Server
const server = new Server(
  { name: "xeon-lan-worker", version: "1.0.0" },
  { capabilities: { tools: {} } },
);
