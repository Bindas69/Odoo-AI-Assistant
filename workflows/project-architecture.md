# Project #2: AI Inventory Assistant — Architecture

## 1. Problem

SMEs running Odoo receive repetitive WhatsApp/customer messages asking
"is X in stock?" and "how much is X?". Answering these manually costs
staff time and delays responses, sometimes costing sales to customers
who don't wait for a reply.

## 2. Business Value

- Instant, always-on responses to stock/price queries
- Frees staff from repetitive lookups
- Answers are grounded in live Odoo data — never guessed or stale
- Reuses the Twilio/WhatsApp channel already sold in Project #1,
  making this a natural upsell rather than a new sales motion

## 3. Architecture Diagram

```
Customer (WhatsApp)
      |
      v
   Twilio  --webhook-->  n8n
                           |
                           v
                    AI Agent Node
                    (Groq LLM, tool-calling)
                     |              |
                     v              v
              search_product   get_product_details
                     |              |
                     +------+-------+
                            v
                    Odoo (JSON-RPC, execute_kw,
                    reusable credential: url/db/user/pass)
                            |
                            v
                   Grounded reply composed
                            |
                            v
                   Twilio sends WhatsApp reply
                            |
                            v
                   Log to PostgreSQL
                   (phone, message, reply, tool_called,
                    matched_product_id, match_score,
                    resolved, response_time_ms)
```

## 4. Components

| Component | Role |
|---|---|
| Twilio WhatsApp API | Customer-facing channel (reused from Project #1) |
| n8n | Orchestration: webhook, AI Agent, tools, logging |
| Groq (free tier) | LLM backend — swappable later without touching tools/logic |
| Odoo | Source of truth for product name/SKU/category/stock/price |
| PostgreSQL | Conversation audit log |

## 5. Data Flow

1. Customer sends WhatsApp message → Twilio webhook fires → n8n
2. AI Agent receives message + phone-keyed memory context (last product, ~20-30 min TTL)
3. Agent calls `search_product` if the message names/implies a product
4. If 1 match → agent calls `get_product_details` → replies with stock+price
5. If >1 match → agent lists candidates, asks user to disambiguate
6. If 0 match → agent replies it couldn't find the item, logs `resolved=false`
7. Every turn logged to Postgres regardless of outcome

## 6. Tool Definitions

### `search_product(query: string)`
- Odoo model: `product.product`
- Domain: OR across `name`, `default_code` (SKU), `barcode`
- Returns: list of `{product_id, name, default_code, match_score}`
- `match_score`: string-similarity ranking between query and matched
  field — NOT an LLM-reported confidence value (deliberately avoided,
  see Project #1 documentation-honesty precedent)

### `get_product_details(product_id: int)`
- Odoo model: `product.product`
- Returns: `{qty_available, list_price, categ_id}`
- Must handle Odoo's `false`-as-empty sentinel explicitly

## 7. Conversation Flow / Grounding Rules

- Agent must NEVER state stock or price without a tool result backing it
- Ambiguous match (>1 candidate) → always ask, never guess
- No match → escalate ("let me get a team member") + log unresolved
- Memory: last discussed product only, ~20-30 min expiry — no long-term
  conversation history

## 8. MVP Boundaries (explicitly out of scope for v1)

- No order placement or payment
- No web widget (stretch goal only if time allows)
- No admin dashboard (Postgres queries suffice for now)
- No semantic/vector search — direct structured query is sufficient
  and easier to explain for a ~20-product catalog

## 9. Future Improvements (Phase 2+)

- Category-filter queries ("show me accessories under $30")
- Product recommendations ("gaming mouse under $40" → ranked options)
- Web chat widget
- Swap Groq → OpenAI/Anthropic/self-hosted if a client requires it
  (only the Chat Model node changes — tools and logic stay the same)
