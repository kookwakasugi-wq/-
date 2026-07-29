import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { LarkClient, LarkError, formatTimestamp, renderMessageContent, type LarkMessage } from './lark.js';

const DEFAULT_LOOKBACK_DAYS = 30;
const MAX_PAGE_SIZE = 50;

const TIME_ZONE = process.env.LARK_TIME_ZONE ?? 'Asia/Tokyo';

type Chat = {
  chat_id: string;
  name?: string;
  description?: string;
  owner_id?: string;
  external?: boolean;
  chat_status?: string;
};

type Paged<K extends string, T> = {
  [key in K]?: T[];
} & { page_token?: string; has_more?: boolean };

export function createServer(client: LarkClient): McpServer {
  const server = new McpServer(
    { name: 'lark-mcp', version: '0.1.0' },
    {
      instructions:
        'Read-only access to Lark (Feishu) group chats. The app can only see chats its bot has ' +
        'been added to — start with lark_list_chats or lark_search_chats to find a chat_id, then ' +
        'read history with lark_list_messages.'
    }
  );

  server.registerTool(
    'lark_list_chats',
    {
      title: 'List Lark chats',
      description:
        'List the groups the app/bot is a member of. Returns chat_id values needed by the other tools. ' +
        'The bot only sees chats it has been explicitly added to.',
      inputSchema: {
        page_size: z.number().int().min(1).max(100).optional().describe('Results per page (default 50).'),
        page_token: z.string().optional().describe('Token from a previous response to fetch the next page.')
      },
      annotations: { readOnlyHint: true, openWorldHint: true }
    },
    async ({ page_size, page_token }) =>
      guard(async () => {
        const data = await client.get<Paged<'items', Chat>>('/open-apis/im/v1/chats', {
          page_size: page_size ?? 50,
          page_token,
          user_id_type: 'open_id'
        });
        const chats = data.items ?? [];
        if (!chats.length) {
          return text(
            'No chats found. The bot must be added as a member of a group before it can see it: ' +
              'open the group in Lark → Settings → Group Bots → Add Bot.'
          );
        }
        return text([chats.map(formatChatLine).join('\n'), paginationFooter(data)].filter(Boolean).join('\n\n'));
      })
  );

  server.registerTool(
    'lark_search_chats',
    {
      title: 'Search Lark chats',
      description: 'Search the groups the app/bot belongs to by name keyword.',
      inputSchema: {
        query: z.string().min(1).describe('Keyword matched against chat names.'),
        page_size: z.number().int().min(1).max(100).optional().describe('Results per page (default 20).'),
        page_token: z.string().optional().describe('Token from a previous response to fetch the next page.')
      },
      annotations: { readOnlyHint: true, openWorldHint: true }
    },
    async ({ query, page_size, page_token }) =>
      guard(async () => {
        const data = await client.get<Paged<'items', Chat>>('/open-apis/im/v1/chats/search', {
          query,
          page_size: page_size ?? 20,
          page_token,
          user_id_type: 'open_id'
        });
        const chats = data.items ?? [];
        if (!chats.length) return text(`No chat matched "${query}" among the groups the bot belongs to.`);
        return text([chats.map(formatChatLine).join('\n'), paginationFooter(data)].filter(Boolean).join('\n\n'));
      })
  );

  server.registerTool(
    'lark_get_chat',
    {
      title: 'Get Lark chat details',
      description: 'Fetch metadata for one group: name, description, owner and member count.',
      inputSchema: {
        chat_id: z.string().min(1).describe('Chat id, e.g. oc_xxxxxxxx.')
      },
      annotations: { readOnlyHint: true, openWorldHint: true }
    },
    async ({ chat_id }) =>
      guard(async () => {
        const chat = await client.get<Chat & { user_count?: string; bot_count?: string }>(
          `/open-apis/im/v1/chats/${encodeURIComponent(chat_id)}`,
          { user_id_type: 'open_id' }
        );
        const lines = [
          `name: ${chat.name ?? '(unnamed)'}`,
          `chat_id: ${chat_id}`,
          chat.description ? `description: ${chat.description}` : null,
          chat.user_count ? `members: ${chat.user_count} users, ${chat.bot_count ?? '0'} bots` : null,
          chat.owner_id ? `owner: ${chat.owner_id}` : null,
          chat.external !== undefined ? `external: ${chat.external}` : null
        ].filter(Boolean);
        return text(lines.join('\n'));
      })
  );

  server.registerTool(
    'lark_list_chat_members',
    {
      title: 'List Lark chat members',
      description: 'List the members of a group.',
      inputSchema: {
        chat_id: z.string().min(1).describe('Chat id, e.g. oc_xxxxxxxx.'),
        page_size: z.number().int().min(1).max(100).optional().describe('Results per page (default 50).'),
        page_token: z.string().optional().describe('Token from a previous response to fetch the next page.')
      },
      annotations: { readOnlyHint: true, openWorldHint: true }
    },
    async ({ chat_id, page_size, page_token }) =>
      guard(async () => {
        const data = await client.get<Paged<'items', { member_id?: string; name?: string; member_id_type?: string }>>(
          `/open-apis/im/v1/chats/${encodeURIComponent(chat_id)}/members`,
          { member_id_type: 'open_id', page_size: page_size ?? 50, page_token }
        );
        const members = data.items ?? [];
        if (!members.length) return text('No members returned.');
        const body = members.map(m => `- ${m.name ?? '(unknown)'} (${m.member_id ?? '?'})`).join('\n');
        return text([body, paginationFooter(data)].filter(Boolean).join('\n\n'));
      })
  );

  server.registerTool(
    'lark_list_messages',
    {
      title: 'Read Lark chat history',
      description:
        'Read the message history of a group as a readable transcript. Without a time range this ' +
        `returns the last ${DEFAULT_LOOKBACK_DAYS} days. Times accept "YYYY-MM-DD", an ISO 8601 ` +
        'datetime, or epoch seconds.',
      inputSchema: {
        chat_id: z.string().min(1).describe('Chat id, e.g. oc_xxxxxxxx.'),
        start_time: z.string().optional().describe('Oldest message to include.'),
        end_time: z.string().optional().describe('Newest message to include.'),
        days: z
          .number()
          .int()
          .min(1)
          .optional()
          .describe('Convenience alternative to start_time: look back this many days from now.'),
        order: z
          .enum(['asc', 'desc'])
          .optional()
          .describe('asc = oldest first (default, reads like a transcript), desc = newest first.'),
        page_size: z
          .number()
          .int()
          .min(1)
          .max(MAX_PAGE_SIZE)
          .optional()
          .describe(`Messages per page (max ${MAX_PAGE_SIZE}, default ${MAX_PAGE_SIZE}).`),
        page_token: z.string().optional().describe('Token from a previous response to fetch the next page.'),
        resolve_names: z
          .boolean()
          .optional()
          .describe('Resolve sender ids to display names (default true, needs the contact scope).')
      },
      annotations: { readOnlyHint: true, openWorldHint: true }
    },
    async ({ chat_id, start_time, end_time, days, order, page_size, page_token, resolve_names }) =>
      guard(async () => {
        const now = Math.floor(Date.now() / 1000);
        let startSec = start_time !== undefined ? parseTime(start_time, 'start_time') : undefined;
        const endSec = end_time !== undefined ? parseTime(end_time, 'end_time') : undefined;
        if (startSec === undefined) {
          const lookback = days ?? DEFAULT_LOOKBACK_DAYS;
          startSec = (endSec ?? now) - lookback * 86400;
        }
        if (endSec !== undefined && startSec > endSec) {
          throw new UserError('start_time must be earlier than end_time.');
        }

        const data = await client.get<Paged<'items', LarkMessage>>('/open-apis/im/v1/messages', {
          container_id_type: 'chat',
          container_id: chat_id,
          start_time: startSec,
          end_time: endSec,
          sort_type: order === 'desc' ? 'ByCreateTimeDesc' : 'ByCreateTimeAsc',
          page_size: page_size ?? MAX_PAGE_SIZE,
          page_token
        });

        const messages = (data.items ?? []).filter(m => !m.deleted);
        const rangeLabel = `${formatTimestamp(String(startSec * 1000), TIME_ZONE)} – ${
          endSec ? formatTimestamp(String(endSec * 1000), TIME_ZONE) : 'now'
        } (${TIME_ZONE})`;

        if (!messages.length) {
          return text(`No messages in ${rangeLabel}.`);
        }

        const names = new Map<string, string>();
        if (resolve_names !== false) {
          const senderIds = [...new Set(messages.map(m => m.sender?.id).filter((id): id is string => !!id))];
          const resolved = await Promise.all(senderIds.map(async id => [id, await client.resolveUserName(id)] as const));
          for (const [id, name] of resolved) names.set(id, name);
        }

        const transcript = messages
          .map(message => {
            const when = formatTimestamp(message.create_time, TIME_ZONE);
            const senderId = message.sender?.id ?? 'unknown';
            const who =
              message.sender?.sender_type === 'app' ? `${names.get(senderId) ?? senderId} [bot]` : (names.get(senderId) ?? senderId);
            const threadMark = message.parent_id ? ' (reply)' : '';
            return `[${when}] ${who}${threadMark}: ${renderMessageContent(message)}`;
          })
          .join('\n');

        const header = `${messages.length} message(s), ${rangeLabel}`;
        return text([header, transcript, paginationFooter(data)].filter(Boolean).join('\n\n'));
      })
  );

  server.registerTool(
    'lark_get_message',
    {
      title: 'Get one Lark message',
      description: 'Fetch a single message by id, including its thread/reply linkage.',
      inputSchema: {
        message_id: z.string().min(1).describe('Message id, e.g. om_xxxxxxxx.')
      },
      annotations: { readOnlyHint: true, openWorldHint: true }
    },
    async ({ message_id }) =>
      guard(async () => {
        const data = await client.get<Paged<'items', LarkMessage>>(
          `/open-apis/im/v1/messages/${encodeURIComponent(message_id)}`
        );
        const message = data.items?.[0];
        if (!message) return text(`Message ${message_id} not found.`);
        const senderId = message.sender?.id;
        const who = senderId ? await client.resolveUserName(senderId) : 'unknown';
        const lines = [
          `message_id: ${message.message_id}`,
          `chat_id: ${message.chat_id ?? '?'}`,
          `sent: ${formatTimestamp(message.create_time, TIME_ZONE)} (${TIME_ZONE})`,
          `sender: ${who}`,
          `type: ${message.msg_type}`,
          message.parent_id ? `parent_id: ${message.parent_id}` : null,
          message.thread_id ? `thread_id: ${message.thread_id}` : null,
          '',
          renderMessageContent(message)
        ].filter(line => line !== null);
        return text(lines.join('\n'));
      })
  );

  return server;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

class UserError extends Error {}

function text(value: string): CallToolResult {
  return { content: [{ type: 'text', text: value }] };
}

/**
 * Tool handlers must not throw: an API-level failure (missing scope, bot not in
 * the chat) is information the caller can act on, so surface it as an error
 * result rather than a transport-level exception.
 */
async function guard(run: () => Promise<CallToolResult>): Promise<CallToolResult> {
  try {
    return await run();
  } catch (error) {
    if (error instanceof LarkError || error instanceof UserError) {
      return { content: [{ type: 'text', text: `Lark API error: ${error.message}` }], isError: true };
    }
    const message = error instanceof Error ? error.message : String(error);
    return { content: [{ type: 'text', text: `Unexpected error: ${message}` }], isError: true };
  }
}

function formatChatLine(chat: Chat): string {
  const description = chat.description ? ` — ${chat.description.replace(/\s+/g, ' ').slice(0, 80)}` : '';
  return `- ${chat.name ?? '(unnamed)'} [${chat.chat_id}]${description}`;
}

function paginationFooter(data: { has_more?: boolean; page_token?: string }): string | null {
  if (!data.has_more || !data.page_token) return null;
  return `More results available — pass page_token: ${data.page_token}`;
}

/** Accepts epoch seconds, "YYYY-MM-DD", or an ISO 8601 datetime. Exported for tests. */
export function parseTime(value: string, field: string): number {
  if (/^\d{10}$/.test(value)) return Number(value);
  if (/^\d{13}$/.test(value)) return Math.floor(Number(value) / 1000);

  // A bare date is interpreted in the server's configured time zone, not UTC,
  // so "2026-07-01" means local midnight for whoever is reading the chat.
  const isBareDate = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = Date.parse(isBareDate ? `${value}T00:00:00${tzOffset(value)}` : value);
  if (Number.isNaN(parsed)) {
    throw new UserError(`Could not parse ${field}="${value}". Use YYYY-MM-DD, an ISO 8601 datetime, or epoch seconds.`);
  }
  return Math.floor(parsed / 1000);
}

/** Offset string (e.g. "+09:00") for TIME_ZONE on the given date. */
function tzOffset(isoDate: string): string {
  const reference = new Date(`${isoDate}T00:00:00Z`);
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: TIME_ZONE,
    timeZoneName: 'longOffset'
  }).formatToParts(reference);
  const name = parts.find(part => part.type === 'timeZoneName')?.value ?? 'GMT+00:00';
  const offset = name.replace('GMT', '');
  return offset === '' ? '+00:00' : offset;
}
