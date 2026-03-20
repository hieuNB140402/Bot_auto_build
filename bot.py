from telegram import *
from telegram.ext import *

import os
from config import *
from build_manager import *

PAGE_SIZE = 10
projects = load_projects()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(p["name"], callback_data=p["name"])]
        for p in projects
    ]

    await update.message.reply_text(
        "Chọn project:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_versions(message, context, page):
    versions = context.user_data["versions"]
    name = context.user_data["project"]

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    current = versions[start:end]

    keyboard = [
        [InlineKeyboardButton(v, callback_data=f"{name}|{v}")]
        for v in current
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"page|{page - 1}"))
    if end < len(versions):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"page|{page + 1}"))

    if nav:
        keyboard.append(nav)

    await message.reply_text(
        f"Chọn branch (Page {page + 1})",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name = query.data
    project = next(p for p in projects if p["name"] == name)

    project_dir = os.path.join(BASE_DIR, name)

    msg = await query.message.reply_text("⏳ Đang load branch...")

    if not os.path.isdir(project_dir):
        if not clone_repo(project["repo"], project_dir):
            await msg.edit_text("❌ Clone fail")
            return

    versions = await get_versions(project_dir)

    if not versions:
        await msg.edit_text("❌ Không có branch")
        return

    context.user_data["versions"] = versions
    context.user_data["project"] = name

    await msg.delete()
    await show_versions(query.message, context, 0)


async def handle_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, page = query.data.split("|")
    await show_versions(query.message, context, int(page))


async def handle_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name, version = query.data.split("|")
    project = next(p for p in projects if p["name"] == name)

    await build_project(context.bot, query.message.chat_id, project, version)


def main():
    os.makedirs(BASE_DIR, exist_ok=True)

    # Tăng thời gian chờ mặc định cho toàn bộ ứng dụng
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(2000)  # Tăng lên 2000 giây (~33 phút)
        .write_timeout(2000)
        .connect_timeout(120)
        .pool_timeout(120)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_project, pattern="^[^|]+$"))
    app.add_handler(CallbackQueryHandler(handle_page, pattern="^page\\|"))
    app.add_handler(CallbackQueryHandler(handle_version, pattern=".+\\|.+"))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
