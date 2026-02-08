import sqlite3
import datetime
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from openai import OpenAI


# =========================
# 🔧 تنظیمات
# =========================



DAILY_IMAGE_LIMIT = 3


# ✅ کلاینت GapGPT
client = OpenAI(
    base_url="https://api.gapgpt.app/v1",
    api_key=GAPGPT_API_KEY
)


# =========================
# 🗄️ دیتابیس
# =========================
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        messages INTEGER DEFAULT 0,
        images_today INTEGER DEFAULT 0,
        last_image_date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        telegram_id INTEGER,
        role TEXT,
        content TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_or_create_user(user):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (user.id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
            (user.id, user.username)
        )

    conn.commit()
    conn.close()


# =========================
# 🧠 حافظه
# =========================
def get_memory(user_id, limit=10):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""
    SELECT role, content FROM memory
    WHERE telegram_id=?
    ORDER BY rowid DESC
    LIMIT ?
    """, (user_id, limit))

    rows = c.fetchall()
    conn.close()

    rows.reverse()
    return [{"role": r, "content": c} for r, c in rows]


def save_memory(user_id, role, content):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute(
        "INSERT INTO memory (telegram_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )

    conn.commit()
    conn.close()


# =========================
# 💬 چت متنی
# =========================
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    get_or_create_user(user)

    messages = [
        {"role": "system", "content": "تو یک دستیار فارسی، مودب و دقیق هستی"}
    ]

    messages += get_memory(user.id)
    messages.append({"role": "user", "content": text})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )

    answer = response.choices[0].message.content

    save_memory(user.id, "user", text)
    save_memory(user.id, "assistant", answer)

    await update.message.reply_text(answer)


# =========================
# 🖼️ تحلیل عکس (Vision)
# =========================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user)

    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"temp_{user.id}.jpg"
    await file.download_to_drive(path)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "این تصویر را تحلیل کن و توضیح بده"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"file://{os.path.abspath(path)}"
                        }
                    }
                ]
            }
        ]
    )

    os.remove(path)

    await update.message.reply_text(
        response.choices[0].message.content
    )


# =========================
# 🎨 ساخت عکس روزانه
# =========================
async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user)

    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("❌ مثال:\n/image گربه فضانورد")
        return

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    today = str(datetime.date.today())
    c.execute("""
    SELECT images_today, last_image_date
    FROM users WHERE telegram_id=?
    """, (user.id,))
    row = c.fetchone()

    images_today = 0
    last_date = None
    if row:
        images_today, last_date = row

    if last_date != today:
        images_today = 0

    if images_today >= DAILY_IMAGE_LIMIT:
        await update.message.reply_text("⛔ سهمیه ۳ عکس امروزت تموم شده")
        conn.close()
        return

    img = client.images.generate(
        model="gpt-image-1",
        prompt=topic,
        size="1024x1024"
    )

    await update.message.reply_photo(img.data[0].url)

    c.execute("""
    UPDATE users
    SET images_today=?, last_image_date=?
    WHERE telegram_id=?
    """, (images_today + 1, today, user.id))

    conn.commit()
    conn.close()


# =========================
# 🛡️ پنل ادمین
# =========================
def is_admin(user_id):
    return user_id in ADMIN_IDS


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی نداری")
        return

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM memory")
    messages = c.fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"📊 آمار ربات:\n\n"
        f"👤 کاربران: {users}\n"
        f"💬 پیام‌های ذخیره‌شده: {messages}"
    )


# =========================
# ▶️ اجرا
# =========================
if __name__ == "__main__":
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("✅ Bot is running with GapGPT...")
    app.run_polling()
