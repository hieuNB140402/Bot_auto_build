from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

import os
from config import *
from build_manager import load_projects, get_versions, build_project

projects = load_projects()


# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(p["name"], callback_data=p["name"])]
        for p in projects
    ]

    await update.message.reply_text(
        "Chọn project:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# CHỌN PROJECT
# =========================
async def handle_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name = query.data
    project = next(p for p in projects if p["name"] == name)

    project_dir = os.path.join(BASE_DIR, name)

    if not os.path.exists(project_dir):
        os.system(f"git clone {project['repo']} {project_dir}")

    versions = await get_versions(project_dir)

    if not versions:
        await query.message.reply_text("❌ Không có version")
        return

    keyboard = [
        [InlineKeyboardButton(v, callback_data=f"{name}|{v}")]
        for v in versions
    ]

    await query.message.reply_text(
        "Chọn version:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# BUILD
# =========================
async def handle_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name, version = query.data.split("|")

    project = next(p for p in projects if p["name"] == name)

    await build_project(context.bot, query.message.chat_id, project, version)


# =========================
# MAIN
# =========================
def main():
    os.makedirs(BASE_DIR, exist_ok=True)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_project, pattern="^[^|]+$"))
    app.add_handler(CallbackQueryHandler(handle_version, pattern=".+\\|.+"))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()