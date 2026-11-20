import os
import re
import csv
import logging
import sqlite3
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "norms.db"
CSV_PATH = BASE_DIR / "data" / "norms.csv"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger("normativny_bot_rt")

CATEGORIES = {
    "law": ("⚖️ Законодательство и разрешения", "Законодательство"),
    "survey": ("📐 Изыскания и исходные данные", "Изыскания"),
    "gp": ("🗺 Генеральный план", "Генеральный план"),
    "ar": ("🏢 Архитектурные решения", "Архитектура"),
    "housing": ("🏠 Жилые здания", "Жилые здания"),
    "public": ("🏫 Общественные здания", "Общественные здания"),
    "education": ("🎓 Детские сады и школы", "Образование"),
    "structures": ("🏗 Конструкции", "Конструкции"),
    "seismic": ("🌍 Сейсмостойкость", "Сейсмостойкость"),
    "fire": ("🔥 Пожарная безопасность", "Пожарная безопасность"),
    "hvac": ("🌬 Отопление и вентиляция", "ОВ"),
    "water": ("🚰 Водоснабжение и канализация", "ВК"),
    "electric": ("⚡ Электроснабжение и связь", "Электрика"),
    "energy": ("☀️ Энергоэффективность", "Энергоэффективность"),
    "sanitary": ("🧪 Санитарные и экологические требования", "Санитарные требования"),
    "special": ("🌉 Специальные сооружения", "Специальные сооружения"),
    "estimate": ("🧾 Сметы и организация строительства", "Сметы"),
    "expertise": ("📋 Экспертиза и сдача объекта", "Экспертиза"),
}

OBJECTS = [
    "Индивидуальный жилой дом", "Многоквартирный жилой дом",
    "Детский сад", "Общеобразовательная школа", "Специальная школа",
    "Больница / поликлиника", "Административное здание",
    "Спортивный комплекс", "Торговый объект", "Гостиница",
    "Мост", "Дорога", "Подпорная стена", "Водонапорная башня",
    "Инженерные сети", "Другой объект"
]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS norms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'Требует проверки',
            approval TEXT DEFAULT '',
            effective_date TEXT DEFAULT '',
            scope TEXT DEFAULT '',
            parts TEXT DEFAULT '',
            clauses TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            keywords TEXT DEFAULT ''
        )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_norms_code ON norms(code)")
        con.commit()
    import_csv_if_empty()

def import_csv_if_empty():
    with db() as con:
        count = con.execute("SELECT COUNT(*) FROM norms").fetchone()[0]
    if count or not CSV_PATH.exists():
        return
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f, db() as con:
        reader = csv.DictReader(f)
        for row in reader:
            con.execute("""
                INSERT INTO norms
                (code,title,category,status,approval,effective_date,scope,parts,clauses,source_url,notes,keywords)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, tuple(row.get(k, "") for k in [
                "code","title","category","status","approval","effective_date",
                "scope","parts","clauses","source_url","notes","keywords"
            ]))
        con.commit()

def main_menu():
    keyboard = [
        [InlineKeyboardButton("🔎 Найти норматив", callback_data="search")],
        [InlineKeyboardButton("📚 Каталог документов", callback_data="catalog")],
        [InlineKeyboardButton("🏗 Поиск по типу объекта", callback_data="objects")],
        [InlineKeyboardButton("📐 Поиск по разделу проекта", callback_data="sections")],
        [InlineKeyboardButton("ℹ️ Как пользоваться", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Главное меню", callback_data="home")]])

def category_keyboard():
    rows = []
    items = list(CATEGORIES.items())
    for i in range(0, len(items), 2):
        row = []
        for key, (label, _) in items[i:i+2]:
            row.append(InlineKeyboardButton(label, callback_data=f"cat:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def object_keyboard():
    rows = []
    for i in range(0, len(OBJECTS), 2):
        rows.append([InlineKeyboardButton(x, callback_data=f"obj:{i+j}") for j, x in enumerate(OBJECTS[i:i+2])])
    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def search_norms(query, category=None, limit=12):
    q = f"%{query.lower()}%"
    sql = """SELECT * FROM norms WHERE
        lower(code) LIKE ? OR lower(title) LIKE ? OR lower(scope) LIKE ?
        OR lower(clauses) LIKE ? OR lower(keywords) LIKE ?"""
    args = [q, q, q, q, q]
    if category:
        sql += " AND lower(category) LIKE ?"
        args.append(f"%{category.lower()}%")
    sql += " ORDER BY code LIMIT ?"
    args.append(limit)
    with db() as con:
        return con.execute(sql, args).fetchall()

def format_norm(n):
    status = n["status"] or "Требует проверки"
    status_icon = "✅" if status.lower().startswith("действ") or status.lower() == "подтверждено" else "⚠️"
    lines = [
        f"📘 <b>{escape(n['code'])}</b>",
        f"<b>{escape(n['title'])}</b>",
        f"{status_icon} Статус: <b>{escape(status)}</b>",
    ]
    fields = [
        ("Утверждение", n["approval"]),
        ("Введение в действие", n["effective_date"]),
        ("Область применения", n["scope"]),
        ("Части / приложения", n["parts"]),
        ("Пункты и таблицы", n["clauses"]),
        ("Примечание", n["notes"]),
    ]
    for label, value in fields:
        if value:
            lines.append(f"\n<b>{label}:</b> {escape(value)}")
    if n["source_url"]:
        lines.append(f'\n🔗 <a href="{escape(n["source_url"])}">Источник документа</a>')
    lines.append("\n<i>Перед применением проверьте актуальность редакции и область действия документа.</i>")
    return "\n".join(lines)

def escape(s):
    s = str(s or "")
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🏛 <b>Нормативный бот РТ</b>\n\n"
        "Справочник нормативных документов для проектирования зданий и сооружений в Республике Таджикистан.\n\n"
        "Выберите действие:",
        reply_markup=main_menu(), parse_mode="HTML"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n/start — главное меню\n/search — поиск документа\n/catalog — каталог по разделам\n"
        "/objects — поиск по типу объекта\n/help — инструкция\n\n"
        "Можно отправить шифр СНиП, название документа или ключевое слово.",
        reply_markup=main_menu()
    )

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "search"
    await update.message.reply_text("Введите шифр, название нормы, пункт или ключевое слово:", reply_markup=back_menu())

async def catalog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выберите раздел нормативной базы:", reply_markup=category_keyboard())

async def objects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выберите тип объекта:", reply_markup=object_keyboard())

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if context.user_data.get("mode") == "search":
        context.user_data.pop("mode", None)
        results = search_norms(text)
        await send_results(update, results, f"Результаты поиска: {text}")
        return
    results = search_norms(text)
    await send_results(update, results, f"Поиск: {text}")

async def send_results(update, results, heading):
    if not results:
        await update.message.reply_text(
            f"По запросу «{escape(heading)}» ничего не найдено в текущей базе.\n"
            "Попробуйте другой шифр или ключевое слово. База пополняется по мере проверки документов.",
            reply_markup=main_menu(), parse_mode="HTML"
        )
        return
    await update.message.reply_text(f"🔎 <b>{escape(heading)}</b>\nНайдено: {len(results)}", parse_mode="HTML")
    for n in results[:8]:
        await update.message.reply_text(format_norm(n), parse_mode="HTML", disable_web_page_preview=True)
    await update.message.reply_text("Выберите следующее действие:", reply_markup=main_menu())

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "home":
        context.user_data.clear()
        await query.edit_message_text("🏛 <b>Нормативный бот РТ</b>\nВыберите действие:", reply_markup=main_menu(), parse_mode="HTML")
    elif data == "search":
        context.user_data["mode"] = "search"
        await query.edit_message_text("Введите шифр, название документа, пункт или ключевое слово:", reply_markup=back_menu())
    elif data == "catalog":
        await query.edit_message_text("Выберите раздел:", reply_markup=category_keyboard())
    elif data == "objects":
        await query.edit_message_text("Выберите тип объекта:", reply_markup=object_keyboard())
    elif data == "sections":
        await query.edit_message_text("Выберите раздел проекта:", reply_markup=category_keyboard())
    elif data == "help":
        await query.edit_message_text(
            "Отправьте шифр или ключевое слово для поиска. В карточке документа отображаются статус, область применения, пункты и источник.",
            reply_markup=back_menu()
        )
    elif data.startswith("cat:"):
        key = data.split(":", 1)[1]
        label, category = CATEGORIES.get(key, ("Раздел", ""))
        results = search_norms("", category=category, limit=20)
        if not results:
            await query.edit_message_text(
                f"<b>{escape(label)}</b>\nВ этой категории пока нет загруженных карточек документов.",
                reply_markup=back_menu(), parse_mode="HTML"
            )
        else:
            await query.edit_message_text(f"<b>{escape(label)}</b>\nДокументов: {len(results)}", parse_mode="HTML")
            for n in results[:8]:
                await context.bot.send_message(query.message.chat_id, format_norm(n), parse_mode="HTML", disable_web_page_preview=True)
    elif data.startswith("obj:"):
        idx = int(data.split(":", 1)[1])
        obj = OBJECTS[idx]
        terms = obj.lower().replace("/", " ")
        results = search_norms(terms, limit=12)
        if not results:
            await query.edit_message_text(
                f"<b>{escape(obj)}</b>\nКарточки для этого объекта ещё не добавлены. Можно выполнить поиск по отдельному нормативу.",
                reply_markup=back_menu(), parse_mode="HTML"
            )
        else:
            await query.edit_message_text(f"<b>{escape(obj)}</b>\nНайденные документы: {len(results)}", parse_mode="HTML")
            for n in results[:8]:
                await context.bot.send_message(query.message.chat_id, format_norm(n), parse_mode="HTML", disable_web_page_preview=True)

async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("start", "Главное меню"),
        ("search", "Найти норматив"),
        ("catalog", "Каталог документов"),
        ("objects", "Поиск по типу объекта"),
        ("help", "Инструкция"),
    ])

def main():
    if not TOKEN:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN. Создайте бота через BotFather и задайте токен в переменной окружения.")
    init_db()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("catalog", catalog_cmd))
    app.add_handler(CommandHandler("objects", objects_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
