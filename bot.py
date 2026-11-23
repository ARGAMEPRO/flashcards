#!/usr/bin/env python3
"""Карточки для запоминания в Telegram.

Вопрос на лице карточки, ответ на обороте. Переворот — интерактивным виджетом
внутри сообщения (sendWidget → widget_query → answerWidgetQuery). Если сервер
виджеты не отдаёт, бот откатывается на обычное сообщение с кнопкой.

Интервалы — упрощённый SM-2: забыл → завтра, знаю → 1, 3, дальше × лёгкость.

Запуск: python3 bot.py  (токен: $BOT_TOKEN или ./token.txt)
"""

import datetime as dt
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("BOT_TOKEN") or open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
).read().strip()
BASE = f"https://api.telegram.org/bot{TOKEN}"
DB = os.environ.get("DB_PATH", "cards.db")
UPDATES = ["message", "callback_query", "widget_query", "shared_widget_query"]

PENDING = {}  # user_id -> {"step": "front"|"back", "front": str}


class ApiError(Exception):
    def __init__(self, method, code, description):
        self.method, self.code, self.description = method, code, description
        super().__init__(f"{method}: [{code}] {description}")


def api(method, **params):
    data = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            data[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            data[key] = json.dumps(value, ensure_ascii=False)
        else:
            data[key] = str(value)
    req = urllib.request.Request(f"{BASE}/{method}", data=urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=65) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            raise ApiError(method, exc.code, raw[:300])
    except urllib.error.URLError as exc:
        raise ApiError(method, -1, str(exc.reason))
    if not payload.get("ok"):
        raise ApiError(method, payload.get("error_code"), payload.get("description"))
    return payload["result"]


def send(chat_id, text, **kw):
    return api("sendMessage", chat_id=chat_id, text=text, **kw)


# ------------------------------------------------------------------ база ---
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                ease REAL NOT NULL DEFAULT 2.5,
                interval INTEGER NOT NULL DEFAULT 0,
                due TEXT NOT NULL,
                reviews INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL
            );
            """
        )


def today():
    return dt.date.today().isoformat()


def next_interval(interval, ease, known):
    if not known:
        return 1, max(1.3, ease - 0.2)
    interval = 1 if interval == 0 else 3 if interval == 1 else round(interval * ease)
    return min(interval, 365), min(2.8, ease + 0.05)


def next_due_card(user_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE user_id = ? AND due <= ? ORDER BY due, id LIMIT 1",
            (user_id, today()),
        ).fetchone()


# --------------------------------------------------------- виджет-карточка ---
WIDGET_HTML = r"""<!doctype html><meta charset="utf-8">
<style>
body{margin:0;padding:10px 12px;font:15px/1.35 system-ui,-apple-system,sans-serif;
 color:var(--tg-theme-text-color);background:transparent}
.s{font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;margin-bottom:6px}
.card{border:1px solid var(--tg-theme-hint-color);border-radius:12px;padding:13px;
 min-height:56px;margin-bottom:10px;font-size:16px;font-weight:600;line-height:1.35}
.card.back{font-weight:400}
button{width:100%;padding:10px;border:0;border-radius:10px;font:600 15px system-ui,sans-serif;
 background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}
button:active{opacity:.65}
</style>
<div class="s" id="s">вопрос</div>
<div class="card" id="c"></div>
<button id="b">показать ответ</button>
<script>
var open=false,front="",back="";
function draw(){
  document.getElementById('s').textContent=open?'ответ':'вопрос';
  document.getElementById('c').textContent=open?back:front;
  document.getElementById('c').className='card'+(open?' back':'');
  document.getElementById('b').textContent=open?'вернуть вопрос':'показать ответ';
}
function load(){
  var d={};
  try{d=JSON.parse(TelegramWidget.chatData||'{}')}catch(e){}
  front=d.front||'';back=d.back||'';open=!!d.open;draw();
}
load();
TelegramWidget.onEvent('chatDataChanged',load);
document.getElementById('b').addEventListener('click',function(){
  TelegramWidget.request('flip').then(function(r){
    open=(r.result==='1');draw();
  },function(){});
});
TelegramWidget.ready();
</script>"""


def card_chat_data(card, open_side=False):
    return json.dumps({"front": card["front"], "back": card["back"], "open": 1 if open_side else 0})


def grade_keyboard(card_id, back_text):
    return {
        "inline_keyboard": [
            [{"text": "Знаю", "callback_data": f"know:{card_id}", "style": "success"},
             {"text": "Забыл", "callback_data": f"dunno:{card_id}", "style": "danger"}],
            [{"text": "Скопировать ответ", "copy_text": {"text": back_text[:200]}}],
        ]
    }


def show_card(chat_id, card):
    """Пробует виджет с переворотом, при ошибке — обычное сообщение."""
    try:
        api(
            "sendWidget", chat_id=chat_id, html=WIDGET_HTML, height=210,
            allow_queries=True, chat_data=card_chat_data(card),
            caption=f"Карточка №{card['id']} · повтор №{card['reviews'] + 1}\n"
                    "Нажмите на кнопку в карточке, чтобы увидеть ответ.",
        )
        return
    except ApiError as exc:
        print("sendWidget недоступен:", exc.description, flush=True)

    send(
        chat_id,
        f"Карточка №{card['id']} · повтор №{card['reviews'] + 1}\n\n<b>{card['front']}</b>",
        parse_mode="HTML",
        reply_markup={"inline_keyboard": [[
            {"text": "Показать ответ", "callback_data": f"show:{card['id']}", "style": "primary"}
        ]]},
    )


def handle_widget_query(update):
    q = update.get("widget_query") or update.get("shared_widget_query")
    if not q:
        return
    chat, message_id = q.get("chat"), q.get("message_id")
    if not chat or not message_id:
        return

    user_id = (q.get("from") or {}).get("id")
    data = {}
    try:
        data = json.loads(q.get("chat_data") or "{}")
    except ValueError:
        pass

    opened = 0 if data.get("open") else 1
    data["open"] = opened
    try:
        api("answerWidgetQuery", widget_query_id=q["id"], data=str(opened))
    except ApiError as exc:
        print("answerWidgetQuery:", exc.description, flush=True)

    try:
        api("editMessageWidgetData", chat_id=chat["id"], message_id=message_id,
            chat_data=json.dumps(data, ensure_ascii=False))
    except ApiError as exc:
        print("editMessageWidgetData:", exc.description, flush=True)

    if opened and user_id:
        send_ephemeral(
            user_id,
            "Ответ открыт. Оцените себя — кнопки придут следующим сообщением.",
        )
        with db() as conn:
            card = conn.execute(
                "SELECT * FROM cards WHERE user_id = ? AND front = ? ORDER BY id DESC LIMIT 1",
                (user_id, data.get("front", "")),
            ).fetchone()
        if card:
            send(chat["id"], f"Оцените карточку №{card['id']}",
                 reply_markup=grade_keyboard(card["id"], card["back"]))


def send_ephemeral(user_id, text):
    """Сообщение видит только нажавший: приходит по callback-кнопке или виджету."""
    try:
        api("sendMessage", user_id=user_id, text=text,
            ephemeral_message_parameters={"user_id": user_id})
    except ApiError:
        pass


# ------------------------------------------------------------- команды -------
HELLO = (
    "Карточки для запоминания.\n\n"
    "/add — новая карточка (вопрос, потом ответ)\n"
    "/review — пройти то, что пора\n"
    "/stats — сколько всего и сколько ждёт\n"
    "/list — последние десять"
)


def on_message(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()
    command = text.split("@")[0]

    if command in ("/start", "/help"):
        return send(chat_id, HELLO)

    if command == "/add":
        PENDING[user_id] = {"step": "front"}
        return send(chat_id, "Вопрос или термин? Напишите одной строкой.")

    if command == "/review":
        card = next_due_card(user_id)
        if not card:
            return send(chat_id, "На сегодня всё повторено. Добавить карточку — /add.")
        return show_card(chat_id, card)

    if command == "/stats":
        with db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id = ?", (user_id,)).fetchone()[0]
            due = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE user_id = ? AND due <= ?", (user_id, today())
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE user_id = ? AND reviews > 0", (user_id,)
            ).fetchone()[0]
        return send(chat_id, f"Всего карточек: {total}\nПора повторить: {due}\nУже повторяли: {done}")

    if command == "/list":
        with db() as conn:
            rows = conn.execute(
                "SELECT id, front, due FROM cards WHERE user_id = ? ORDER BY id DESC LIMIT 10",
                (user_id,),
            ).fetchall()
        if not rows:
            return send(chat_id, "Карточек нет. Первая — /add.")
        return send(chat_id, "Последние карточки:\n" + "\n".join(
            f"№{r['id']} · {r['due']} · {r['front'][:60]}" for r in rows))

    state = PENDING.get(user_id)
    if state and state["step"] == "front":
        if len(text) < 2:
            return send(chat_id, "Слишком коротко. Напишите вопрос целиком.")
        PENDING[user_id] = {"step": "back", "front": text}
        return send(chat_id, "Теперь ответ.")

    if state and state["step"] == "back":
        PENDING.pop(user_id, None)
        if not text:
            return send(chat_id, "Пустой ответ не сохраняю. Начните заново: /add")
        with db() as conn:
            conn.execute(
                "INSERT INTO cards(user_id, front, back, due, created) VALUES (?, ?, ?, ?, ?)",
                (user_id, state["front"], text, today(), today()),
            )
        return send(chat_id, "Карточка добавлена. Ещё одну — /add, повторить — /review")

    send(chat_id, "Не понял. Команды: /add, /review, /stats, /list")


def on_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    user_id = cb["from"]["id"]
    data = cb.get("data", "")
    api("answerCallbackQuery", callback_query_id=cb["id"])

    if data.startswith("show:"):
        card_id = int(data.split(":")[1])
        with db() as conn:
            card = conn.execute(
                "SELECT * FROM cards WHERE id = ? AND user_id = ?", (card_id, user_id)
            ).fetchone()
        if not card:
            return
        return api(
            "editMessageText", chat_id=chat_id, message_id=cb["message"]["message_id"],
            text=f"Карточка №{card['id']}\n\n<b>{card['front']}</b>\n\n— {card['back']}",
            parse_mode="HTML", reply_markup=grade_keyboard(card_id, card["back"]),
        )

    if data.startswith(("know:", "dunno:")):
        action, raw_id = data.split(":")
        card_id = int(raw_id)
        with db() as conn:
            card = conn.execute(
                "SELECT * FROM cards WHERE id = ? AND user_id = ?", (card_id, user_id)
            ).fetchone()
            if not card:
                return
            interval, ease = next_interval(card["interval"], card["ease"], known=(action == "know"))
            due = (dt.date.today() + dt.timedelta(days=interval)).isoformat()
            conn.execute(
                "UPDATE cards SET interval = ?, ease = ?, due = ?, reviews = reviews + 1 WHERE id = ?",
                (interval, ease, due, card_id),
            )
        verdict = "Знаете" if action == "know" else "Вернём позже"
        send(chat_id, f"{verdict}: карточка №{card_id} вернётся через {interval} дн.")
        nxt = next_due_card(user_id)
        if nxt:
            return show_card(chat_id, nxt)
        return send(chat_id, "На сегодня всё повторено.")


def main():
    init_db()
    try:
        api("setMyCommands", commands=[
            {"command": "add", "description": "новая карточка"},
            {"command": "review", "description": "повторить"},
            {"command": "stats", "description": "цифры"},
            {"command": "list", "description": "последние карточки"},
        ])
    except ApiError as exc:
        print("setMyCommands:", exc.description, flush=True)

    me = api("getMe")
    print(f"@{me['username']} на связи; Ctrl+C для выхода", flush=True)

    offset = None
    while True:
        try:
            updates = api("getUpdates", offset=offset, timeout=50, allowed_updates=UPDATES)
        except ApiError as exc:
            print("getUpdates:", exc.description, flush=True)
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    on_message(upd["message"])
                elif "callback_query" in upd:
                    on_callback(upd["callback_query"])
                elif "widget_query" in upd or "shared_widget_query" in upd:
                    handle_widget_query(upd)
            except ApiError as exc:
                print("update error:", exc.description, flush=True)
            except Exception as exc:  # noqa: BLE001
                print("update crash:", type(exc).__name__, exc, flush=True)


if __name__ == "__main__":
    main()
