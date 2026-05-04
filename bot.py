import os
import time
import sqlite3
import logging
from dotenv import load_dotenv
import telebot
from telebot import types

# ================= ENV =================
load_dotenv()

TOKEN = "8614082185:AAEsAEIQgFuJo7z2eXxe2g4Jetxyu4g-8aM"
OWNER_ID = 7925843350

if not TOKEN:
    raise ValueError("TOKEN не найден")

bot = telebot.TeleBot(TOKEN)

# ================= LOG =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ================= DB =================
conn = sqlite3.connect("bank.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS credits (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    total INTEGER,
    payment INTEGER,
    last_pay REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS requests (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    amount INTEGER,
    periods INTEGER,
    status TEXT,
    created_at REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    rating INTEGER DEFAULT 5
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT,
    target TEXT,
    timestamp REAL
)
""")

conn.commit()

cursor.execute("INSERT OR IGNORE INTO admins VALUES (?)", (OWNER_ID,))
conn.commit()

# ================= SETTINGS =================
PENALTY_RATE = 0.02
RATING_DROP = 1
DAY_SEC = 86400

# ================= UTILS =================
def is_admin(uid):
    cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,))
    return cursor.fetchone() is not None


def log_admin(admin, action, target=""):
    cursor.execute(
        "INSERT INTO admin_logs (admin_id, action, target, timestamp) VALUES (?, ?, ?, ?)",
        (admin, action, target, time.time())
    )
    conn.commit()


def get_rating(user_id, username):
    cursor.execute("SELECT rating FROM users WHERE user_id=?", (user_id,))
    r = cursor.fetchone()

    if r:
        return r[0]

    cursor.execute(
        "INSERT INTO users VALUES (?, ?, ?)",
        (user_id, username, 5)
    )
    conn.commit()
    return 5


def percent(r):
    if r >= 9:
        return 0.05
    if r >= 7:
        return 0.08
    if r >= 5:
        return 0.10
    if r >= 3:
        return 0.15
    return 0.20


# ================= OVERDUE =================
def check_overdue():
    now = time.time()

    cursor.execute("SELECT user_id, total, last_pay FROM credits")
    rows = cursor.fetchall()

    for uid, total, last_pay in rows:
        if not last_pay:
            continue

        overdue = int((now - last_pay) // DAY_SEC)

        if overdue > 0:
            new_total = int(total + total * PENALTY_RATE * overdue)

            cursor.execute(
                "UPDATE credits SET total=?, last_pay=? WHERE user_id=?",
                (new_total, now, uid)
            )

    conn.commit()


# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(m, "🤖 Бот работает")


# ================= CREDIT =================
@bot.message_handler(commands=["credit"])
def credit(m):
    uid = str(m.from_user.id)
    username = m.from_user.username or "no_username"

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "Пример: /credit 10000 7")

    amount = int(args[1])
    periods = int(args[2])

    cursor.execute("SELECT status FROM requests WHERE user_id=?", (uid,))
    r = cursor.fetchone()

    if r and r[0] == "pending":
        return bot.reply_to(m, "Заявка уже есть")

    cursor.execute("""
    INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?, ?, ?)
    """, (uid, username, amount, periods, "pending", time.time()))
    conn.commit()

    bot.reply_to(m, "📄 Заявка отправлена")


# ================= PAY =================
@bot.message_handler(commands=["pay"])
def pay(m):
    uid = str(m.from_user.id)

    args = m.text.split()
    if len(args) < 2:
        return bot.reply_to(m, "Пример: /pay 1000")

    amount = int(args[1])

    cursor.execute("SELECT total FROM credits WHERE user_id=?", (uid,))
    r = cursor.fetchone()

    if not r:
        return bot.reply_to(m, "Нет кредита")

    new_total = max(r[0] - amount, 0)

    cursor.execute(
        "UPDATE credits SET total=?, last_pay=? WHERE user_id=?",
        (new_total, time.time(), uid)
    )

    conn.commit()

    bot.reply_to(m, f"💳 Осталось: {new_total}")


# ================= TOP =================
@bot.message_handler(commands=["top"])
def top(m):
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
    rows = cursor.fetchall()

    text = "🏆 ТОП:\n\n"

    for i, (name, r) in enumerate(rows, 1):
        text += f"{i}. @{name} ⭐ {r}\n"

    bot.reply_to(m, text)


# ================= ADMIN =================
@bot.message_handler(commands=["admin"])
def admin(m):
    if not is_admin(m.from_user.id):
        return

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton("📄 Заявки", callback_data="req"),
        types.InlineKeyboardButton("📜 Логи", callback_data="logs")
    )

    kb.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="stats")
    )

    bot.send_message(m.chat.id, "⚙️ Админ-панель", reply_markup=kb)


# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if not is_admin(c.from_user.id):
        return

    if c.data == "req":
        cursor.execute("SELECT user_id, username, amount FROM requests WHERE status='pending'")
        rows = cursor.fetchall()

        for uid, name, amount in rows:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅", callback_data=f"ok_{uid}"),
                types.InlineKeyboardButton("❌", callback_data=f"no_{uid}")
            )

            bot.send_message(c.message.chat.id, f"👤 @{name}\n💰 {amount}", reply_markup=kb)

    elif c.data == "stats":
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM requests")
        req = cursor.fetchone()[0]

        bot.send_message(c.message.chat.id, f"📊 Users: {users}\n📄 Requests: {req}")

    elif c.data == "logs":
        cursor.execute("SELECT admin_id, action, target FROM admin_logs ORDER BY id DESC LIMIT 10")
        rows = cursor.fetchall()

        text = "📜 LOGS:\n\n"
        for a, ac, t in rows:
            text += f"{a} | {ac} | {t}\n"

        bot.send_message(c.message.chat.id, text)

    elif c.data.startswith("ok_"):
        uid = c.data.split("_")[1]

        cursor.execute("SELECT username, amount, periods FROM requests WHERE user_id=?", (uid,))
        r = cursor.fetchone()
        if not r:
            return

        name, amount, periods = r

        rating = get_rating(uid, name)
        total = int(amount * (1 + percent(rating)))
        pay = total // periods

        cursor.execute("INSERT OR REPLACE INTO credits VALUES (?, ?, ?, ?, ?)",
                       (uid, name, total, pay, time.time()))

        cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
        conn.commit()

        bot.send_message(uid, f"✅ Одобрено\n💰 {total}\n💳 {pay}")

    elif c.data.startswith("no_"):
        uid = c.data.split("_")[1]

        cursor.execute("UPDATE requests SET status='rejected' WHERE user_id=?", (uid,))
        conn.commit()

        bot.send_message(uid, "❌ Отклонено")


# ================= LOOP =================
if __name__ == "__main__":
    logging.info("BOT STARTED")

    while True:
        try:
            check_overdue()
            bot.polling(none_stop=True)
        except Exception as e:
            logging.error(e)
            time.sleep(5)
