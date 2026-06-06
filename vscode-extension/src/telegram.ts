// Minimal Telegram Bot API client over Node's https (no third-party deps).
import * as https from "node:https";
import { URLSearchParams } from "node:url";

export interface TgResponse<T> {
  ok: boolean;
  result?: T;
  description?: string;
}

function call<T>(
  token: string,
  method: string,
  params: Record<string, string | number>,
  httpTimeoutSeconds = 20
): Promise<TgResponse<T>> {
  const body = new URLSearchParams(
    Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]))
  ).toString();

  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        host: "api.telegram.org",
        path: `/bot${token}/${method}`,
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "Content-Length": Buffer.byteLength(body),
        },
        timeout: httpTimeoutSeconds * 1000,
      },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(data) as TgResponse<T>);
          } catch {
            reject(new Error(`Telegram returned non-JSON (HTTP ${res.statusCode})`));
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("Telegram request timed out")));
    req.write(body);
    req.end();
  });
}

export interface BotInfo {
  id: number;
  username: string;
  first_name: string;
}

/** Validate a token. Throws with a friendly message if invalid. */
export async function getMe(token: string): Promise<BotInfo> {
  const res = await call<BotInfo>(token, "getMe", {});
  if (!res.ok || !res.result) {
    throw new Error(res.description || "Invalid bot token");
  }
  return res.result;
}

interface Update {
  update_id: number;
  message?: { chat?: { id?: number } };
  edited_message?: { chat?: { id?: number } };
}

/**
 * Wait up to `waitSeconds` for the user to send the bot any message, then
 * return their chat id. Uses a long-poll so it catches a message sent *during*
 * the wait window — important when the bot's update queue has already been
 * consumed by a running dispatcher (offset advanced, old messages gone).
 */
export async function detectChatId(
  token: string,
  waitSeconds = 20
): Promise<string | null> {
  // First try an instant poll — catches existing unread messages.
  const instant = await call<Update[]>(token, "getUpdates", {
    offset: 0,
    timeout: 0,
  });
  if (instant.ok && instant.result) {
    for (const upd of instant.result) {
      const msg = upd.message || upd.edited_message;
      const id = msg?.chat?.id;
      if (id !== undefined && id !== null) {
        return String(id);
      }
    }
  }
  // Nothing in the queue — long-poll so we catch the message the user is
  // about to send while the "I've sent it" dialog is showing.
  const res = await call<Update[]>(token, "getUpdates", {
    offset: 0,
    timeout: waitSeconds,
  }, waitSeconds + 10);
  if (!res.ok || !res.result) {
    return null;
  }
  let chatId: number | null = null;
  for (const upd of res.result) {
    const msg = upd.message || upd.edited_message;
    const id = msg?.chat?.id;
    if (id !== undefined && id !== null) {
      chatId = id;
    }
  }
  return chatId === null ? null : String(chatId);
}

export async function sendMessage(token: string, chatId: string, text: string): Promise<void> {
  const res = await call(token, "sendMessage", { chat_id: chatId, text });
  if (!res.ok) {
    throw new Error(res.description || "sendMessage failed");
  }
}
