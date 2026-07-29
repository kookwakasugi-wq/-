# lark-mcp

An MCP server that gives Claude read-only access to Lark (Feishu) group chats, so
chat history can be summarised and analysed the same way as any other connected
source.

Built to read the **カフェプリマ** and **プリマ** group chats, but nothing in it is
specific to those groups.

## Tools

| Tool | Purpose |
| --- | --- |
| `lark_list_chats` | List the groups the bot belongs to; returns the `chat_id` values the other tools need. |
| `lark_search_chats` | Find a group by name keyword. |
| `lark_get_chat` | Group metadata: name, description, owner, member count. |
| `lark_list_chat_members` | Members of a group. |
| `lark_list_messages` | Chat history as a readable transcript, with a time range and pagination. |
| `lark_get_message` | A single message by id, including its thread linkage. |

`lark_list_messages` renders each message as `[timestamp] sender: content`. Rich
text, cards and mentions are flattened to plain text; images, files and other
attachments become `[image image_key=…]`-style markers so nothing is silently
dropped. Without a time range it returns the last 30 days.

## Setup

### 1. Create a Lark app

In the developer console — [open.larksuite.com](https://open.larksuite.com/app)
for the international edition, [open.feishu.cn](https://open.feishu.cn/app) for
the China edition:

1. **Create custom app** → give it a name (e.g. "Claude chat reader").
2. Copy the **App ID** and **App Secret** from *Credentials & Basic Info*.
3. Under *Features*, enable **Bot**.
4. Under *Permissions & Scopes*, add:
   - `im:message:readonly` — read messages in groups the bot belongs to
   - `im:chat:readonly` — read group info and member lists
   - `contact:user.base:readonly` — *optional*, resolves sender ids to names.
     Without it the transcript shows raw `ou_…` ids instead.
5. **Publish** the app (*Version Management & Release*) and have a workspace
   admin approve it. Scopes do not take effect until the release is approved.

### 2. Add the bot to each group

Lark will not return history for a chat the bot is not in. In the Lark client,
open the group → **Settings** → **Group Bots** → **Add Bot** → select the app.
Repeat for カフェプリマ and プリマ.

> The bot can only read messages sent **after** it joined. Older history is not
> retrievable through the API.

### 3. Build

```bash
cd lark-mcp
npm install
npm run build
npm test
```

Requires Node 20+.

### 4. Configure credentials

Copy `.env.example` to `.env` and fill in `LARK_APP_ID` / `LARK_APP_SECRET`. Set
`LARK_DOMAIN=feishu` if you are on the China edition. Timestamps render in
`LARK_TIME_ZONE` (default `Asia/Tokyo`).

## Running it

### With Claude Code (stdio)

```bash
claude mcp add lark \
  --env LARK_APP_ID=cli_xxxx \
  --env LARK_APP_SECRET=xxxx \
  -- node /absolute/path/to/lark-mcp/dist/index.js
```

Or commit a `.mcp.json` in the project that should have access:

```json
{
  "mcpServers": {
    "lark": {
      "command": "node",
      "args": ["/absolute/path/to/lark-mcp/dist/index.js"],
      "env": { "LARK_APP_ID": "cli_xxxx", "LARK_APP_SECRET": "xxxx" }
    }
  }
}
```

The same stdio configuration works for Claude Desktop.

### As a hosted endpoint (HTTP)

```bash
MCP_AUTH_TOKEN=$(openssl rand -hex 32) npm run start:http
```

Serves stateless Streamable HTTP on `POST /mcp` (plus `GET /healthz`), listening
on `$PORT` (default 3000). When `MCP_AUTH_TOKEN` is set, requests must carry
`Authorization: Bearer <token>`; the server logs a warning if it is unset.

Deploy this behind TLS on any host that can run Node — Cloud Run, Fly.io, Render,
a VM. Do not expose it without `MCP_AUTH_TOKEN`: the endpoint reads your company
chat.

**Caveat for claude.ai custom connectors.** Adding a remote MCP server in
claude.ai's connector settings expects the server to implement the OAuth
authorization flow. This server only does static bearer-token auth, which is
enough for Claude Code, Claude Desktop and any client that lets you set a
header, but an OAuth layer would need to be added in front of it for the
claude.ai connector UI. The stdio path above needs no such work.

## Notes and limitations

- **Read-only by design.** There are no tools for sending, editing or deleting
  messages.
- **Not yet exercised against the live API.** The tool surface, message decoding
  and time handling are covered by unit tests (`npm test`), but the development
  sandbox blocks egress to `open.larksuite.com`, so the HTTP paths have not been
  run against a real tenant. Expect to verify scopes and endpoint behaviour on
  first connection.
- Lark caps `lark_list_messages` at 50 messages per page; follow `page_token`
  for more.
- Tenant access tokens are cached in memory and refreshed automatically; a
  token rejected early is dropped and re-fetched once.
- Transient `429`/`5xx` responses are retried three times with exponential
  backoff.
