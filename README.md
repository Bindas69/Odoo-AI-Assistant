# 🤖 AI Inventory Assistant — WhatsApp Stock & Pricing Agent for Odoo

**An AI agent that answers customer WhatsApp questions about product stock
and pricing, grounded entirely in live Odoo ERP data — never guessing, never
inventing an answer.**

![Status](https://img.shields.io/badge/Status-MVP%20Complete-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![n8n](https://img.shields.io/badge/n8n-2.27-orange)
![Odoo](https://img.shields.io/badge/Odoo-17.0-red)

This is Project #2 in a portfolio of SME workflow automation projects, built
on the same core stack as [Project #1: Odoo Invoice
Automation](../Odoo-Invoice-Automation) — reusing its Twilio WhatsApp
channel and Odoo integration, extended with an AI Agent, tool-calling, and
conversation memory.

---

## 🎯 Overview

Retail and distribution SMEs running Odoo get a constant stream of WhatsApp
messages asking "is this in stock?" and "how much is it?". Answering these
manually costs staff time and delays responses — sometimes losing the sale
to a customer who doesn't wait.

This assistant answers those questions automatically, in seconds, over the
same WhatsApp number the business already uses:

1. **Customer messages** the business's WhatsApp number with a product
   question
2. **AI Agent** (Google Gemini) interprets the question and calls tools to
   search the live Odoo catalog
3. **Grounded reply** — stock and price are only ever stated after a real
   tool call returns that data; the agent never answers from assumption
4. **Ambiguity handling** — if multiple products match, the agent asks which
   one, rather than guessing
5. **Every conversation logged** to PostgreSQL for review and analytics

**Business impact:**
- ✅ Instant, always-on responses to stock/price questions
- ✅ Frees staff from repetitive lookups
- ✅ Reuses the WhatsApp channel already sold in Project #1 — a natural
  upsell, not a new integration
- ✅ Every answer traceable to a real database query, not a hallucination

---

## 📊 System Architecture

```
Customer (WhatsApp)
      |
      v
   Twilio  --webhook-->  n8n
                           |
                           v
                    AI Agent Node
                    (Gemini, tool-calling, memory)
                     |              |
                     v              v
              search_product   get_product_details
              (sub-workflow)   (sub-workflow)
                     |              |
                     +------+-------+
                            v
                    Odoo (JSON-RPC, execute_kw)
                            |
                            v
                   Grounded reply composed
                            |
                            v
                   Twilio sends WhatsApp reply
                            |
                            v
                   Logged to PostgreSQL
                   (phone, message, reply, resolved,
                    response_time_ms)
```

Full design rationale, data flow, and tool contracts are in
[`project-architecture.md`](./project-architecture.md).

---

## ⚙️ Technology Stack

| Component | Role |
|---|---|
| **n8n** | Orchestration — webhook, AI Agent, tools, memory, logging |
| **Google Gemini API** (`gemini-2.5-flash` / `3-flash-preview`) | LLM backend — chosen for a genuine free tier; swappable without touching tools or logic |
| **Odoo 17** | Source of truth for product name/SKU/category/stock/price, via JSON-RPC |
| **Twilio WhatsApp API** | Customer-facing channel, reused from Project #1 |
| **PostgreSQL 16** | Conversation audit log |
| **Docker Compose** | Local dev environment (Odoo, n8n, Postgres) |
| **ngrok** | Tunnels the local n8n webhook to Twilio |

---

## 🧠 How the Agent Stays Grounded

The system prompt enforces strict rules, not just suggestions:

- Stock/price is **only ever stated immediately after a tool call returns
  that exact data** — never from prior knowledge or assumption
- **Multiple matches → the agent asks which one**, rather than guessing
  (e.g. "Blue T-Shirt" resolves to Small/Medium/Large and the agent asks the
  customer to clarify)
- **No match → clean escalation** ("a team member will follow up"), never a
  substituted or invented product
- **Follow-up references** ("what about the gaming one?") are resolved
  using conversation memory, but stock/price is always **re-verified with a
  fresh tool call**, never assumed stale from earlier in the conversation

This is deliberately more constrained than a general-purpose chatbot — the
constraint is the actual product.

---

## 🔧 Tool Definitions

### `search_product(query)`
- Searches Odoo's `product.product` by name, SKU, or barcode
- Multi-word queries are matched as an AND of substrings against the name
  (so "blue shirt" correctly matches "Blue T-Shirt Small/Medium/Large"),
  OR'd against a direct SKU/barcode match
- Returns candidates ranked by `match_score` — a reproducible string-overlap
  score, deliberately **not** an LLM-reported "confidence" value

### `get_product_details(product_id)`
- Direct lookup of `qty_available`, `list_price`, and category
- Explicitly normalizes Odoo's `false`-as-empty-field sentinel before
  returning data, so a genuinely out-of-stock item is never misreported

Both tools are built as standalone n8n sub-workflows (not inline HTTP
nodes) because each needs pre/post-processing logic — see
[`DEBUGGING_LOG.md`](./DEBUGGING_LOG.md#5-http-request-tool-cant-run-multi-step-logic)
for why that choice was necessary, not just preferred.

---

## 🚀 Setup

### Prerequisites
- Docker Desktop with WSL2 (Windows) or native Docker (Linux/Mac)
- An Odoo 17 instance running (see [Project #1's
  docker-compose.yml](../Odoo-Invoice-Automation/docker-compose.yml) for a
  working reference)
- n8n v2.27+ (self-hosted, Community Edition is sufficient)
- A Google AI Studio API key ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)) — free tier, no card required
- A Twilio account with WhatsApp Sandbox enabled
- ngrok (or any tunneling tool) for exposing n8n's webhook to Twilio

### 1. Seed the demo catalog

```bash
pip install requests --break-system-packages

export ODOO_URL=http://localhost:8069
export ODOO_DB=odoo
export ODOO_USERNAME=admin
export ODOO_PASSWORD=admin

python3 seed_demo_catalog.py
```

Seeds 21 products across Apparel/Electronics/Accessories, including a
same-name product cluster (for testing disambiguation) and one intentionally
zero-stock item (for testing out-of-stock handling). See the script's
comments for the full catalog list.

### 2. Set required environment variables

In your n8n container's `docker-compose.yml`:
```yaml
environment:
  N8N_BLOCK_ENV_ACCESS_IN_NODE: "false"
  ODOO_URL: "http://odoo:8069"
  ODOO_DB: "odoo"
  ODOO_USER: "${ODOO_USER}"
  ODOO_PASSWORD: "${ODOO_PASSWORD}"
```
`http://odoo:8069` (the Docker service name), not `localhost` — n8n and
Odoo run in separate containers on the same Docker network.

### 3. Create the logging database

```bash
docker exec -it <postgres_container_name> psql -U odoo -c "CREATE DATABASE ai_assistant_logs;"

docker exec -it <postgres_container_name> psql -U odoo -d ai_assistant_logs << 'EOF'

CREATE TABLE IF NOT EXISTS conversation_logs (
  id SERIAL PRIMARY KEY,
  phone VARCHAR(20) NOT NULL,
  user_message TEXT NOT NULL,
  assistant_reply TEXT,
  tool_called VARCHAR(50),
  matched_product_id INTEGER,
  match_score NUMERIC(3,2),
  resolved BOOLEAN NOT NULL DEFAULT false,
  response_time_ms INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_conversation_phone ON conversation_logs(phone);
CREATE INDEX idx_conversation_created_at ON conversation_logs(created_at);

EOF
```

### 4. Import the workflows

Import all three files from `workflows/` into n8n:
- `Tool - Search Product.json`
- `Tool - Get Product Details.json`
- `AI Inventory Assistant.json` (the main workflow)

**Publish/Activate both tool sub-workflows** before testing — the main
workflow will fail to call them otherwise (see [Debugging Log
#6](./DEBUGGING_LOG.md#6-tool-sub-workflows-not-activepublished)).

### 5. Configure credentials in n8n

- **Google Gemini**: paste your AI Studio API key
- **Twilio**: reuse your Project #1 credential, or create new with your
  Account SID/Auth Token
- **Postgres**: point at `ai_assistant_logs` (host: `postgres`, port `5432`)

### 6. Connect Twilio to your local n8n via ngrok

```bash
ngrok http 5678
```

In Twilio Console → Messaging → Try it out → WhatsApp Sandbox Settings, set
**"When a message comes in"** to your ngrok HTTPS URL +
`/webhook/whatsapp-incoming`, method `POST`.

### 7. Test

Send a WhatsApp message to your Twilio Sandbox number (after joining with
`join <your-sandbox-keyword>`):
```
Do you have a wireless mouse?
```

---

## 📈 Verified Test Scenarios

All confirmed working over real WhatsApp, not just n8n's internal test chat:

| Scenario | Message | Result |
|---|---|---|
| Single clean match | "Do you have a wireless mouse?" | Correct stock + price |
| 2-way ambiguity | "Do you have an SSD?" | Asks 1TB vs 512GB |
| 3-way ambiguity | "Do you have a blue shirt?" | Asks Small/Medium/Large |
| No match / escalation | "Do you have gaming headphones?" | Clean escalation, no substitution |
| Memory / pronoun resolution | "wireless mouse?" → "what about the gaming one?" | Correctly pivots, re-verifies stock fresh |

---

## ⚠️ Known Limitations (Honest, By Design)

- **Response time**: ~20-25 seconds end-to-end on Gemini's free tier, driven
  by multiple sequential LLM calls per turn plus two Odoo round-trips. A
  paid-tier model or faster provider would reduce this meaningfully for
  production use.
- **`tool_called`, `matched_product_id`, `match_score` are not logged**:
  this version of n8n's AI Agent node doesn't natively expose which tools
  ran or their results at the top level. Rather than guess from reply text,
  these columns are left `NULL` — a real, documented gap, not a bug or a
  fake value.
- **Memory is message-count-based, not time-based**: resets per chat
  session rather than expiring after ~20-30 minutes of inactivity within an
  ongoing session, as originally scoped. A true TTL-based memory would need
  a persistent, timestamp-aware store — noted as a Phase 2 improvement.
- **Free-tier LLM quota**: subject to rate limits during heavy testing; not
  suitable as-is for high-volume production traffic without upgrading to a
  paid tier.
- **No order placement, no web widget, no admin dashboard** — all
  deliberately out of scope for this MVP (see
  [`project-architecture.md`](./project-architecture.md#8-mvp-boundaries-explicitly-out-of-scope-for-v1)).

---

## 🔮 Future Improvements

- Consolidate `search_product` + `get_product_details` into a single tool
  call for single-match queries, saving one LLM reasoning round-trip (see
  discussion in project notes — deliberately deferred to preserve tested
  disambiguation behavior)
- Category-filter queries ("show me accessories under $30")
- Product recommendations ("gaming mouse under $40" → ranked options)
- Web chat widget alongside WhatsApp
- TTL-based memory via a persistent store

---

## 📚 Documentation

- **[`project-architecture.md`](./project-architecture.md)** — full design
  rationale, data flow, tool contracts, MVP boundaries
- **[`DEBUGGING_LOG.md`](./DEBUGGING_LOG.md)** — 15 real bugs hit during the
  build, with root causes and fixes — the most honest documentation of what
  this actually took to build

---

## 📄 License

MIT License © 2026 Taha Tahir

---

## 🤝 Related Work

Project #1 in this portfolio: [Odoo Invoice
Automation](../Odoo-Invoice-Automation) — automated WhatsApp invoice
delivery, sharing the same Odoo/Twilio/n8n foundation this project builds on.
