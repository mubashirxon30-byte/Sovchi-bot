#!/usr/bin/env python3
"""
Sovchilar Bot - Telegram matrimonial bot
To'lov: Paynet avtomatik + Karta manual
Premium: 45,000 so'm / 30 kun
Yangi: Faqat premium foydalanuvchilar yozisha oladi
"""

import logging
import json
import os
import hmac
import hashlib
from datetime import datetime, timedelta
from aiohttp import web
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== SOZLAMALAR ====================
BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
ADMIN_IDS        = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))
DB_FILE          = "users.json"

PREMIUM_NARX     = 45000      # so'm
PREMIUM_KUN      = 30         # kun

# --- Karta (manual) ---
KARTA_RAQAM      = "8600 1234 5678 9012"
KARTA_EGASI      = "Abdullayev Jasur"
KARTA_BANK       = "Uzcard"

# --- Paynet ---
PAYNET_MERCHANT_ID  = "YOUR_PAYNET_MERCHANT_ID"
PAYNET_SECRET_KEY   = "YOUR_PAYNET_SECRET_KEY"
PAYNET_BASE_URL     = "https://paynet.uz/paying/getPayPage"
PAYNET_WEBHOOK_PORT = 8080           # Webhook server porti
PAYNET_WEBHOOK_PATH = "/paynet/webhook"

# ==================== HOLATLAR ====================
(
    MAIN_MENU,
    REG_ISM, REG_YOSH, REG_JINS, REG_SHAHAR,
    REG_MAQSAD, REG_TAVSIF, REG_FOTO,
    BROWSE_PROFILES,
    TOLOV_WAIT_RECEIPT,
    CHAT_WRITE,
    ADMIN_MENU,
    ADMIN_BROADCAST,
) = range(13)

# ==================== DATABASE ====================
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"users": {}, "likes": {}, "matches": [], "payments": {}, "chats": {}}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(user_id):
    return load_db()["users"].get(str(user_id))

def save_user(user_id, data):
    db = load_db()
    db["users"][str(user_id)] = data
    save_db(db)

def get_all_users():
    return load_db()["users"]

def is_premium(user_id):
    u = get_user(user_id)
    if not u or not u.get("premium_exp"):
        return False
    try:
        return datetime.now() < datetime.fromisoformat(u["premium_exp"])
    except:
        return False

def activate_premium(user_id, days=PREMIUM_KUN):
    db = load_db()
    uid = str(user_id)
    if uid not in db["users"]:
        return False
    exp = datetime.now() + timedelta(days=days)
    db["users"][uid]["premium"]     = True
    db["users"][uid]["premium_exp"] = exp.isoformat()
    save_db(db)
    return exp

def add_like(from_id, to_id):
    db = load_db()
    fl = str(from_id)
    tl = str(to_id)
    if fl not in db["likes"]:
        db["likes"][fl] = []
    if tl not in db["likes"][fl]:
        db["likes"][fl].append(tl)
    is_match = tl in db["likes"] and fl in db["likes"].get(tl, [])
    if is_match:
        pair = sorted([fl, tl])
        if pair not in db["matches"]:
            db["matches"].append(pair)
    save_db(db)
    return is_match

def get_liked_ids(user_id):
    return load_db()["likes"].get(str(user_id), [])

def get_next_profile(uid, jins):
    db = load_db()
    liked = get_liked_ids(uid)
    opposite = "ayol" if jins == "erkak" else "erkak"
    for tid, td in db["users"].items():
        if (tid != str(uid)
                and td.get("jins") == opposite
                and td.get("tasdiqlangan")
                and tid not in liked):
            return tid, td
    return None, None

def save_payment_record(user_id, method, transaction_id=None, photo_id=None):
    db = load_db()
    if "payments" not in db:
        db["payments"] = {}
    db["payments"][str(user_id)] = {
        "method": method,
        "transaction_id": transaction_id,
        "photo_id": photo_id,
        "sana": datetime.now().isoformat(),
        "holat": "kutmoqda"
    }
    save_db(db)

# ==================== PAYNET HELPERS ====================
def paynet_generate_link(user_id, amount=PREMIUM_NARX):
    """Paynet to'lov havolasini yaratish"""
    order_id = f"SOV_{user_id}_{int(datetime.now().timestamp())}"
    # Paynet signature
    sign_str = f"{PAYNET_MERCHANT_ID}{order_id}{amount}{PAYNET_SECRET_KEY}"
    signature = hashlib.md5(sign_str.encode()).hexdigest()
    
    link = (
        f"{PAYNET_BASE_URL}"
        f"?merchant={PAYNET_MERCHANT_ID}"
        f"&amount={amount}"
        f"&order={order_id}"
        f"&currency=UZS"
        f"&description=Sovchilar+Premium+{PREMIUM_KUN}+kun"
        f"&sign={signature}"
    )
    # Order ID ni saqlash (webhook uchun)
    db = load_db()
    if "paynet_orders" not in db:
        db["paynet_orders"] = {}
    db["paynet_orders"][order_id] = str(user_id)
    save_db(db)
    return link, order_id

def paynet_verify_webhook(data: dict) -> bool:
    """Paynet webhookni tekshirish"""
    received_sign = data.get("sign", "")
    merchant      = data.get("merchant", "")
    order_id      = data.get("order", "")
    amount        = data.get("amount", "")
    status        = data.get("status", "")
    sign_str = f"{merchant}{order_id}{amount}{status}{PAYNET_SECRET_KEY}"
    expected = hashlib.md5(sign_str.encode()).hexdigest()
    return hmac.compare_digest(received_sign, expected)

# ==================== KLAVIATURALAR ====================
def main_menu_kb(registered=False, premium=False):
    if not registered:
        return ReplyKeyboardMarkup([
            ["📝 Ro'yxatdan o'tish"],
            ["ℹ️ Bot haqida", "📞 Aloqa"]
        ], resize_keyboard=True)
    if premium:
        return ReplyKeyboardMarkup([
            ["👤 Profilim", "✏️ Tahrirlash"],
            ["💑 Profillarni ko'rish", "❤️ Liklarim"],
            ["💬 Xabar yozish", "⭐ Premium faol"],
            ["📞 Aloqa"]
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["👤 Profilim", "✏️ Tahrirlash"],
        ["💑 Profillarni ko'rish", "❤️ Liklarim"],
        ["💳 Premium olish", "📞 Aloqa"]
    ], resize_keyboard=True)

def jins_kb():
    return ReplyKeyboardMarkup([["👨 Erkak", "👩 Ayol"]], resize_keyboard=True, one_time_keyboard=True)

def maqsad_kb():
    return ReplyKeyboardMarkup([
        ["💍 Jiddiy munosabat (nikoh)"],
        ["🤝 Tanishish"]
    ], resize_keyboard=True, one_time_keyboard=True)

def profile_kb(target_id, premium=False):
    rows = [[
        InlineKeyboardButton("❤️ Like", callback_data=f"like_{target_id}"),
        InlineKeyboardButton("👎 O'tkazish", callback_data=f"skip_{target_id}"),
    ]]
    if premium:
        rows.append([InlineKeyboardButton("💬 Xabar yozish", callback_data=f"write_{target_id}")])
    rows.append([InlineKeyboardButton("🚫 Shikoyat", callback_data=f"report_{target_id}")])
    return InlineKeyboardMarkup(rows)

def tolov_kb(paynet_link):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟠 Paynet orqali to'lash", url=paynet_link)],
        [InlineKeyboardButton("💳 Karta orqali (manual)", callback_data="pay_karta")],
        [InlineKeyboardButton("✅ Chek yubordim", callback_data="pay_receipt")],
    ])

def admin_kb():
    return ReplyKeyboardMarkup([
        ["👥 Foydalanuvchilar", "📊 Statistika"],
        ["💰 To'lovlar", "📢 Xabar yuborish"],
        ["✅ Profillar", "🔙 Asosiy menyu"]
    ], resize_keyboard=True)

# ==================== PROFIL FORMATLASH ====================
def fmt_profile(u, show_contact=False):
    je = "👨" if u.get("jins") == "erkak" else "👩"
    me = "💍" if "nikoh" in u.get("maqsad", "").lower() else "🤝"
    badge = "⭐ " if u.get("premium") and is_premium(u.get("user_id", 0)) else ""
    t = (
        f"{je} {badge}*{u['ism']}*, {u['yosh']} yosh\n"
        f"📍 {u['shahar']}\n"
        f"{me} {u['maqsad']}\n\n"
        f"📝 *Haqida:*\n{u['tavsif']}\n"
    )
    if show_contact and u.get("username"):
        t += f"\n📱 Telegram: @{u['username']}"
    return t

async def send_profile_msg(context, chat_id, udata, target_id, premium=False):
    txt = fmt_profile(udata)
    kb  = profile_kb(target_id, premium=premium)
    try:
        if udata.get("foto_id"):
            await context.bot.send_photo(chat_id=chat_id, photo=udata["foto_id"],
                                          caption=txt, parse_mode="Markdown", reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=chat_id, text=txt,
                                            parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"send_profile_msg: {e}")

# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = get_user(uid)
    prem = is_premium(uid)
    if user:
        badge = "⭐ *Premium*" if prem else "🆓 Bepul"
        await update.message.reply_text(
            f"👋 Qaytib keldingiz, *{user['ism']}*!\n{badge}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(registered=True, premium=prem)
        )
    else:
        await update.message.reply_text(
            "💍 *Sovchilar Botiga Xush Kelibsiz!*\n\n"
            "✅ Profil yarating\n"
            "💑 Profillarni ko'ring\n"
            "💬 Like va xabar yozing\n\n"
            "⭐ *Premium — 45,000 so'm/oy:*\n"
            "• Profillarni ko'rish\n"
            "• Xabar yozish\n"
            "• Kontaktni ko'rish\n"
            "• Cheksiz like\n\n"
            "👇 Boshlash uchun ro'yxatdan o'ting",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(registered=False)
        )
    return MAIN_MENU

# ==================== ASOSIY MENYU ====================
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid  = update.effective_user.id
    user = get_user(uid)
    prem = is_premium(uid)

    # --- Ro'yxatdan o'tish ---
    if text == "📝 Ro'yxatdan o'tish":
        await update.message.reply_text("📝 Ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
        return REG_ISM

    # --- Profilim ---
    elif text == "👤 Profilim":
        if user:
            exp_str = ""
            if prem and user.get("premium_exp"):
                try:
                    exp_dt = datetime.fromisoformat(user["premium_exp"])
                    qolgan = (exp_dt - datetime.now()).days
                    exp_str = f"\n⭐ Premium: {qolgan} kun qoldi"
                except: pass
            await update.message.reply_text(f"📋 *Profilingiz*{exp_str}", parse_mode="Markdown")
            await send_profile_msg(context, update.effective_chat.id, user, uid)
        return MAIN_MENU

    # --- Tahrirlash ---
    elif text == "✏️ Tahrirlash":
        db = load_db()
        if str(uid) in db["users"]:
            old = db["users"][str(uid)]
            context.user_data["old_premium"] = {
                "premium": old.get("premium", False),
                "premium_exp": old.get("premium_exp")
            }
            del db["users"][str(uid)]
            save_db(db)
        await update.message.reply_text("✏️ Profilni qayta to'ldiramiz.\nIsmingizni kiriting:",
                                         reply_markup=ReplyKeyboardRemove())
        return REG_ISM

    # --- Profillarni ko'rish ---
    elif text == "💑 Profillarni ko'rish":
        if not user:
            await update.message.reply_text("Avval ro'yxatdan o'ting!")
            return MAIN_MENU
        if not user.get("tasdiqlangan"):
            await update.message.reply_text("⏳ Profilingiz hali tasdiqlanmagan.")
            return MAIN_MENU
        if not prem:
            await _premium_taklif(update)
            return MAIN_MENU
        tid, tuser = get_next_profile(uid, user.get("jins", "erkak"))
        if tuser:
            await update.message.reply_text("💑 Profillarni ko'rish:", reply_markup=ReplyKeyboardRemove())
            await send_profile_msg(context, update.effective_chat.id, tuser, tid, premium=True)
        else:
            await update.message.reply_text("😔 Hozircha yangi profil yo'q.",
                                             reply_markup=main_menu_kb(registered=True, premium=True))
        return BROWSE_PROFILES

    # --- Liklarim ---
    elif text == "❤️ Liklarim":
        liked = [l for l in get_liked_ids(uid) if not l.startswith("skip_")]
        await update.message.reply_text(f"❤️ Siz {len(liked)} ta profilga like bossiz.")
        return MAIN_MENU

    # --- Xabar yozish ---
    elif text == "💬 Xabar yozish":
        if not prem:
            await _premium_taklif(update)
            return MAIN_MENU
        # Match bo'lgan foydalanuvchilar ro'yxati
        db = load_db()
        my_matches = [pair for pair in db.get("matches", []) if str(uid) in pair]
        if not my_matches:
            await update.message.reply_text(
                "💬 Hali o'zaro like bo'lgan foydalanuvchi yo'q.\n"
                "Profillarni ko'rib like bosing, match bo'lgach yozishingiz mumkin!"
            )
            return MAIN_MENU
        buttons = []
        for pair in my_matches[:10]:
            other_id = [p for p in pair if p != str(uid)][0]
            other    = get_user(int(other_id))
            if other:
                buttons.append([InlineKeyboardButton(
                    f"💬 {other['ism']}, {other['yosh']} yosh",
                    callback_data=f"chat_{other_id}"
                )])
        buttons.append([InlineKeyboardButton("❌ Yopish", callback_data="chat_close")])
        await update.message.reply_text(
            "💬 *Kimga xabar yozmoqchisiz?*\n_(Faqat o'zaro like bo'lganlar)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return MAIN_MENU

    # --- Premium olish ---
    elif text == "💳 Premium olish":
        await _premium_sahifa(update, context, uid)
        return MAIN_MENU

    # --- Premium faol ---
    elif text == "⭐ Premium faol":
        if prem and user and user.get("premium_exp"):
            try:
                exp_dt  = datetime.fromisoformat(user["premium_exp"])
                qolgan  = (exp_dt - datetime.now()).days
                await update.message.reply_text(
                    f"⭐ *Premium faol*\n\n"
                    f"Qolgan kunlar: *{qolgan} kun*\n"
                    f"Tugash sanasi: {user['premium_exp'][:10]}",
                    parse_mode="Markdown"
                )
            except:
                await update.message.reply_text("⭐ Premium faol.")
        return MAIN_MENU

    elif text == "📞 Aloqa":
        await update.message.reply_text("📞 Admin: @admin_username")
        return MAIN_MENU

    elif text == "ℹ️ Bot haqida":
        await update.message.reply_text(
            "ℹ️ *Sovchilar Bot*\n\nHalol va jiddiy munosabat uchun platforma.\n"
            "Barcha profillar admin tomonidan tasdiqlanadi.",
            parse_mode="Markdown"
        )
        return MAIN_MENU

    elif text == "🔧 Admin panel" and uid in ADMIN_IDS:
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode="Markdown", reply_markup=admin_kb())
        return ADMIN_MENU

    return MAIN_MENU

async def _premium_taklif(update):
    await update.message.reply_text(
        "🔒 Bu funksiya faqat *Premium* foydalanuvchilar uchun!\n\n"
        "⭐ *Premium — 45,000 so'm / oy*\n"
        "• Barcha profillarni ko'rish\n"
        "• Xabar yozish (match bo'lgandan keyin)\n"
        "• Kontaktni ko'rish\n"
        "• Cheksiz like\n\n"
        "👇 *Premium olish* tugmasini bosing",
        parse_mode="Markdown"
    )

async def _premium_sahifa(update, context, uid):
    paynet_link, order_id = paynet_generate_link(uid, PREMIUM_NARX)
    await update.message.reply_text(
        f"⭐ *PREMIUM — {PREMIUM_NARX:,} so'm / {PREMIUM_KUN} kun*\n\n"
        f"To'lov usulini tanlang:\n\n"
        f"🟠 *Paynet* — avtomatik, tezkor\n"
        f"💳 *Karta* — qo'lda tasdiqlash (1-2 soat)\n\n"
        f"📌 Buyurtma ID: `{order_id}`",
        parse_mode="Markdown",
        reply_markup=tolov_kb(paynet_link)
    )

# ==================== RO'YXATDAN O'TISH ====================
async def reg_ism(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ism = update.message.text.strip()
    if not (2 <= len(ism) <= 50):
        await update.message.reply_text("❌ Ism 2-50 harf bo'lsin:")
        return REG_ISM
    context.user_data["reg"] = {"ism": ism}
    await update.message.reply_text(f"✅ *{ism}*\n\nYoshingizni kiriting:", parse_mode="Markdown")
    return REG_YOSH

async def reg_yosh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        yosh = int(update.message.text.strip())
        assert 18 <= yosh <= 70
    except:
        await update.message.reply_text("❌ Yosh 18-70 orasida bo'lsin:")
        return REG_YOSH
    context.user_data["reg"]["yosh"] = yosh
    await update.message.reply_text("✅ Jinsingizni tanlang:", reply_markup=jins_kb())
    return REG_JINS

async def reg_jins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if "Erkak" in t:   jins = "erkak"
    elif "Ayol" in t:  jins = "ayol"
    else:
        await update.message.reply_text("Tugmadan tanlang:", reply_markup=jins_kb())
        return REG_JINS
    context.user_data["reg"]["jins"] = jins
    await update.message.reply_text("✅ Shahringizni kiriting:", reply_markup=ReplyKeyboardRemove())
    return REG_SHAHAR

async def reg_shahar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    shahar = update.message.text.strip()
    if len(shahar) < 2:
        await update.message.reply_text("To'g'ri shahar nomini kiriting:")
        return REG_SHAHAR
    context.user_data["reg"]["shahar"] = shahar
    await update.message.reply_text("✅ Maqsadingizni tanlang:", reply_markup=maqsad_kb())
    return REG_MAQSAD

async def reg_maqsad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if "nikoh" in t.lower() or "jiddiy" in t.lower():  maqsad = "Jiddiy munosabat (nikoh)"
    elif "tanish" in t.lower():                         maqsad = "Tanishish"
    else:
        await update.message.reply_text("Tugmadan tanlang:", reply_markup=maqsad_kb())
        return REG_MAQSAD
    context.user_data["reg"]["maqsad"] = maqsad
    await update.message.reply_text("✅ O'zingiz haqingizda yozing:", reply_markup=ReplyKeyboardRemove())
    return REG_TAVSIF

async def reg_tavsif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tavsif = update.message.text.strip()
    if len(tavsif) < 10:
        await update.message.reply_text("Kamida 10 ta belgi kiriting:")
        return REG_TAVSIF
    context.user_data["reg"]["tavsif"] = tavsif[:500]
    skip_kb = ReplyKeyboardMarkup([["⏭️ Fotosiz davom etish"]], resize_keyboard=True)
    await update.message.reply_text("✅ Rasmingizni yuboring:", reply_markup=skip_kb)
    return REG_FOTO

async def reg_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    username = update.effective_user.username
    if update.message.photo:
        foto_id = update.message.photo[-1].file_id
    elif update.message.text and "Fotosiz" in update.message.text:
        foto_id = None
    else:
        await update.message.reply_text("Rasm yuboring yoki o'tkazib yuboring:")
        return REG_FOTO

    reg = context.user_data.get("reg", {})
    reg.update({
        "foto_id": foto_id, "username": username,
        "tasdiqlangan": False,
        "sana": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "user_id": uid, "premium": False, "premium_exp": None
    })
    old = context.user_data.get("old_premium", {})
    if old.get("premium"):
        reg["premium"]     = old["premium"]
        reg["premium_exp"] = old["premium_exp"]
    save_user(uid, reg)

    await update.message.reply_text(
        "🎉 *Profil yaratildi!*\n\n⏳ Admin tasdiqlashini kuting 🙏",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(registered=True, premium=is_premium(uid))
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🆕 *Yangi profil!*\n\n👤 {reg['ism']}, {reg['yosh']} yosh | {reg['shahar']}\n🆔 `{uid}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_{uid}"),
                    InlineKeyboardButton("❌ Rad etish",  callback_data=f"reject_{uid}")
                ]])
            )
        except Exception as e:
            logger.error(e)
    return MAIN_MENU

# ==================== TO'LOV ====================
async def tolov_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = update.effective_user.id
    data = query.data

    if data == "pay_karta":
        await query.message.reply_text(
            f"💳 *Karta orqali to'lash*\n\n"
            f"Karta: `{KARTA_RAQAM}`\n"
            f"Egasi: *{KARTA_EGASI}* ({KARTA_BANK})\n"
            f"Miqdor: *{PREMIUM_NARX:,} so'm*\n\n"
            f"📸 To'lovdan so'ng chek yuboring.",
            parse_mode="Markdown"
        )
        return TOLOV_WAIT_RECEIPT

    elif data == "pay_receipt":
        await query.message.reply_text(
            "📸 To'lov chekini (screenshot) yuboring:",
            reply_markup=ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)
        )
        return TOLOV_WAIT_RECEIPT

    return MAIN_MENU

async def tolov_chek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if update.message.text == "❌ Bekor qilish":
        await update.message.reply_text("Bekor qilindi.",
                                         reply_markup=main_menu_kb(registered=True, premium=is_premium(uid)))
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("📸 Chek rasmini yuboring:")
        return TOLOV_WAIT_RECEIPT

    photo_id = update.message.photo[-1].file_id
    save_payment_record(uid, "karta", photo_id=photo_id)
    user = get_user(uid)

    await update.message.reply_text(
        "✅ *Chek qabul qilindi!*\n\n⏳ Admin 1-2 soat ichida tasdiqlaydi.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(registered=True, premium=False)
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id, photo=photo_id,
                caption=(f"💰 *Yangi to'lov cheki!*\n\n"
                         f"👤 {user.get('ism','?')}, {user.get('yosh','?')} yosh\n"
                         f"🆔 `{uid}`\n💵 {PREMIUM_NARX:,} so'm"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Premiumni yoqish", callback_data=f"prem_ok_{uid}"),
                    InlineKeyboardButton("❌ Rad etish",        callback_data=f"prem_no_{uid}")
                ]])
            )
        except Exception as e:
            logger.error(e)
    return MAIN_MENU

# ==================== BROWSE ====================
async def browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = update.effective_user.id
    data = query.data
    user = get_user(uid)
    prem = is_premium(uid)

    if data.startswith("like_"):
        tid      = data.split("_")[1]
        is_match = add_like(uid, tid)
        if is_match:
            tuser      = get_user(int(tid))
            match_txt  = "🎉 *O'ZARO LIKE! Moslik topildi!*\n\n" + fmt_profile(tuser, show_contact=True)
            try:
                if query.message.caption:
                    await query.edit_message_caption(caption=match_txt, parse_mode="Markdown")
                else:
                    await query.edit_message_text(text=match_txt, parse_mode="Markdown")
            except: pass
            try:
                await context.bot.send_message(int(tid),
                    "🎉 *O'ZARO LIKE! Moslik topildi!*\n\n" + fmt_profile(user, show_contact=True),
                    parse_mode="Markdown")
            except: pass
        else:
            await query.answer("❤️ Like bosildi!")

        tid2, tuser2 = get_next_profile(uid, user.get("jins","erkak"))
        if tuser2:
            await send_profile_msg(context, query.message.chat_id, tuser2, tid2, premium=prem)
        else:
            await context.bot.send_message(query.message.chat_id, "✨ Yangi profil yo'q!",
                reply_markup=main_menu_kb(registered=True, premium=prem))

    elif data.startswith("skip_"):
        tid = data.split("_")[1]
        db  = load_db()
        if str(uid) not in db["likes"]: db["likes"][str(uid)] = []
        if f"skip_{tid}" not in db["likes"][str(uid)]:
            db["likes"][str(uid)].append(f"skip_{tid}")
        save_db(db)
        tid2, tuser2 = get_next_profile(uid, user.get("jins","erkak"))
        if tuser2:
            await send_profile_msg(context, query.message.chat_id, tuser2, tid2, premium=prem)
        else:
            await context.bot.send_message(query.message.chat_id, "✨ Barcha profillarni ko'rdingiz!",
                reply_markup=main_menu_kb(registered=True, premium=prem))

    elif data.startswith("write_"):
        # Profildan to'g'ridan xabar yozish (faqat premium)
        if not prem:
            await query.answer("⭐ Faqat Premium uchun!", show_alert=True)
            return
        tid = data.split("_")[1]
        tuser = get_user(int(tid))
        # Match tekshirish
        db     = load_db()
        liked  = get_liked_ids(uid)
        if tid not in liked:
            await query.answer("Avval like bosing!", show_alert=True)
            return
        if not (str(tid) in db["likes"] and str(uid) in db["likes"].get(str(tid), [])):
            await query.answer("O'zaro like bo'lgandagina yozishingiz mumkin!", show_alert=True)
            return
        context.user_data["chat_target"] = tid
        await context.bot.send_message(uid,
            f"💬 *{tuser['ism']}* ga xabar yozing:\n_(Bekor qilish: /stop)_",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)
        )
        return CHAT_WRITE

    elif data.startswith("chat_") and not data.startswith("chat_close"):
        tid   = data.split("_")[1]
        tuser = get_user(int(tid))
        if not prem:
            await query.answer("⭐ Faqat Premium uchun!", show_alert=True)
            return
        context.user_data["chat_target"] = tid
        await query.message.reply_text(
            f"💬 *{tuser['ism']}* ga xabar yozing:\n_(Bekor qilish: Tugmani bosing)_",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)
        )
        return CHAT_WRITE

    elif data == "chat_close":
        await query.message.delete()

    elif data.startswith("report_"):
        await query.answer("🚫 Shikoyat yuborildi!", show_alert=True)
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id,
                    f"🚫 Shikoyat!\nKimdan: {uid}\nKimga: {data.split('_')[1]}")
            except: pass

# ==================== CHAT ====================
async def chat_write_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text
    prem = is_premium(uid)

    if text == "❌ Bekor qilish" or text == "/stop":
        await update.message.reply_text("Bekor qilindi.",
            reply_markup=main_menu_kb(registered=True, premium=prem))
        context.user_data.pop("chat_target", None)
        return MAIN_MENU

    if not prem:
        await update.message.reply_text("⭐ Xabar yozish uchun Premium kerak!",
            reply_markup=main_menu_kb(registered=True, premium=False))
        return MAIN_MENU

    target_id = context.user_data.get("chat_target")
    if not target_id:
        await update.message.reply_text("Kimga yozishni tanlang.",
            reply_markup=main_menu_kb(registered=True, premium=True))
        return MAIN_MENU

    user  = get_user(uid)
    tuser = get_user(int(target_id))

    # Match tekshirish
    db    = load_db()
    liked = get_liked_ids(uid)
    is_matched = (
        str(target_id) in liked and
        str(target_id) in db["likes"] and
        str(uid) in db["likes"].get(str(target_id), [])
    )
    if not is_matched:
        await update.message.reply_text("❌ Faqat o'zaro like bo'lgan odamlarga yozishingiz mumkin!",
            reply_markup=main_menu_kb(registered=True, premium=True))
        return MAIN_MENU

    try:
        sender_name = user.get("ism", "Noma'lum")
        await context.bot.send_message(
            int(target_id),
            f"💬 *{sender_name}* dan xabar:\n\n{text}\n\n"
            f"_(Javob berish uchun botga kiring va Xabar yozish tugmasini bosing)_",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ Xabar *{tuser.get('ism','?')}* ga yuborildi!\n\nYana xabar yozing yoki menyuga qayting:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([
                ["❌ Menyuga qaytish"]
            ], resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"chat yuborishda xato: {e}")
        await update.message.reply_text("❌ Xabar yuborishda xato. Keyinroq urinib ko'ring.")

    return CHAT_WRITE

# ==================== ADMIN CALLBACK ====================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    data = query.data

    if data.startswith("approve_"):
        tid = data.split("_")[1]
        db  = load_db()
        if tid in db["users"]:
            db["users"][tid]["tasdiqlangan"] = True
            save_db(db)
            await query.edit_message_text("✅ Profil tasdiqlandi!")
            try:
                await context.bot.send_message(int(tid),
                    "🎉 *Profilingiz tasdiqlandi!*\n\nEndi profillarni ko'rishingiz mumkin.",
                    parse_mode="Markdown")
            except: pass

    elif data.startswith("reject_"):
        tid = data.split("_")[1]
        db  = load_db()
        if tid in db["users"]:
            del db["users"][tid]
            save_db(db)
            await query.edit_message_text("❌ Profil rad etildi.")
            try:
                await context.bot.send_message(int(tid), "❌ Profilingiz qabul qilinmadi.")
            except: pass

    elif data.startswith("prem_ok_"):
        tid = data.split("_")[2]
        exp = activate_premium(int(tid), PREMIUM_KUN)
        db  = load_db()
        if "payments" in db and tid in db["payments"]:
            db["payments"][tid]["holat"] = "tasdiqlangan"
            save_db(db)
        try:
            await query.edit_message_caption(caption="✅ Premium faollashtirildi!")
        except:
            await query.edit_message_text("✅ Premium faollashtirildi!")
        try:
            await context.bot.send_message(int(tid),
                f"🎉 *Premium faollashtirildi!*\n\n"
                f"⭐ {PREMIUM_KUN} kun amal qiladi.\n"
                f"Tugash: {str(exp)[:10]}\n\n"
                f"Endi barcha profillarni ko'rishingiz va xabar yozishingiz mumkin!",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(registered=True, premium=True)
            )
        except: pass

    elif data.startswith("prem_no_"):
        tid = data.split("_")[2]
        db  = load_db()
        if "payments" in db and tid in db["payments"]:
            db["payments"][tid]["holat"] = "rad_etilgan"
            save_db(db)
        try:
            await query.edit_message_caption(caption="❌ To'lov rad etildi.")
        except:
            await query.edit_message_text("❌ To'lov rad etildi.")
        try:
            await context.bot.send_message(int(tid),
                "❌ To'lovingiz tasdiqlanmadi. Admin: @admin_username")
        except: pass

# ==================== ADMIN MENYU ====================
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid  = update.effective_user.id
    if uid not in ADMIN_IDS:
        return MAIN_MENU

    if text == "👥 Foydalanuvchilar":
        users    = get_all_users()
        confirmed = sum(1 for u in users.values() if u.get("tasdiqlangan"))
        prems    = sum(1 for u in users.values() if is_premium(u.get("user_id",0)))
        await update.message.reply_text(
            f"👥 Jami: {len(users)}\n✅ Tasdiqlangan: {confirmed}\n"
            f"⏳ Kutmoqda: {len(users)-confirmed}\n⭐ Premium: {prems}"
        )

    elif text == "📊 Statistika":
        db     = load_db()
        pays   = db.get("payments", {})
        ok_pay = sum(1 for p in pays.values() if p.get("holat") == "tasdiqlangan")
        await update.message.reply_text(
            f"📊 *Statistika:*\n\n"
            f"👥 Foydalanuvchilar: {len(db['users'])}\n"
            f"❤️ Liklarlar: {sum(len(v) for v in db['likes'].values())}\n"
            f"💑 Matchlar: {len(db['matches'])}\n"
            f"💰 To'lovlar: {len(pays)} (✅ {ok_pay})",
            parse_mode="Markdown"
        )

    elif text == "💰 To'lovlar":
        db      = load_db()
        pays    = db.get("payments", {})
        pending = [(tid, p) for tid, p in pays.items() if p.get("holat") == "kutmoqda"]
        if pending:
            await update.message.reply_text(f"⏳ Kutmoqda: {len(pending)} ta to'lov")
            for tid, p in pending[:5]:
                u = get_user(int(tid))
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"prem_ok_{tid}"),
                    InlineKeyboardButton("❌ Rad etish",  callback_data=f"prem_no_{tid}")
                ]])
                if p.get("photo_id"):
                    await context.bot.send_photo(uid, photo=p["photo_id"],
                        caption=f"💰 {u.get('ism','?')} | 🆔 `{tid}`",
                        parse_mode="Markdown", reply_markup=kb)
                else:
                    await context.bot.send_message(uid,
                        f"💰 {u.get('ism','?')} | 🆔 `{tid}`",
                        parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text("✅ Kutmoqda to'lov yo'q.")

    elif text == "📢 Xabar yuborish":
        await update.message.reply_text("📢 Xabarni yozing:",
            reply_markup=ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True))
        return ADMIN_BROADCAST

    elif text == "✅ Profillar":
        db      = load_db()
        pending = [(tid, u) for tid, u in db["users"].items() if not u.get("tasdiqlangan")]
        if pending:
            await update.message.reply_text(f"⏳ {len(pending)} ta profil kutmoqda:")
            for tid, u in pending[:5]:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_{tid}"),
                    InlineKeyboardButton("❌ Rad etish",  callback_data=f"reject_{tid}")
                ]])
                txt = f"👤 {u['ism']}, {u['yosh']} yosh | {u['shahar']}\n🆔 `{tid}`"
                if u.get("foto_id"):
                    await context.bot.send_photo(uid, photo=u["foto_id"],
                        caption=txt, parse_mode="Markdown", reply_markup=kb)
                else:
                    await context.bot.send_message(uid, txt, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text("✅ Tasdiqlanmagan profil yo'q.")

    elif text == "🔙 Asosiy menyu":
        await update.message.reply_text("Asosiy menyu:",
            reply_markup=main_menu_kb(registered=True, premium=is_premium(uid)))
        return MAIN_MENU

    return ADMIN_MENU

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    if uid not in ADMIN_IDS:
        return MAIN_MENU
    text = update.message.text
    if text == "❌ Bekor qilish":
        await update.message.reply_text("Bekor.", reply_markup=admin_kb())
        return ADMIN_MENU
    users = get_all_users()
    sent  = 0
    for tid in users:
        try:
            await context.bot.send_message(int(tid), f"📢 *Admin xabari:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except: pass
    await update.message.reply_text(f"✅ {sent}/{len(users)} ta yuborildi.", reply_markup=admin_kb())
    return ADMIN_MENU

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_IDS:
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode="Markdown", reply_markup=admin_kb())
        return ADMIN_MENU
    return MAIN_MENU

# ==================== PAYNET WEBHOOK SERVER ====================
async def paynet_webhook_handler(request: web.Request):
    """Paynet avtomatik to'lov tasdiqlash webhook"""
    try:
        data = await request.json()
        logger.info(f"Paynet webhook: {data}")

        # Imzoni tekshirish
        if not paynet_verify_webhook(data):
            logger.warning("Paynet: noto'g'ri imzo!")
            return web.Response(status=400, text="Invalid signature")

        status   = str(data.get("status", ""))
        order_id = str(data.get("order", ""))

        # Faqat muvaffaqiyatli to'lovlar
        if status not in ("2", "success", "paid"):
            return web.Response(text="OK")

        # Order ID dan user_id topish
        db = load_db()
        uid = db.get("paynet_orders", {}).get(order_id)
        if not uid:
            logger.warning(f"Paynet: order topilmadi: {order_id}")
            return web.Response(text="OK")

        # Premium yoqish
        already = is_premium(int(uid))
        if not already:
            exp = activate_premium(int(uid), PREMIUM_KUN)
            save_payment_record(uid, "paynet", transaction_id=order_id)

            # Foydalanuvchiga xabar
            app = request.app["telegram_app"]
            await app.bot.send_message(
                int(uid),
                f"🎉 *To'lov qabul qilindi!*\n\n"
                f"⭐ Premium {PREMIUM_KUN} kun faollashtirildi!\n"
                f"Tugash sanasi: {str(exp)[:10]}\n\n"
                f"Endi barcha profillarni ko'rishingiz va xabar yozishingiz mumkin! 🎊",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(registered=True, premium=True)
            )
            # Adminga ham xabar
            for admin_id in ADMIN_IDS:
                try:
                    await app.bot.send_message(admin_id,
                        f"✅ *Avtomatik to'lov qabul qilindi*\n\n"
                        f"🆔 User: `{uid}`\n"
                        f"📋 Order: `{order_id}`\n"
                        f"💵 {PREMIUM_NARX:,} so'm",
                        parse_mode="Markdown")
                except: pass

        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Paynet webhook xato: {e}")
        return web.Response(status=500, text="Error")

# ==================== MAIN ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(tolov_callback, pattern="^pay_"),
                CallbackQueryHandler(browse_callback, pattern="^chat_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            REG_ISM:    [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_ism)],
            REG_YOSH:   [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_yosh)],
            REG_JINS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_jins)],
            REG_SHAHAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_shahar)],
            REG_MAQSAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_maqsad)],
            REG_TAVSIF: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_tavsif)],
            REG_FOTO:   [MessageHandler(filters.PHOTO | filters.TEXT, reg_foto)],
            BROWSE_PROFILES: [
                CallbackQueryHandler(browse_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            TOLOV_WAIT_RECEIPT: [
                CallbackQueryHandler(tolov_callback, pattern="^pay_"),
                MessageHandler(filters.PHOTO | filters.TEXT, tolov_chek),
            ],
            CHAT_WRITE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, chat_write_handler),
            ],
            ADMIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler),
            ],
            ADMIN_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_command),
            CommandHandler("stop",  start),
        ],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(approve|reject|prem_ok|prem_no)_"))

    # Paynet webhook server
    web_app = web.Application()
    web_app["telegram_app"] = app
    web_app.router.add_post(PAYNET_WEBHOOK_PATH, paynet_webhook_handler)

    async def on_startup(telegram_app):
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PAYNET_WEBHOOK_PORT)
        await site.start()
        logger.info(f"🌐 Paynet webhook: port {PAYNET_WEBHOOK_PORT}{PAYNET_WEBHOOK_PATH}")

    app.post_init = on_startup

    logger.info("🤖 Sovchilar Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
