import os
import sqlite3
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from contextlib import asynccontextmanager

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL") # Render сам подставит сюда ссылку

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

user_states = {}

def init_db():
    conn = sqlite3.connect('crm.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY, name TEXT, phone TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, client TEXT, amount REAL, desc TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY, client TEXT, end_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS money (id INTEGER PRIMARY KEY, comment TEXT, type TEXT, amount REAL)''')
    conn.commit()
    conn.close()

def db_query(query, params=(), fetch=False):
    conn = sqlite3.connect('crm.db')
    c = conn.cursor()
    c.execute(query, params)
    res = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return res

def is_owner(user_id): return user_id == OWNER_ID

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Клиенты", callback_data="menu_clients")
    kb.button(text="📦 Заказы", callback_data="menu_orders")
    kb.button(text="💳 Подписки", callback_data="menu_subs")
    kb.button(text="💰 Деньги", callback_data="menu_money")
    kb.button(text="📈 Сводка", callback_data="menu_summary")
    kb.adjust(2, 2, 1)
    return kb.as_markup()

def back_to_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Меню", callback_data="menu_main")
    return kb.as_markup()

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("📊 <b>CRM NFC/QR-стоек 2ГИС</b>\n\nВыбери раздел:", reply_markup=main_menu())

@dp.callback_query(F.data == "menu_main")
async def menu_main(callback: types.CallbackQuery):
    user_states.pop(callback.from_user.id, None)
    await callback.message.edit_text("📊 <b>CRM NFC/QR-стоек 2ГИС</b>\n\nВыбери раздел:", reply_markup=main_menu())

@dp.callback_query(F.data == "menu_clients")
async def menu_clients(callback: types.CallbackQuery):
    clients = db_query("SELECT name, phone FROM clients", fetch=True)
    text = "👥 <b>Клиенты</b>\n\n"
    if not clients: text += "Пока нет клиентов."
    else:
        for i, (name, phone) in enumerate(clients[:15], 1): text += f"{i}. {name} | {phone}\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить", callback_data="add_client")
    kb.button(text="◀️ Меню", callback_data="menu_main")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "add_client")
async def add_client_start(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = "wait_client"
    await callback.message.edit_text("Отправь одним сообщением:\n<b>Название | Телефон</b>", reply_markup=back_to_menu())

@dp.callback_query(F.data == "menu_orders")
async def menu_orders(callback: types.CallbackQuery):
    orders = db_query("SELECT id, client, amount, status FROM orders", fetch=True)
    text = "📦 <b>Заказы</b>\n\n"
    if not orders: text += "Пока нет заказов."
    else:
        for o_id, client, amount, status in orders[:10]:
            icon = "✅" if status == "Выполнен" else "⏳"
            text += f"{icon} {client} | {amount} ₽ | {status}\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новый заказ", callback_data="add_order")
    kb.button(text="✅ Выполнить заказ", callback_data="done_order_list")
    kb.button(text="◀️ Меню", callback_data="menu_main")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "add_order")
async def add_order_start(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = "wait_order"
    await callback.message.edit_text("Отправь одним сообщением:\n<b>Клиент | Сумма | Описание</b>", reply_markup=back_to_menu())

@dp.callback_query(F.data == "done_order_list")
async def done_order_list(callback: types.CallbackQuery):
    orders = db_query("SELECT id, client, amount FROM orders WHERE status != 'Выполнен'", fetch=True)
    if not orders:
        await callback.message.edit_text("Все заказы выполнены! 🎉", reply_markup=back_to_menu())
        return
    kb = InlineKeyboardBuilder()
    for o_id, client, amount in orders: kb.button(text=f"📦 {client} ({amount} ₽)", callback_data=f"done_order_{o_id}")
    kb.button(text="◀️ Назад", callback_data="menu_orders")
    kb.adjust(1)
    await callback.message.edit_text("Выбери выполненный заказ:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("done_order_"))
async def done_order_process(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    order = db_query("SELECT client, amount FROM orders WHERE id=?", (order_id,), fetch=True)[0]
    db_query("UPDATE orders SET status='Выполнен' WHERE id=?", (order_id,))
    db_query("INSERT INTO money (comment, type, amount) VALUES (?, ?, ?)", (f"Заказ: {order[0]}", "Поступление", order[1]))
    await callback.message.edit_text(f"✅ Заказ для <b>{order[0]}</b> выполнен.\nВ Деньги добавлено {order[1]} ₽.", reply_markup=back_to_menu())

@dp.callback_query(F.data == "menu_money")
async def menu_money(callback: types.CallbackQuery):
    income = db_query("SELECT SUM(amount) FROM money WHERE type='Поступление'", fetch=True)[0][0] or 0
    expense = db_query("SELECT SUM(amount) FROM money WHERE type='Расход'", fetch=True)[0][0] or 0
    recent = db_query("SELECT type, amount, comment FROM money ORDER BY id DESC LIMIT 5", fetch=True)
    text = "💰 <b>Деньги (последние 5)</b>\n\n"
    if recent:
        for t, a, c in recent:
            icon = "🟢" if t == "Поступление" else "🔴"
            text += f"{icon} {a} ₽ — {c}\n"
    text += f"\n━━━━━━━━━━━━━━\nПоступления: {income} ₽\nРасходы: {expense} ₽\n<b>Прибыль: {income - expense} ₽</b>"
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить операцию", callback_data="add_money")
    kb.button(text="◀️ Меню", callback_data="menu_main")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "add_money")
async def add_money_start(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = "wait_money"
    await callback.message.edit_text("Отправь одним сообщением:\n<b>Поступление или Расход | Сумма | Комментарий</b>", reply_markup=back_to_menu())

@dp.callback_query(F.data == "menu_summary")
async def menu_summary(callback: types.CallbackQuery):
    income = db_query("SELECT SUM(amount) FROM money WHERE type='Поступление'", fetch=True)[0][0] or 0
    expense = db_query("SELECT SUM(amount) FROM money WHERE type='Расход'", fetch=True)[0][0] or 0
    clients = db_query("SELECT COUNT(*) FROM clients", fetch=True)[0][0]
    orders = db_query("SELECT COUNT(*) FROM orders", fetch=True)[0][0]
    text = f"📈 <b>Сводка</b>\n\n👥 Клиентов: {clients}\n📦 Заказов: {orders}\n💰 Поступления: {income} ₽\n💸 Расходы: {expense} ₽\n<b>Прибыль: {income - expense} ₽</b>"
    await callback.message.edit_text(text, reply_markup=back_to_menu())

@dp.callback_query(F.data == "menu_subs")
async def menu_subs(callback: types.CallbackQuery):
    await callback.message.edit_text("Раздел подписок в разработке для этой версии.", reply_markup=back_to_menu())

@dp.message(F.text)
async def handle_text(message: types.Message):
    if not is_owner(message.from_user.id): return
    state = user_states.get(message.from_user.id)
    if not state:
        await message.answer("Я тебя не понял. Нажми /start", reply_markup=main_menu())
        return
    parts = [p.strip() for p in message.text.split("|")]
    if state == "wait_client":
        if len(parts) < 2: return await message.answer("❌ Формат: Название | Телефон")
        db_query("INSERT INTO clients (name, phone) VALUES (?, ?)", (parts[0], parts[1]))
        user_states.pop(message.from_user.id, None)
        await message.answer("✅ Клиент добавлен.", reply_markup=main_menu())
    elif state == "wait_order":
        if len(parts) < 2: return await message.answer("❌ Формат: Клиент | Сумма | Описание")
        try: amount = float(parts[1])
        except ValueError: return await message.answer("❌ Сумма должна быть числом.")
        desc = parts[2] if len(parts) > 2 else ""
        db_query("INSERT INTO orders (client, amount, desc, status) VALUES (?, ?, ?, 'В работе')", (parts[0], amount, desc))
        user_states.pop(message.from_user.id, None)
        await message.answer("✅ Заказ добавлен.", reply_markup=main_menu())
    elif state == "wait_money":
        if len(parts) < 2: return await message.answer("❌ Формат: Тип | Сумма | Комментарий")
        if parts[0] not in ["Поступление", "Расход"]: return await message.answer("❌ Тип: 'Поступление' или 'Расход'")
        try: amount = float(parts[1])
        except ValueError: return await message.answer("❌ Сумма должна быть числом.")
        comment = parts[2] if len(parts) > 2 else ""
        db_query("INSERT INTO money (comment, type, amount) VALUES (?, ?, ?)", (comment, parts[0], amount))
        user_states.pop(message.from_user.id, None)
        await message.answer("✅ Операция добавлена.", reply_markup=main_menu())

# --- WEB-СЕРВЕР (FASTAPI) ДЛЯ RENDER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await bot.set_webhook(webhook_url)
        print(f"Webhook установлен на {webhook_url}")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def index():
    return {"status": "ok", "message": "Bot is running"}