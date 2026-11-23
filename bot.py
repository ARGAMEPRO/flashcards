"""Telegram-бот с карточками для запоминания.

Закидываешь вопрос и ответ — бот показывает карточку, ты жмёшь «Показать ответ»,
потом «Знаю» или «Забыл». Интервалы считаются по упрощённому SM-2: знал — карточка
уходит дальше по времени, забыл — возвращается на завтра.

Запуск: python3 bot.py (нужен BOT_TOKEN)
"""

import asyncio
import datetime as dt
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

TOKEN = os.getenv("BOT_TOKEN", "")
DB = os.getenv("DB_PATH", "cards.db")

dp = Dispatcher()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
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


def today() -> dt.date:
    return dt.date.today()


def next_interval(interval: int, ease: float, known: bool) -> tuple[int, float]:
    """Упрощённый SM-2: возвращает новый интервал в днях и новую лёгкость."""
    if not known:
        return 1, max(1.3, ease - 0.2)
    if interval == 0:
        interval = 1
    elif interval == 1:
        interval = 3
    else:
        interval = round(interval * ease)
    return min(interval, 365), min(2.8, ease + 0.05)


class AddCard(StatesGroup):
    front = State()
    back = State()


def card_keyboard(card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Показать ответ", callback_data=f"show:{card_id}")]]
    )


def answer_keyboard(card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Знаю", callback_data=f"know:{card_id}"),
                InlineKeyboardButton(text="Забыл", callback_data=f"dunno:{card_id}"),
            ]
        ]
    )


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Карточки для запоминания.\n\n"
        "/add — добавить карточку (вопрос, потом ответ)\n"
        "/review — пройти то, что пора повторить\n"
        "/stats — сколько всего и сколько ждёт\n"
        "/list — последние 10 карточек"
    )


@dp.message(Command("add"))
async def add_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AddCard.front)
    await message.answer("Вопрос или термин? Напишите одной строкой.")


@dp.message(AddCard.front)
async def add_front(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("Слишком коротко. Напишите вопрос целиком.")
        return
    await state.update_data(front=text)
    await state.set_state(AddCard.back)
    await message.answer("Теперь ответ.")


@dp.message(AddCard.back)
async def add_back(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    await state.clear()
    if len(text) < 1:
        await message.answer("Пустой ответ не сохраняю. Попробуйте ещё раз через /add.")
        return

    with db() as conn:
        conn.execute(
            "INSERT INTO cards(user_id, front, back, due, created) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, data["front"], text, today().isoformat(), today().isoformat()),
        )
    await message.answer("Карточка добавлена. Ещё одну — /add, повторить — /review.")


@dp.message(Command("review"))
async def review(message: Message) -> None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cards WHERE user_id = ? AND due <= ? ORDER BY due LIMIT 1",
            (message.from_user.id, today().isoformat()),
        ).fetchone()

    if row is None:
        await message.answer("На сегодня всё повторено. Добавить карточку — /add.")
        return

    await message.answer(
        f"Карточка №{row['id']} · повтор №{row['reviews'] + 1}\n\n{row['front']}",
        reply_markup=card_keyboard(row["id"]),
    )


@dp.callback_query(F.data.startswith("show:"))
async def show_answer(callback: CallbackQuery) -> None:
    card_id = int(callback.data.split(":")[1])
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cards WHERE id = ? AND user_id = ?", (card_id, callback.from_user.id)
        ).fetchone()
    if row is None:
        await callback.answer("Карточка не найдена", show_alert=False)
        return
    await callback.message.edit_text(
        f"Карточка №{row['id']}\n\n{row['front']}\n\n— {row['back']}",
        reply_markup=answer_keyboard(card_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith(("know:", "dunno:")))
async def grade(callback: CallbackQuery) -> None:
    action, raw_id = callback.data.split(":")
    card_id = int(raw_id)

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cards WHERE id = ? AND user_id = ?", (card_id, callback.from_user.id)
        ).fetchone()
        if row is None:
            await callback.answer("Карточка не найдена")
            return

        interval, ease = next_interval(row["interval"], row["ease"], known=(action == "know"))
        due = (today() + dt.timedelta(days=interval)).isoformat()
        conn.execute(
            "UPDATE cards SET interval = ?, ease = ?, due = ?, reviews = reviews + 1 WHERE id = ?",
            (interval, ease, due, card_id),
        )

    await callback.message.edit_text(
        f"{'Отлично' if action == 'know' else 'Вернём позже'}: карточка №{card_id} "
        f"вернётся через {interval} дн.\n\nДальше — /review"
    )
    await callback.answer("Записано")


@dp.message(Command("stats"))
async def stats(message: Message) -> None:
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id = ?", (message.from_user.id,)
        ).fetchone()[0]
        due = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id = ? AND due <= ?",
            (message.from_user.id, today().isoformat()),
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id = ? AND reviews > 0", (message.from_user.id,)
        ).fetchone()[0]
    await message.answer(f"Всего карточек: {total}\nПора повторить: {due}\nУже повторяли: {done}")


@dp.message(Command("list"))
async def list_cards(message: Message) -> None:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, front, due FROM cards WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (message.from_user.id,),
        ).fetchall()
    if not rows:
        await message.answer("Карточек нет. Первая — /add.")
        return
    lines = [f"№{r['id']} · {r['due']} · {r['front'][:60]}" for r in rows]
    await message.answer("Последние карточки:\n" + "\n".join(lines))


async def main() -> None:
    init_db()
    if not TOKEN:
        raise SystemExit("Не задан BOT_TOKEN — возьмите токен у @BotFather.")
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
