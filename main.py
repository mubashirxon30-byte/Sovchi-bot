import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 8736539905
KARTA_RAQAMI = os.environ.get("Karta_raqami")
KANAL_USERNAME = "@Sovchi_uzbekiston"
TO_LOV_MIQDORI = "20,000 so'm"

logging.basicConfig(level=logging.INFO)

(JINS, ISM, YOSH, SHAHAR, BOY, KASB, MAQSAD, TALABLAR, RASM, TELEFON, TOLOV) = range(11)

JINS_KEYBOARD = [["👦 Yigit", "👧 Qiz"]]
SHAHAR_KEYBOARD = [["Toshkent", "Samarqand", "Buxoro"], ["Namangan", "Andijon", "Farg'ona"], ["Boshqa shahar"]]
MAQSAD_KEYBOARD = [["💍 Nikoh", "👫 Tanishish"]]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌸 *Sovchi Uzbekiston Botiga Xush Kelibsiz!*\n\nAnketa to'ldirib e'lon joylashtirishingiz mumkin.\n\n📋 Jarayon:\n1. Anketa to'ldirish\n2. To'lov: *20,000 so'm*\n3. E'lon kanalda chiqadi ✅",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["✅ Boshlash"]], resize_keyboard=True)
    )
    return JINS

async def jins_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Jinsingizni tanlang:", reply_markup=ReplyKeyboardMarkup(JINS_KEYBOARD, resize_keyboard=True))
    return ISM

async def ism_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["jins"] = update.message.text
    await update.message.reply_text("Ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    return YOSH

async def yosh_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ism"] = update.message.text
    await update.message.reply_text("Yoshingizni kiriting:")
    return SHAHAR

async def shahar_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["yosh"] = update.message.text
    await update.message.reply_text("Shahringizni tanlang:", reply_markup=ReplyKeyboardMarkup(SHAHAR_KEYBOARD, resize_keyboard=True))
    return BOY

async def boy_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["shahar"] = update.message.text
    await update.message.reply_text("Bo'yingizni kiriting (masalan: 170 sm):", reply_markup=ReplyKeyboardRemove())
    return KASB

async def kasb_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["boy"] = update.message.text
    await update.message.reply_text("Kasbingizni kiriting:")
    return MAQSAD

async def maqsad_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["kasb"] = update.message.text
    await update.message.reply_text("Maqsadingizni tanlang:", reply_markup=ReplyKeyboardMarkup(MAQSAD_KEYBOARD, resize_keyboard=True))
    return TALABLAR

async def talablar_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["maqsad"] = update.message.text
    await update.message.reply_text("Juftingizga talablaringizni yozing:", reply_markup=ReplyKeyboardRemove())
    return RASM

async def rasm_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["talablar"] = update.message.text
    await update.message.reply_text("📸 Rasmingizni yuboring:", reply_markup=ReplyKeyboardMarkup([["⏭ O'tkazib yuborish"]], resize_keyboard=True))
    return TELEFON

async def telefon_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["rasm"] = update.message.photo[-1].file_id
    else:
        context.user_data["rasm"] = None
    await update.message.reply_text("📞 Telefon raqamingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    return TOLOV

async def tolov_sorash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["telefon"] = update.message.text
    user = update.effective_user
    d = context.user_data
    anketa_text = (
        f"📋 *YANGI ANKETA*\n"
        f"👤 Telegram: @{user.username or 'Yoq'}\n"
        f"🆔 ID: `{user.id}`\n"
        f"⚥ Jins: {d.get('jins')}\n"
        f"📛 Ism: {d.get('ism')}\n"
        f"🎂 Yosh: {d.get('yosh')}\n"
        f"🏙 Shahar: {d.get('shahar')}\n"
        f"📏 Boy: {d.get('boy')}\n"
        f"💼 Kasb: {d.get('kasb')}\n"
        f"🎯 Maqsad: {d.get('maqsad')}\n"
        f"✨ Talablar: {d.get('talablar')}\n"
        f"📞 Telefon: {d.get('telefon')}\n"
        f"⏳ Tolov kutilmoqda..."
    )
    if d.get("rasm"):
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=d["rasm"], caption=anketa_text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=ADMIN_ID, text=anketa_text, parse_mode="Markdown")
    await update.message.reply_text(
        f"✅ *Anketangiz qabul qilindi!*\n\n💳 Karta: `{KARTA_RAQAMI}`\nMiqdor: *{TO_LOV_MIQDORI}*\n\nTolov chekini shu yerga yuboring 👇",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def chek_qabul(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        user = update.effective_user
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=f"💸 *TOLOV CHEKI*\n@{user.username or user.first_name}\nID: `{user.id}`", parse_mode="Markdown")
        await update.message.reply_text("✅ Chekingiz qabul qilindi!\n\n⏰ 1-2 soat ichida e'loningiz kanalda chiqadi. Rahmat! 🌸")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            JINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, jins_sorash)],
            ISM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ism_sorash)],
            YOSH: [MessageHandler(filters.TEXT & ~filters.COMMAND, yosh_sorash)],
            SHAHAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, shahar_sorash)],
            BOY: [MessageHandler(filters.TEXT & ~filters.COMMAND, boy_sorash)],
            KASB: [MessageHandler(filters.TEXT & ~filters.COMMAND, kasb_sorash)],
            MAQSAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, maqsad_sorash)],
            TALABLAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, talablar_sorash)],
            RASM: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, rasm_sorash)],
            TELEFON: [MessageHandler(filters.TEXT & ~filters.COMMAND, telefon_sorash)],
            TOLOV: [MessageHandler(filters.TEXT & ~filters.COMMAND, tolov_sorash)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.PHOTO, chek_qabul))
    print("Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
