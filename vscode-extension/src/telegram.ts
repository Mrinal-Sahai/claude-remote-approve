// Minimal Telegram Bot API client over Node's https (no third-party deps).
import * as https from "https";
import { URLSearchParams } from "url";

export interface TgResponse<T> {
  ok: boolean;
  result?: T;
  description?: string;
}

function call<T>(token: string, method: string, params: Record<string, string | number>): Promise<TgResponse<T>> {
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
        timeout: 20000,
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
 * Return the chat id of the most recent message sent to the bot, or null if
 * none yet. Used during onboarding to learn the user's chat id.
 */
export async function detectChatId(token: string): Promise<string | null> {
  const res = await call<Update[]>(token, "getUpdates", { offset: 0, timeout: 0 });
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
