/**
 * Minimal Lark (Feishu) Open API client.
 *
 * Handles tenant access token acquisition/caching, request retries and the
 * decoding of Lark's message payloads, which arrive as JSON encoded strings
 * whose shape depends on the message type.
 */

export type LarkConfig = {
  appId: string;
  appSecret: string;
  /** API base, e.g. https://open.larksuite.com or https://open.feishu.cn */
  baseUrl: string;
};

export class LarkError extends Error {
  constructor(
    message: string,
    readonly code: number,
    readonly httpStatus: number
  ) {
    super(message);
    this.name = 'LarkError';
  }
}

type LarkEnvelope<T> = {
  code: number;
  msg: string;
  data?: T;
};

const TOKEN_EXPIRY_MARGIN_SEC = 60;

export class LarkClient {
  private token: { value: string; expiresAt: number } | null = null;
  private tokenRequest: Promise<string> | null = null;
  private readonly userNameCache = new Map<string, string>();

  constructor(private readonly config: LarkConfig) {}

  static fromEnv(): LarkClient {
    const appId = process.env.LARK_APP_ID;
    const appSecret = process.env.LARK_APP_SECRET;
    if (!appId || !appSecret) {
      throw new Error(
        'LARK_APP_ID and LARK_APP_SECRET must be set. Create a custom app at ' +
          'https://open.larksuite.com/app (or https://open.feishu.cn/app) and copy its credentials.'
      );
    }
    const domain = (process.env.LARK_DOMAIN ?? 'larksuite').toLowerCase();
    const baseUrl =
      process.env.LARK_BASE_URL ??
      (domain === 'feishu' ? 'https://open.feishu.cn' : 'https://open.larksuite.com');
    return new LarkClient({ appId, appSecret, baseUrl });
  }

  /**
   * Tenant access tokens live for ~2h. Concurrent callers share one refresh so a
   * burst of tool calls does not fire a burst of auth requests.
   */
  private async getToken(): Promise<string> {
    const now = Date.now() / 1000;
    if (this.token && this.token.expiresAt - TOKEN_EXPIRY_MARGIN_SEC > now) {
      return this.token.value;
    }
    if (this.tokenRequest) return this.tokenRequest;

    this.tokenRequest = (async () => {
      const res = await fetch(`${this.config.baseUrl}/open-apis/auth/v3/tenant_access_token/internal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ app_id: this.config.appId, app_secret: this.config.appSecret })
      });
      const body = await readEnvelope<
        LarkEnvelope<unknown> & { tenant_access_token?: string; expire?: number }
      >(res);
      if (!res.ok || body.code !== 0 || !body.tenant_access_token) {
        throw new LarkError(
          `Failed to obtain tenant access token: ${body.msg ?? res.statusText}`,
          body.code ?? -1,
          res.status
        );
      }
      this.token = {
        value: body.tenant_access_token,
        expiresAt: Date.now() / 1000 + (body.expire ?? 7200)
      };
      return this.token.value;
    })();

    try {
      return await this.tokenRequest;
    } finally {
      this.tokenRequest = null;
    }
  }

  async get<T>(path: string, query: Record<string, string | number | undefined> = {}): Promise<T> {
    const url = new URL(`${this.config.baseUrl}${path}`);
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
    }

    for (let attempt = 0; ; attempt++) {
      const token = await this.getToken();
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json; charset=utf-8' }
      });

      // 429/5xx are transient; back off and retry a few times before surfacing.
      if ((res.status === 429 || res.status >= 500) && attempt < 3) {
        await sleep(2 ** attempt * 500);
        continue;
      }

      const body = await readEnvelope<LarkEnvelope<T>>(res);
      if (body.code === 99991663 || body.code === 99991661) {
        // Token invalid/expired earlier than advertised — drop it and retry once.
        this.token = null;
        if (attempt < 1) continue;
      }
      if (!res.ok || body.code !== 0) {
        throw new LarkError(describeLarkError(body), body.code ?? -1, res.status);
      }
      return body.data as T;
    }
  }

  /**
   * Resolve a display name for an open_id. Requires the contact scope; when the
   * app lacks it we fall back to the raw id rather than failing the whole call.
   */
  async resolveUserName(openId: string): Promise<string> {
    const cached = this.userNameCache.get(openId);
    if (cached) return cached;
    try {
      const data = await this.get<{ user?: { name?: string } }>(
        `/open-apis/contact/v3/users/${encodeURIComponent(openId)}`,
        { user_id_type: 'open_id' }
      );
      const name = data.user?.name ?? openId;
      this.userNameCache.set(openId, name);
      return name;
    } catch {
      this.userNameCache.set(openId, openId);
      return openId;
    }
  }
}

/**
 * Lark always answers with a JSON envelope. Anything else means the response
 * came from something other than Lark — a proxy, a captive portal, an outage
 * page — so say that instead of leaking a JSON parse error.
 */
async function readEnvelope<T>(res: Response): Promise<T> {
  const raw = await res.text();
  try {
    return JSON.parse(raw) as T;
  } catch {
    const preview = raw.replace(/\s+/g, ' ').trim().slice(0, 200);
    throw new LarkError(
      `Expected JSON from the Lark API but got a non-JSON response (HTTP ${res.status}). ` +
        `Check network egress to the API host. Response began: ${preview || '(empty)'}`,
      -1,
      res.status
    );
  }
}

function describeLarkError(body: { code: number; msg: string }): string {
  const hints: Record<number, string> = {
    99991672: 'the app is missing the required permission scope for this endpoint',
    230002: 'the app (bot) is not a member of this chat — add it to the group first',
    230020: 'the bot has no permission to read this chat',
    232001: 'chat not found'
  };
  const hint = hints[body.code];
  return hint ? `${body.msg} (code ${body.code}: ${hint})` : `${body.msg} (code ${body.code})`;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Message decoding
// ---------------------------------------------------------------------------

export type LarkMessage = {
  message_id: string;
  root_id?: string;
  parent_id?: string;
  thread_id?: string;
  msg_type: string;
  create_time?: string;
  update_time?: string;
  deleted?: boolean;
  chat_id?: string;
  sender?: { id?: string; id_type?: string; sender_type?: string };
  body?: { content?: string };
  mentions?: Array<{ key?: string; id?: string; name?: string }>;
};

type PostElement = {
  tag: string;
  text?: string;
  href?: string;
  user_name?: string;
  user_id?: string;
  file_name?: string;
  image_key?: string;
};

/**
 * Turn a Lark message body into readable plain text.
 *
 * `body.content` is a JSON string whose schema varies by `msg_type`; anything we
 * do not have a specific renderer for degrades to a `[msg_type]` marker plus the
 * raw JSON so no information is silently dropped.
 */
export function renderMessageContent(message: LarkMessage): string {
  const raw = message.body?.content;
  if (!raw) return '';

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return raw;
  }

  const content = parsed as Record<string, any>;
  switch (message.msg_type) {
    case 'text':
      return applyMentions(String(content.text ?? ''), message.mentions);
    case 'post':
      return renderPost(content, message.mentions);
    case 'image':
      return `[image image_key=${content.image_key ?? '?'}]`;
    case 'file':
      return `[file ${content.file_name ?? ''} file_key=${content.file_key ?? '?'}]`.trim();
    case 'audio':
      return `[audio duration=${content.duration ?? '?'}ms file_key=${content.file_key ?? '?'}]`;
    case 'media':
      return `[video ${content.file_name ?? ''} file_key=${content.file_key ?? '?'}]`.trim();
    case 'sticker':
      return `[sticker file_key=${content.file_key ?? '?'}]`;
    case 'share_chat':
      return `[shared chat chat_id=${content.chat_id ?? '?'}]`;
    case 'share_user':
      return `[shared user user_id=${content.user_id ?? '?'}]`;
    case 'system':
      return `[system] ${content.template ?? JSON.stringify(content)}`;
    case 'interactive':
      return `[card] ${renderCardText(content)}`;
    default:
      return `[${message.msg_type}] ${raw}`;
  }
}

function renderPost(content: Record<string, any>, mentions: LarkMessage['mentions']): string {
  // Rich text is keyed by locale (zh_cn / en_us / ja_jp); take whichever exists.
  const locales = Object.keys(content);
  const localeKey = locales.find(key => content[key]?.content) ?? locales[0];
  const post = content[localeKey] ?? {};
  const title: string = post.title ?? '';
  const lines: string[] = [];

  for (const paragraph of (post.content ?? []) as PostElement[][]) {
    const parts = paragraph.map(element => {
      switch (element.tag) {
        case 'text':
          return element.text ?? '';
        case 'a':
          return element.href ? `${element.text ?? element.href} (${element.href})` : (element.text ?? '');
        case 'at':
          return `@${element.user_name ?? element.user_id ?? 'unknown'}`;
        case 'img':
          return `[image image_key=${element.image_key ?? '?'}]`;
        case 'media':
          return `[video ${element.file_name ?? ''}]`.trim();
        default:
          return element.text ?? `[${element.tag}]`;
      }
    });
    lines.push(parts.join(''));
  }

  const bodyText = lines.join('\n');
  const combined = title ? `${title}\n${bodyText}` : bodyText;
  return applyMentions(combined, mentions);
}

function renderCardText(content: Record<string, any>): string {
  // Cards are arbitrary JSON; pull out the text-bearing fields for readability.
  const texts: string[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (node && typeof node === 'object') {
      for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
        if ((key === 'content' || key === 'text') && typeof value === 'string') texts.push(value);
        else walk(value);
      }
    }
  };
  walk(content);
  return texts.length ? texts.join(' / ') : JSON.stringify(content);
}

/** Replace the `@_user_N` placeholders Lark embeds in text with real names. */
function applyMentions(text: string, mentions: LarkMessage['mentions']): string {
  if (!mentions?.length) return text;
  let result = text;
  for (const mention of mentions) {
    if (!mention.key) continue;
    result = result.split(mention.key).join(`@${mention.name ?? mention.id ?? 'unknown'}`);
  }
  return result;
}

/** Lark timestamps are epoch milliseconds in a string. */
export function formatTimestamp(value: string | undefined, timeZone: string): string {
  if (!value) return 'unknown time';
  const ms = Number(value);
  if (!Number.isFinite(ms)) return value;
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(ms));
}
