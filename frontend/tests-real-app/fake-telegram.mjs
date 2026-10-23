// Telegram Bot API falsa para o teste da aplicação real (verification affordance, akitaonrails/my-skills).
// Imita só o que o gateway usa (getMe, sendMessage, sendPhoto, sendVideo, getUpdates, getChat) e registra cada chamada,
// para o teste conferir o que o backend real mandou ao Telegram. Nunca grava o token: só os 4 últimos caracteres.
//   GET    /__calls  -> chamadas registradas
//   DELETE /__calls  -> limpa o registro
import http from "node:http";

const PORT = Number(process.env.FAKE_TELEGRAM_PORT || 8091);
// Token que o Telegram recusa no getMe, para o teste do caminho de erro.
const REJECTED_TOKEN_PREFIX = "100000000:";
const calls = [];
let nextMessageId = 1;
// Busca de canais (#23): o bot "está" neste canal pelos updates, e este canal público responde ao getChat.
const DISCOVERED_CHANNEL = { id: -1002222222222, title: "Canal Descoberto", type: "channel" };
const PUBLIC_CHANNEL = { id: -1003333333333, title: "Canal Público", type: "channel", username: "canalpublico" };

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

// Campos de um multipart/form-data: valor dos campos de texto e nome do arquivo dos campos de arquivo.
function parseMultipart(body, contentType) {
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/.exec(contentType);
  if (!boundary) return { fields: {}, files: {} };
  const fields = {};
  const files = {};
  for (const part of body.toString("latin1").split(`--${boundary[1] || boundary[2]}`)) {
    const [head, ...rest] = part.split("\r\n\r\n");
    const name = /name="([^"]+)"/.exec(head || "");
    if (!name) continue;
    const filename = /filename="([^"]*)"/.exec(head);
    const value = rest.join("\r\n\r\n").replace(/\r\n$/, "");
    if (filename) files[name[1]] = { filename: filename[1], size: Buffer.byteLength(value, "latin1") };
    else fields[name[1]] = Buffer.from(value, "latin1").toString("utf8");
  }
  return { fields, files };
}

function send(res, status, payload) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(payload));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === "/__calls") {
    if (req.method === "DELETE") calls.length = 0;
    return send(res, 200, calls);
  }

  const match = /^\/bot([^/]+)\/(\w+)$/.exec(url.pathname);
  if (!match) return send(res, 404, { ok: false, error_code: 404, description: "Not Found" });
  const [, token, method] = match;

  const body = await readBody(req);
  const contentType = req.headers["content-type"] || "";
  let fields = {};
  let files = {};
  if (contentType.startsWith("application/json")) fields = JSON.parse(body.toString("utf8") || "{}");
  else if (contentType.startsWith("multipart/form-data")) ({ fields, files } = parseMultipart(body, contentType));

  calls.push({ method, tokenSuffix: token.slice(-4), query: Object.fromEntries(url.searchParams), fields, files });

  if (token.startsWith(REJECTED_TOKEN_PREFIX)) {
    return send(res, 401, { ok: false, error_code: 401, description: "Unauthorized" });
  }
  if (method === "getMe") {
    return send(res, 200, {
      ok: true,
      result: { id: Number(token.split(":")[0]), is_bot: true, first_name: "Bot de Teste", username: `teste_${token.slice(-4).toLowerCase()}_bot` },
    });
  }
  if (method === "getUpdates") {
    return send(res, 200, { ok: true, result: [{ update_id: 1, channel_post: { message_id: 1, chat: DISCOVERED_CHANNEL, text: "oi" } }] });
  }
  if (method === "getChat") {
    if (url.searchParams.get("chat_id") === `@${PUBLIC_CHANNEL.username}`) return send(res, 200, { ok: true, result: PUBLIC_CHANNEL });
    return send(res, 400, { ok: false, error_code: 400, description: "Bad Request: chat not found" });
  }
  if (["sendMessage", "sendPhoto", "sendVideo"].includes(method)) {
    return send(res, 200, { ok: true, result: { message_id: nextMessageId++, chat: { id: Number(fields.chat_id) }, date: Math.floor(Date.now() / 1000) } });
  }
  return send(res, 404, { ok: false, error_code: 404, description: `Method ${method} not implemented by the fake` });
});

server.listen(PORT, "127.0.0.1", () => console.log(`fake telegram on http://127.0.0.1:${PORT}`));
