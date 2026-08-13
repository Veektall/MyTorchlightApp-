import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import postgres from "npm:postgres@3.4.5";

const OLD = "https://kwulmnvxhybbxlsdcwcn.supabase.co/functions/v1/telegram-unified-relay-v52";
const sql = postgres(Deno.env.get("SUPABASE_DB_URL")!, { prepare: false, max: 2, idle_timeout: 20, connect_timeout: 20 });
const json = (d: unknown, s = 200) => new Response(JSON.stringify(d), { status: s, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store, max-age=0" } });
const b64 = (v: string) => Uint8Array.from(atob(v), c => c.charCodeAt(0));
const pem = (v: string) => b64(v.replace(/-----BEGIN [^-]+-----/g, "").replace(/-----END [^-]+-----/g, "").replace(/\s+/g, ""));

async function vault(name: string) {
  const rows = await sql`select decrypted_secret from vault.decrypted_secrets where name=${name} limit 1`;
  return rows.length ? String(rows[0].decrypted_secret ?? "") : null;
}

async function authorized(auth: string) {
  const r = await fetch(OLD, { method: "POST", headers: { authorization: auth, "content-type": "application/json" }, body: JSON.stringify({ sealed: { v: 0 } }) });
  return r.status === 400;
}

async function openSealed(s: any) {
  if (!s || s.v !== 1) throw new Error("Unsupported sealed payload");
  const keyText = await vault("telegram_relay_private_key");
  if (!keyText) throw new Error("Private key missing");
  const privateKey = await crypto.subtle.importKey("pkcs8", pem(keyText), { name: "RSA-OAEP", hash: "SHA-256" }, false, ["decrypt"]);
  const rawAes = await crypto.subtle.decrypt({ name: "RSA-OAEP" }, privateKey, b64(String(s.wrapped_key || "")));
  const aes = await crypto.subtle.importKey("raw", rawAes, "AES-GCM", false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(String(s.iv || "")), tagLength: 128 }, aes, b64(String(s.ciphertext || "")));
  return JSON.parse(new TextDecoder().decode(plain));
}

function uuid(v: unknown) {
  const s = String(v || "").trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(s)) throw new Error("Invalid thread_id");
  return s;
}

Deno.serve(async req => {
  if (req.method !== "POST") return json({ ok: false, error: "Method not allowed" }, 405);
  const auth = req.headers.get("authorization") || "";
  if (!auth || !(await authorized(auth))) return json({ ok: false, error: "Unauthorized" }, 401);
  const raw = await req.text();
  let input: any, payload: any;
  try { input = JSON.parse(raw); payload = await openSealed(input?.sealed); }
  catch (e) { return json({ ok: false, error: e instanceof Error ? e.message : "Invalid request" }, 400); }

  const kind = String(payload.kind || "text");
  if (kind === "text" || kind === "response") {
    try {
      const thread = uuid(payload.thread_id);
      const message = String(payload.message || "").trim();
      const max = kind === "response" ? 32000 : 4000;
      if (!message || message.length > max) throw new Error("Invalid message");
      if (payload.dry_run === true) return json({ ok: true, dry_run: true, kind, parts: Math.max(1, Math.ceil(message.length / 3000)), bytes: new TextEncoder().encode(message).byteLength, format: "telegram_html_mobile" });
      const seconds = Math.min(600, Math.max(15, Number(payload.reply_window_seconds || 600)));
      const rows = await sql`select public.telegram_private_mirror_v532(${thread}::uuid,${message},${seconds},${kind}) as result`;
      return json({ ok: true, ...(rows[0]?.result || {}), kind, format: "telegram_html_mobile" });
    } catch (e) {
      return json({ ok: false, error: "Telegram formatted text delivery failed", detail: e instanceof Error ? e.message.slice(0, 300) : "unknown" }, 502);
    }
  }

  const r = await fetch(OLD, { method: "POST", headers: { authorization: auth, "content-type": "application/json" }, body: raw });
  return new Response(await r.text(), { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/json; charset=utf-8", "cache-control": "no-store, max-age=0" } });
});
