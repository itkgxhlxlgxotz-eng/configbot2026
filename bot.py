# -*- coding: utf-8 -*-
"""
ربات فروش کانفینگ - فایل اصلی
اجرا: python bot.py
"""
import asyncio
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, Forbidden, BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
import database as db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BACK_TEXT = "🔙 بازگشت"

# ------------------------------------------------------------------ تعریف دکمه‌های ثابت
USER_BUTTONS = [
    ("buy_config", "🛒 خرید کانفینگ"),
    ("gift_code", "🎁 وارد کردن کد هدیه"),
    ("my_purchases", "📦 کانفینگ‌های خریداری‌شده"),
    ("charge_balance", "💳 شارژ حساب"),
    ("buy_points", "⭐️خرید با امتیاز"),
    ("my_points", "⭐️امتیاز های من"),
    ("referral", "👥 زیرمجموعه‌گیری"),
    ("support", "🛟 پشتیبانی"),
]

ADMIN_BUTTONS = [
    ("gift_create", "🎁 ساخت کد هدیه"),
    ("charge_requests", "💰 درخواست‌های شارژ"),
    ("broadcast", "📢 پیام همگانی"),
    ("bot_settings", "⚙️ تنظیمات ربات"),
    ("bot_stats", "📊 آمار ربات"),
    ("manage_packages", "📦 مدیریت پکیج‌ها"),
    ("panel_manage", "🛠 پنل مدیریت"),
    ("add_admin", "➕ افزودن ادمین"),
    ("add_channel", "💻افزودن کانال اجباری"),
    ("transfer_points", "⭐️انتقال امتیاز"),
    ("ban_user", "👨‍🔧مسدود کاربر"),
    ("unban_user", "👨‍🔧رفع مسدودیت کاربر"),
    ("user_stats", "🗽آمار کاربر"),
    ("button_style", "💻تغییر دکمه ظاهر ربات"),
]

USER_KEY2LABEL = dict(USER_BUTTONS)
ADMIN_KEY2LABEL = dict(ADMIN_BUTTONS)
LABEL2KEY = {}
for k, v in USER_BUTTONS + ADMIN_BUTTONS:
    LABEL2KEY[v] = k

ADMIN_ENTRY_LABEL = "👑 پنل ادمین"


# ==================================================================
#                          توابع کمکی کیبورد
# ==================================================================
def button_style():
    return db.get_setting("button_style", config.DEFAULT_BUTTON_STYLE)


def build_menu(buttons, is_admin_menu=False, extra_row_text=None, back=False):
    """buttons: لیست (key, label). بر اساس سبک تنظیم شده، کیبورد شیشه‌ای یا معمولی می‌سازد."""
    style = button_style()
    visible = [(k, l) for k, l in buttons if db.is_button_visible(k)]

    if style == "inline":
        rows = [[InlineKeyboardButton(l, callback_data=f"nv:{k}")] for k, l in visible]
        if extra_row_text:
            rows.append([InlineKeyboardButton(extra_row_text[1], callback_data=f"nv:{extra_row_text[0]}")])
        if back:
            rows.append([InlineKeyboardButton(BACK_TEXT, callback_data="nv:back")])
        return InlineKeyboardMarkup(rows)
    else:
        rows = [[KeyboardButton(l)] for k, l in visible]
        if extra_row_text:
            rows.append([KeyboardButton(extra_row_text[1])])
        if back:
            rows.append([KeyboardButton(BACK_TEXT)])
        return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def user_main_markup(user_id):
    extra = (ADMIN_ENTRY_LABEL, ADMIN_ENTRY_LABEL) if db.is_admin(user_id) else None
    # extra_row_text expects (key,label) - برای ادمین کلید خاص می‌سازیم
    style = button_style()
    visible = [(k, l) for k, l in USER_BUTTONS if db.is_button_visible(k)]
    customs = db.list_custom_buttons()
    if style == "inline":
        rows = [[InlineKeyboardButton(l, callback_data=f"nv:{k}")] for k, l in visible]
        for cb in customs:
            rows.append([InlineKeyboardButton(cb["text"], callback_data=f"cbtn:{cb['id']}")])
        if db.is_admin(user_id):
            rows.append([InlineKeyboardButton(ADMIN_ENTRY_LABEL, callback_data="nv:admin_main")])
        return InlineKeyboardMarkup(rows)
    else:
        rows = [[KeyboardButton(l)] for k, l in visible]
        for cb in customs:
            rows.append([KeyboardButton(cb["text"])])
        if db.is_admin(user_id):
            rows.append([KeyboardButton(ADMIN_ENTRY_LABEL)])
        return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_main_markup():
    return build_menu(ADMIN_BUTTONS, is_admin_menu=True, back=True)


async def send_menu(update_or_query, text, markup, edit=False):
    if edit and hasattr(update_or_query, "edit_message_text"):
        try:
            await update_or_query.edit_message_text(text, reply_markup=markup)
            return
        except BadRequest:
            pass
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=markup)
    else:
        await update_or_query.reply_text(text, reply_markup=markup)


# ==================================================================
#                       بررسی عضویت کانال اجباری
# ==================================================================
async def get_not_joined_channels(bot, user_id):
    not_joined = []
    for ch in db.list_force_channels():
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except TelegramError:
            # اگر ربات ادمین کانال نباشد یا کانال نامعتبر باشد از بررسی صرف‌نظر می‌شود
            continue
    return not_joined


def join_markup(channels):
    rows = []
    for ch in channels:
        uname = ch.lstrip("@")
        rows.append([InlineKeyboardButton(f"عضویت در {ch}", url=f"https://t.me/{uname}")])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data="nv:check_join")])
    return InlineKeyboardMarkup(rows)


async def ensure_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    not_joined = await get_not_joined_channels(context.bot, user_id)
    if not_joined:
        text = config.JOIN_REQUIRED_TEXT
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(text, reply_markup=join_markup(not_joined))
            except BadRequest:
                await update.callback_query.message.reply_text(text, reply_markup=join_markup(not_joined))
        else:
            await update.message.reply_text(text, reply_markup=join_markup(not_joined))
        return False
    return True


# ==================================================================
#                              /start
# ==================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referrer_id = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                rid = int(arg.replace("ref_", ""))
                if rid != user.id:
                    referrer_id = rid
            except ValueError:
                pass

    is_new = db.upsert_user(user.id, user.username, user.first_name, referrer_id)

    if db.is_banned(user.id):
        await update.message.reply_text("⛔️ شما توسط مدیریت مسدود شده‌اید.")
        return

    if is_new and referrer_id and db.get_user(referrer_id):
        db.add_points(referrer_id, config.REFERRAL_POINTS)
        try:
            await context.bot.send_message(
                referrer_id,
                f"🎉 یک کاربر جدید با لینک دعوت شما وارد ربات شد و {config.REFERRAL_POINTS} امتیاز به شما اضافه شد.",
            )
        except TelegramError:
            pass

    if not await ensure_joined(update, context):
        return

    context.user_data.clear()
    await update.message.reply_text(
        db.get_setting("welcome_text", config.WELCOME_TEXT),
        reply_markup=user_main_markup(user.id),
    )


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    not_joined = await get_not_joined_channels(context.bot, user_id)
    if not_joined:
        await query.answer("هنوز در همه کانال‌ها عضو نشده‌اید ❗️", show_alert=True)
        return
    await query.answer("عضویت شما تایید شد ✅")
    await query.edit_message_text(
        db.get_setting("welcome_text", config.WELCOME_TEXT),
    )
    await query.message.reply_text("منوی اصلی:", reply_markup=user_main_markup(user_id))


# ==================================================================
#                     نمایش لیست پکیج‌های کانفینگ
# ==================================================================
def cfg_packages_markup():
    rows = []
    for p in db.list_config_packages():
        label = f"{p['volume']}+{p['duration']}+{p['price']:,}تومان❗️"
        rows.append([InlineKeyboardButton(label, callback_data=f"bc:{p['id']}")])
    rows.append([InlineKeyboardButton(BACK_TEXT, callback_data="nv:back")])
    return InlineKeyboardMarkup(rows)


def pt_packages_markup():
    rows = []
    for p in db.list_point_packages():
        label = f"{p['points_price']}امتیاز+{p['volume']}+{p['duration']}❗️"
        rows.append([InlineKeyboardButton(label, callback_data=f"bp:{p['id']}")])
    rows.append([InlineKeyboardButton(BACK_TEXT, callback_data="nv:back")])
    return InlineKeyboardMarkup(rows)


async def show_buy_config(update, context):
    await send_menu(
        update.callback_query if update.callback_query else update,
        "لیست قیمت های کانفینگ⭐️\n\nپکیج مورد نظر خود را انتخاب کنید:",
        cfg_packages_markup(),
        edit=bool(update.callback_query),
    )


async def show_buy_points(update, context):
    await send_menu(
        update.callback_query if update.callback_query else update,
        "لیست قیمت های خرید با امتیاز⭐️\n\nپکیج مورد نظر خود را انتخاب کنید:",
        pt_packages_markup(),
        edit=bool(update.callback_query),
    )


async def select_config_package(update, context, pkg_id):
    pkg = db.get_config_package(pkg_id)
    query = update.callback_query
    if not pkg:
        await query.answer("این پکیج دیگر موجود نیست.", show_alert=True)
        return
    context.user_data["state"] = "await_receipt_config"
    context.user_data["pkg"] = dict(pkg)
    card = db.get_setting("card_number", config.DEFAULT_CARD_NUMBER)
    text = (
        f"✅ پکیج انتخابی: {pkg['volume']} + {pkg['duration']} + {pkg['price']:,} تومان\n\n"
        f"💳 مبلغ را به شماره کارت زیر واریز کرده و سپس عکس رسید پرداخت را همینجا ارسال کنید:\n\n"
        f"`{card}`"
    )
    await query.answer()
    await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def select_point_package(update, context, pkg_id):
    pkg = db.get_point_package(pkg_id)
    query = update.callback_query
    if not pkg:
        await query.answer("این پکیج دیگر موجود نیست.", show_alert=True)
        return
    user = db.get_user(update.effective_user.id)
    await query.answer()
    if user["points"] < pkg["points_price"]:
        await query.message.reply_text("موجودی خود را لطفا افزایش دهید👨‍💻")
        return
    db.deduct_points(user["user_id"], pkg["points_price"])
    price_text = f"{pkg['points_price']} امتیاز"
    title = f"{pkg['volume']} + {pkg['duration']}"
    purchase_id = db.create_purchase(user["user_id"], "point", title, price_text, None)
    db.set_purchase_status(purchase_id, "approved")
    await query.message.reply_text(
        "✅ خرید شما با موفقیت انجام شد و امتیاز مربوطه کسر گردید.\n"
        "منتظر دریافت کانفینگ باشید، پشتیبانی به زودی برای شما ارسال می‌کند."
    )
    await notify_admins_new_delivery(context, user, title, price_text, purchase_id)
    await post_to_sales_channel(context, title, price_text)


async def notify_admins_new_delivery(context, user, title, price_text, purchase_id):
    uname = f"@{user['username']}" if user["username"] else "ندارد"
    text = (
        f"📦 یک خرید با امتیاز نیاز به تحویل دارد\n\n"
        f"کاربر: {user['first_name']} ({uname})\n"
        f"آیدی عددی: `{user['user_id']}`\n"
        f"پکیج: {title}\n"
        f"مبلغ: {price_text}\n"
        f"شماره خرید: #{purchase_id}"
    )
    for admin_id in db.list_admins():
        try:
            await context.bot.send_message(admin_id, text, parse_mode=ParseMode.MARKDOWN)
        except TelegramError:
            pass


async def post_to_sales_channel(context, title, price_text):
    channel = db.get_setting("sales_channel", config.DEFAULT_SALES_CHANNEL)
    if not channel:
        return
    text = (
        "خرید جدید❗️🔥\n\n"
        f"حجم خریداری شده: {title}\n"
        f"قیمت پرداخت شده: {price_text}\n"
        f"ساعت خرید: {datetime.now().strftime('%H:%M')}\n"
        "وضعیت: تحویل داده شد\n"
        "جهت خرید به ربات زیر مراجعه کنید👨‍💻❤️\n"
        f" {config.SUPPORT_BOT_USERNAME}"
    )
    try:
        await context.bot.send_message(channel, text)
    except TelegramError as e:
        logger.warning("خطا در ارسال به کانال فروش: %s", e)


# ==================================================================
#                    دریافت عکس رسید (خرید کانفینگ / شارژ)
# ==================================================================
async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state not in ("await_receipt_config", "await_receipt_charge"):
        return  # مربوط به این هندلر نیست

    photo = update.message.photo[-1].file_id if update.message.photo else None
    doc = update.message.document.file_id if update.message.document else None
    file_id = photo or doc
    if not file_id:
        await update.message.reply_text("لطفا عکس یا فایل رسید را ارسال کنید.")
        return

    user = db.get_user(update.effective_user.id)
    uname = f"@{user['username']}" if user["username"] else "ندارد"

    if state == "await_receipt_config":
        pkg = context.user_data.get("pkg")
        title = f"{pkg['volume']} + {pkg['duration']}"
        price_text = f"{pkg['price']:,} تومان"
        purchase_id = db.create_purchase(user["user_id"], "config", title, price_text, file_id)
        caption = (
            f"🧾 رسید پرداخت جدید\n\n"
            f"کاربر: {user['first_name']} ({uname})\n"
            f"آیدی عددی: {user['user_id']}\n"
            f"پکیج: {title}\n"
            f"مبلغ: {price_text}\n"
            f"شماره خرید: #{purchase_id}"
        )
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ تایید رسید", callback_data=f"pc:{purchase_id}"),
                InlineKeyboardButton("❌ رد رسید", callback_data=f"pr:{purchase_id}"),
            ]]
        )
        for admin_id in db.list_admins():
            try:
                msg = await context.bot.send_photo(admin_id, file_id, caption=caption, reply_markup=kb)
                db.set_purchase_admin_msg(purchase_id, msg.message_id)
            except TelegramError:
                pass
        await update.message.reply_text("✅ رسید شما برای پشتیبانی ارسال شد، لطفا منتظر تایید بمانید.")

    else:  # await_receipt_charge
        amount = context.user_data.get("charge_amount")
        req_id = db.create_charge_request(user["user_id"], amount, file_id)
        caption = (
            f"🧾 درخواست شارژ حساب جدید\n\n"
            f"کاربر: {user['first_name']} ({uname})\n"
            f"آیدی عددی: {user['user_id']}\n"
            f"مبلغ: {amount:,} تومان\n"
            f"شماره درخواست: #{req_id}"
        )
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ تایید شارژ", callback_data=f"cc:{req_id}"),
                InlineKeyboardButton("❌ رد شارژ", callback_data=f"cr:{req_id}"),
            ]]
        )
        for admin_id in db.list_admins():
            try:
                msg = await context.bot.send_photo(admin_id, file_id, caption=caption, reply_markup=kb)
                db.set_charge_admin_msg(req_id, msg.message_id)
            except TelegramError:
                pass
        await update.message.reply_text("✅ رسید شما برای پشتیبانی ارسال شد، لطفا منتظر تایید بمانید.")

    context.user_data["state"] = None
    context.user_data.pop("pkg", None)
    context.user_data.pop("charge_amount", None)


# ==================================================================
#                  تایید / رد رسید خرید کانفینگ (ادمین)
# ==================================================================
async def purchase_confirm(update, context, purchase_id):
    query = update.callback_query
    if not db.is_admin(update.effective_user.id):
        await query.answer("شما دسترسی ندارید.", show_alert=True)
        return
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("یافت نشد.", show_alert=True)
        return
    if purchase["status"] != "pending":
        await query.answer("این رسید قبلا بررسی شده است.", show_alert=True)
        return
    db.set_purchase_status(purchase_id, "approved")
    await query.answer("تایید شد ✅")
    try:
        await query.edit_message_caption(caption=query.message.caption + "\n\n✅ تایید شد")
    except (BadRequest, TelegramError):
        pass
    try:
        await context.bot.send_message(
            purchase["user_id"],
            "پول انتقال یافته شما توسط پشتیبانی تایید و منتظر دریافت کانفینگ باشید",
        )
    except TelegramError:
        pass
    await post_to_sales_channel(context, purchase["package_title"], purchase["price_text"])


async def purchase_reject(update, context, purchase_id):
    query = update.callback_query
    if not db.is_admin(update.effective_user.id):
        await query.answer("شما دسترسی ندارید.", show_alert=True)
        return
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("یافت نشد.", show_alert=True)
        return
    if purchase["status"] != "pending":
        await query.answer("این رسید قبلا بررسی شده است.", show_alert=True)
        return
    db.set_purchase_status(purchase_id, "rejected")
    await query.answer("رد شد ❌")
    try:
        await query.edit_message_caption(caption=query.message.caption + "\n\n❌ رد شد")
    except (BadRequest, TelegramError):
        pass
    try:
        await context.bot.send_message(
            purchase["user_id"],
            "پشتیبانی پولی که شما زده اید را رد کرد لطفا مجددا تلاش بفرمایید",
        )
    except TelegramError:
        pass


async def charge_confirm(update, context, req_id):
    query = update.callback_query
    if not db.is_admin(update.effective_user.id):
        await query.answer("شما دسترسی ندارید.", show_alert=True)
        return
    req = db.get_charge_request(req_id)
    if not req or req["status"] != "pending":
        await query.answer("قابل انجام نیست.", show_alert=True)
        return
    db.set_charge_status(req_id, "approved")
    db.add_balance(req["user_id"], req["amount"])
    await query.answer("تایید شد ✅")
    try:
        await query.edit_message_caption(caption=query.message.caption + "\n\n✅ تایید شد")
    except (BadRequest, TelegramError):
        pass
    try:
        await context.bot.send_message(
            req["user_id"],
            f"✅ شارژ حساب شما به مبلغ {req['amount']:,} تومان توسط پشتیبانی تایید و به حساب شما اضافه شد.",
        )
    except TelegramError:
        pass


async def charge_reject(update, context, req_id):
    query = update.callback_query
    if not db.is_admin(update.effective_user.id):
        await query.answer("شما دسترسی ندارید.", show_alert=True)
        return
    req = db.get_charge_request(req_id)
    if not req or req["status"] != "pending":
        await query.answer("قابل انجام نیست.", show_alert=True)
        return
    db.set_charge_status(req_id, "rejected")
    await query.answer("رد شد ❌")
    try:
        await query.edit_message_caption(caption=query.message.caption + "\n\n❌ رد شد")
    except (BadRequest, TelegramError):
        pass
    try:
        await context.bot.send_message(
            req["user_id"],
            "درخواست شارژ حساب شما توسط پشتیبانی رد شد، لطفا مجددا تلاش بفرمایید.",
        )
    except TelegramError:
        pass


# ==================================================================
#                          گزینه‌های ساده کاربر
# ==================================================================
async def show_my_purchases(update, context):
    user_id = update.effective_user.id
    rows = db.approved_purchases_for_user(user_id)
    if not rows:
        text = "شما تاکنون خریدی نداشته‌اید."
    else:
        lines = ["📦 کانفینگ‌های خریداری‌شده شما:\n"]
        for r in rows:
            lines.append(f"• {r['package_title']} | {r['price_text']} | {r['created_at']}")
        text = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def show_my_points(update, context):
    user = db.get_user(update.effective_user.id)
    text = f"⭐️ امتیاز فعلی شما: {user['points']}\n💳 موجودی حساب شما: {user['balance']:,} تومان"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def show_referral(update, context):
    user_id = update.effective_user.id
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user_id}"
    count = db.referrals_count(user_id)
    text = (
        f"👥 لینک دعوت اختصاصی شما:\n{link}\n\n"
        f"با هر دعوت موفق {config.REFERRAL_POINTS} امتیاز دریافت می‌کنید.\n"
        f"تعداد افراد دعوت‌شده توسط شما: {count} نفر"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def start_gift_code(update, context):
    context.user_data["state"] = "await_gift_code"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("🎁 کد هدیه خود را ارسال کنید:")
    else:
        await update.message.reply_text("🎁 کد هدیه خود را ارسال کنید:")


async def start_charge_balance(update, context):
    context.user_data["state"] = "await_charge_amount"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("💳 مبلغی که می‌خواهید شارژ کنید را به تومان وارد کنید (فقط عدد):")
    else:
        await update.message.reply_text("💳 مبلغی که می‌خواهید شارژ کنید را به تومان وارد کنید (فقط عدد):")


async def start_support(update, context):
    context.user_data["state"] = "await_support_message"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("پیام موردنظر خود را ارسال کنید")
    else:
        await update.message.reply_text("پیام موردنظر خود را ارسال کنید")


# ==================================================================
#                        هندلر عمومی متن (روتر حالت‌ها)
# ==================================================================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    if db.is_banned(user_id):
        await update.message.reply_text("⛔️ شما توسط مدیریت مسدود شده‌اید.")
        return

    db.upsert_user(user_id, update.effective_user.username, update.effective_user.first_name)

    # ---------- ابتدا بررسی پاسخ ادمین به تیکت پشتیبانی ----------
    if db.is_admin(user_id) and update.message.reply_to_message:
        target_user = db.get_support_user(update.message.reply_to_message.message_id)
        if target_user:
            try:
                await context.bot.send_message(target_user, f"پاسخ پشتیبانی:\n{text}")
                await update.message.reply_text("✅ پاسخ شما ارسال شد.")
            except TelegramError:
                await update.message.reply_text("❌ ارسال پاسخ ناموفق بود.")
            return

    state = context.user_data.get("state")

    # ---------- بازگشت ----------
    if text == BACK_TEXT:
        context.user_data["state"] = None
        if context.user_data.get("in_admin"):
            context.user_data["in_admin"] = False
        await update.message.reply_text("منوی اصلی:", reply_markup=user_main_markup(user_id))
        return

    if text == ADMIN_ENTRY_LABEL and db.is_admin(user_id):
        context.user_data["in_admin"] = True
        await update.message.reply_text("👑 پنل مدیریت:", reply_markup=admin_main_markup())
        return

    # ---------- حالت‌های در انتظار ورودی متن ----------
    if state:
        handled = await handle_stateful_text(update, context, state, text)
        if handled:
            return

    # ---------- دکمه‌های سفارشی ----------
    for cb in db.list_custom_buttons():
        if cb["text"] == text:
            await update.message.reply_text(cb["response_text"])
            return

    # ---------- دکمه‌های ثابت (کیبورد رنگی) ----------
    key = LABEL2KEY.get(text)
    if key:
        if key in ADMIN_KEY2LABEL and not db.is_admin(user_id):
            return
        await dispatch_action(update, context, key)
        return

    # چیزی تشخیص داده نشد
    # اگر بی‌ربط بود چیزی نگو تا اسپم نشود


async def dispatch_action(update, context, key):
    """اجرای اکشن مربوط به هر دکمه - چه از کیبورد رنگی و چه از دکمه شیشه‌ای صدا زده شود."""
    fn = ACTION_MAP.get(key)
    if fn:
        await fn(update, context)


# ==================================================================
#                    مدیریت ورودی‌های متنی چندمرحله‌ای
# ==================================================================
async def handle_stateful_text(update, context, state, text) -> bool:
    user_id = update.effective_user.id

    if state == "await_gift_code":
        context.user_data["state"] = None
        pts, err = db.redeem_gift_code(text.strip(), user_id)
        if err == "not_found":
            await update.message.reply_text("❌ کد وارد شده معتبر نیست.")
        elif err == "exhausted":
            await update.message.reply_text("❌ ظرفیت استفاده از این کد به پایان رسیده است.")
        elif err == "already_used":
            await update.message.reply_text("❌ شما قبلا از این کد استفاده کرده‌اید.")
        else:
            await update.message.reply_text(f"🎉 کد هدیه با موفقیت اعمال شد! {pts} امتیاز به حساب شما اضافه شد.")
        return True

    if state == "await_charge_amount":
        if not text.isdigit():
            await update.message.reply_text("لطفا فقط عدد ارسال کنید (مبلغ به تومان).")
            return True
        context.user_data["charge_amount"] = int(text)
        context.user_data["state"] = "await_receipt_charge"
        card = db.get_setting("card_number", config.DEFAULT_CARD_NUMBER)
        await update.message.reply_text(
            f"💳 مبلغ {int(text):,} تومان را به شماره کارت زیر واریز کرده و عکس رسید را ارسال کنید:\n\n`{card}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    if state == "await_support_message":
        context.user_data["state"] = None
        user = db.get_user(user_id)
        uname = f"@{user['username']}" if user["username"] else "ندارد"
        header = f"📩 پیام پشتیبانی جدید\nکاربر: {user['first_name']} ({uname})\nآیدی: {user['user_id']}\n\n{text}"
        for admin_id in db.list_admins():
            try:
                msg = await context.bot.send_message(admin_id, header)
                db.map_support_message(msg.message_id, user_id)
            except TelegramError:
                pass
        await update.message.reply_text("ارسال شد✅")
        return True

    # -------------------- ویزارد ادمین: ساخت کد هدیه --------------------
    if state == "await_gift_points":
        if not text.isdigit():
            await update.message.reply_text("لطفا فقط عدد ارسال کنید (مقدار امتیاز).")
            return True
        context.user_data["gift_points"] = int(text)
        context.user_data["state"] = "await_gift_maxuses"
        await update.message.reply_text("تعداد دفعات قابل استفاده از این کد را وارد کنید (عدد):")
        return True

    if state == "await_gift_maxuses":
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("لطفا یک عدد صحیح بزرگتر از صفر ارسال کنید.")
            return True
        points = context.user_data.pop("gift_points")
        code = db.create_gift_code(points, int(text))
        context.user_data["state"] = None
        await update.message.reply_text(
            f"✅ کد هدیه ساخته شد:\n\n`{code}`\n\nامتیاز: {points}\nحداکثر استفاده: {text}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    # -------------------- ویزارد ادمین: افزودن ادمین --------------------
    if state == "await_add_admin_id":
        if not text.isdigit():
            await update.message.reply_text("آیدی عددی نامعتبر است.")
            return True
        db.add_admin(int(text))
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ کاربر {text} به عنوان ادمین اضافه شد.")
        return True

    # -------------------- ویزارد ادمین: افزودن کانال اجباری --------------------
    if state == "await_add_channel":
        ch = text.strip()
        if not ch.startswith("@"):
            ch = "@" + ch
        db.add_force_channel(ch)
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ کانال {ch} به لیست عضویت اجباری اضافه شد.")
        return True

    # -------------------- ویزارد ادمین: انتقال امتیاز --------------------
    if state == "await_transfer_uid":
        if not text.isdigit():
            await update.message.reply_text("آیدی عددی نامعتبر است.")
            return True
        context.user_data["transfer_uid"] = int(text)
        context.user_data["state"] = "await_transfer_amount"
        await update.message.reply_text("مقدار امتیاز برای انتقال را وارد کنید:")
        return True

    if state == "await_transfer_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("لطفا یک عدد معتبر ارسال کنید.")
            return True
        uid = context.user_data.pop("transfer_uid")
        db.add_points(uid, amount)
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ {amount} امتیاز به کاربر {uid} منتقل شد.")
        try:
            await context.bot.send_message(uid, f"🎁 {amount} امتیاز توسط مدیریت به حساب شما اضافه شد.")
        except TelegramError:
            pass
        return True

    # -------------------- ویزارد ادمین: مسدود/رفع مسدودی --------------------
    if state == "await_ban_id":
        if not text.isdigit():
            await update.message.reply_text("آیدی عددی نامعتبر است.")
            return True
        db.set_ban(int(text), True)
        context.user_data["state"] = None
        await update.message.reply_text(f"⛔️ کاربر {text} مسدود شد.")
        return True

    if state == "await_unban_id":
        if not text.isdigit():
            await update.message.reply_text("آیدی عددی نامعتبر است.")
            return True
        db.set_ban(int(text), False)
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ کاربر {text} رفع مسدودیت شد.")
        return True

    # -------------------- ویزارد ادمین: آمار کاربر --------------------
    if state == "await_user_stats_id":
        if not text.isdigit():
            await update.message.reply_text("آیدی عددی نامعتبر است.")
            return True
        u = db.get_user(int(text))
        context.user_data["state"] = None
        if not u:
            await update.message.reply_text("کاربری با این آیدی یافت نشد.")
            return True
        purchases = db.approved_purchases_for_user(u["user_id"])
        info = (
            f"🗽 آمار کاربر {u['user_id']}\n\n"
            f"نام: {u['first_name']}\n"
            f"یوزرنیم: @{u['username'] if u['username'] else '---'}\n"
            f"امتیاز: {u['points']}\n"
            f"موجودی: {u['balance']:,} تومان\n"
            f"تعداد خرید موفق: {len(purchases)}\n"
            f"تعداد زیرمجموعه: {db.referrals_count(u['user_id'])}\n"
            f"مسدود: {'بله' if u['is_banned'] else 'خیر'}\n"
            f"تاریخ عضویت: {u['joined_at']}"
        )
        await update.message.reply_text(info)
        return True

    # -------------------- ویزارد ادمین: تنظیمات --------------------
    if state == "await_card_number":
        db.set_setting("card_number", text.strip())
        context.user_data["state"] = None
        await update.message.reply_text("✅ شماره کارت به‌روزرسانی شد.")
        return True

    if state == "await_sales_channel":
        ch = text.strip()
        if not ch.startswith("@"):
            ch = "@" + ch
        db.set_setting("sales_channel", ch)
        context.user_data["state"] = None
        await update.message.reply_text("✅ کانال فروش به‌روزرسانی شد. (دقت کنید ربات باید ادمین آن کانال باشد)")
        return True

    if state == "await_welcome_text":
        db.set_setting("welcome_text", text)
        context.user_data["state"] = None
        await update.message.reply_text("✅ متن خوش‌آمدگویی به‌روزرسانی شد.")
        return True

    # -------------------- ویزارد ادمین: پیام همگانی --------------------
    if state == "await_broadcast":
        context.user_data["state"] = None
        await update.message.reply_text("⏳ در حال ارسال پیام همگانی...")
        ids = db.all_user_ids()
        ok, fail = 0, 0
        for uid in ids:
            try:
                await context.bot.copy_message(uid, update.effective_chat.id, update.message.message_id)
                ok += 1
            except (Forbidden, TelegramError):
                fail += 1
            await asyncio.sleep(0.05)
        await update.message.reply_text(f"✅ ارسال شد.\nموفق: {ok}\nناموفق: {fail}")
        return True

    # -------------------- ویزارد ادمین: افزودن پکیج کانفینگ --------------------
    if state == "await_cfg_volume":
        context.user_data["cfg_volume"] = text.strip()
        context.user_data["state"] = "await_cfg_duration"
        await update.message.reply_text("مدت زمان پکیج را وارد کنید (مثلا: 1 ماه):")
        return True

    if state == "await_cfg_duration":
        context.user_data["cfg_duration"] = text.strip()
        context.user_data["state"] = "await_cfg_price"
        await update.message.reply_text("قیمت پکیج را به تومان وارد کنید (فقط عدد):")
        return True

    if state == "await_cfg_price":
        if not text.isdigit():
            await update.message.reply_text("لطفا فقط عدد ارسال کنید.")
            return True
        db.add_config_package(context.user_data.pop("cfg_volume"), context.user_data.pop("cfg_duration"), int(text))
        context.user_data["state"] = None
        await update.message.reply_text("✅ پکیج کانفینگ اضافه شد.")
        return True

    # -------------------- ویزارد ادمین: افزودن پکیج امتیازی --------------------
    if state == "await_pt_volume":
        context.user_data["pt_volume"] = text.strip()
        context.user_data["state"] = "await_pt_duration"
        await update.message.reply_text("مدت زمان پکیج را وارد کنید (مثلا: 6 روز):")
        return True

    if state == "await_pt_duration":
        context.user_data["pt_duration"] = text.strip()
        context.user_data["state"] = "await_pt_price"
        await update.message.reply_text("قیمت پکیج را به امتیاز وارد کنید (فقط عدد):")
        return True

    if state == "await_pt_price":
        if not text.isdigit():
            await update.message.reply_text("لطفا فقط عدد ارسال کنید.")
            return True
        db.add_point_package(context.user_data.pop("pt_volume"), context.user_data.pop("pt_duration"), int(text))
        context.user_data["state"] = None
        await update.message.reply_text("✅ پکیج امتیازی اضافه شد.")
        return True

    # -------------------- ویزارد ادمین: افزودن دکمه سفارشی --------------------
    if state == "await_custom_btn_text":
        context.user_data["custom_btn_text"] = text.strip()
        context.user_data["state"] = "await_custom_btn_response"
        await update.message.reply_text("متنی که با فشردن این دکمه برای کاربر ارسال شود را وارد کنید:")
        return True

    if state == "await_custom_btn_response":
        db.add_custom_button(context.user_data.pop("custom_btn_text"), text)
        context.user_data["state"] = None
        await update.message.reply_text("✅ دکمه سفارشی اضافه شد.")
        return True

    return False


# ==================================================================
#                          پنل مدیریت (routes)
# ==================================================================
async def show_admin_main(update, context):
    context.user_data["in_admin"] = True
    if update.callback_query:
        await update.callback_query.answer()
        await send_menu(update.callback_query, "👑 پنل مدیریت:", admin_main_markup(), edit=True)
    else:
        await update.message.reply_text("👑 پنل مدیریت:", reply_markup=admin_main_markup())


async def show_user_main(update, context):
    user_id = update.effective_user.id
    context.user_data["in_admin"] = False
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text("منوی اصلی:")
        except BadRequest:
            pass
        await update.callback_query.message.reply_text("منوی اصلی:", reply_markup=user_main_markup(user_id))
    else:
        await update.message.reply_text("منوی اصلی:", reply_markup=user_main_markup(user_id))


async def admin_gift_create(update, context):
    context.user_data["state"] = "await_gift_points"
    await reply_any(update, "🎁 مقدار امتیاز کد هدیه را وارد کنید (عدد):")


async def admin_charge_requests(update, context):
    reqs = db.pending_charge_requests()
    if not reqs:
        await reply_any(update, "درخواست شارژ در انتظاری وجود ندارد.")
        return
    for r in reqs:
        u = db.get_user(r["user_id"])
        caption = (
            f"درخواست شارژ #{r['id']}\nکاربر: {u['first_name'] if u else r['user_id']}\n"
            f"مبلغ: {r['amount']:,} تومان"
        )
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ تایید", callback_data=f"cc:{r['id']}"),
                InlineKeyboardButton("❌ رد", callback_data=f"cr:{r['id']}"),
            ]]
        )
        try:
            if r["receipt_file_id"]:
                await context.bot.send_photo(update.effective_user.id, r["receipt_file_id"], caption=caption, reply_markup=kb)
            else:
                await context.bot.send_message(update.effective_user.id, caption, reply_markup=kb)
        except TelegramError:
            pass


async def admin_broadcast(update, context):
    context.user_data["state"] = "await_broadcast"
    await reply_any(update, "📢 پیام همگانی خود را ارسال کنید (متن، عکس و ...):")


async def admin_bot_settings(update, context):
    card = db.get_setting("card_number", config.DEFAULT_CARD_NUMBER)
    channel = db.get_setting("sales_channel", config.DEFAULT_SALES_CHANNEL)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تغییر شماره کارت", callback_data="nv:set_card")],
        [InlineKeyboardButton("✏️ تغییر کانال فروش", callback_data="nv:set_channel")],
        [InlineKeyboardButton("✏️ تغییر متن خوش‌آمدگویی", callback_data="nv:set_welcome")],
        [InlineKeyboardButton(BACK_TEXT, callback_data="nv:admin_main")],
    ])
    text = f"⚙️ تنظیمات ربات\n\n💳 شماره کارت فعلی: {card}\n📢 کانال فروش فعلی: {channel}"
    await reply_any(update, text, kb)


async def admin_bot_stats(update, context):
    s = db.stats_summary()
    text = (
        "📊 آمار ربات\n\n"
        f"👥 تعداد کاربران: {s['total_users']}\n"
        f"✅ تعداد فروش موفق: {s['total_sales']}\n"
        f"💰 مجموع فروش (تومانی): {s['total_revenue']:,}\n"
        f"⏳ رسیدهای در انتظار بررسی: {s['pending_purchases']}\n"
        f"⏳ درخواست‌های شارژ در انتظار: {s['pending_charges']}\n"
        f"⛔️ کاربران مسدود: {s['banned']}"
    )
    await reply_any(update, text)


async def admin_manage_packages(update, context):
    kb_rows = [[InlineKeyboardButton("➕ افزودن پکیج کانفینگ", callback_data="nv:add_cfg_pkg")],
               [InlineKeyboardButton("➕ افزودن پکیج امتیازی", callback_data="nv:add_pt_pkg")]]
    for p in db.list_config_packages(active_only=False):
        state_icon = "🟢" if p["active"] else "🔴"
        label = f"{state_icon} {p['volume']}+{p['duration']}+{p['price']:,}ت"
        kb_rows.append([
            InlineKeyboardButton(label, callback_data=f"tc:{p['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"dc:{p['id']}"),
        ])
    for p in db.list_point_packages(active_only=False):
        state_icon = "🟢" if p["active"] else "🔴"
        label = f"{state_icon} {p['points_price']}امتیاز+{p['volume']}"
        kb_rows.append([
            InlineKeyboardButton(label, callback_data=f"tp:{p['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"dp:{p['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton(BACK_TEXT, callback_data="nv:admin_main")])
    await reply_any(update, "📦 مدیریت پکیج‌ها (روی نام کلیک کنید تا فعال/غیرفعال شود):", InlineKeyboardMarkup(kb_rows))


async def admin_panel_manage(update, context):
    kb_rows = []
    for k, l in USER_BUTTONS + ADMIN_BUTTONS:
        icon = "🟢" if db.is_button_visible(k) else "🔴"
        kb_rows.append([InlineKeyboardButton(f"{icon} {l}", callback_data=f"tb:{k}")])
    for cb in db.list_custom_buttons(enabled_only=False):
        kb_rows.append([
            InlineKeyboardButton(f"🔘 {cb['text']}", callback_data="noop"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"db:{cb['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton("➕ افزودن دکمه سفارشی", callback_data="nv:add_custom_btn")])
    style = button_style()
    style_label = "🔘 سبک فعلی: شیشه‌ای (تغییر به رنگی)" if style == "inline" else "🔘 سبک فعلی: رنگی (تغییر به شیشه‌ای)"
    kb_rows.append([InlineKeyboardButton(style_label, callback_data="nv:button_style")])
    kb_rows.append([InlineKeyboardButton(BACK_TEXT, callback_data="nv:admin_main")])
    await reply_any(
        update,
        "🛠 پنل مدیریت دکمه‌ها\n\nبا کلیک روی هر دکمه، وضعیت نمایش آن (سبز=فعال/قرمز=غیرفعال) تغییر می‌کند.",
        InlineKeyboardMarkup(kb_rows),
    )


async def admin_add_admin(update, context):
    context.user_data["state"] = "await_add_admin_id"
    await reply_any(update, "➕ آیدی عددی کاربر مورد نظر برای افزودن به عنوان ادمین را ارسال کنید:")


async def admin_add_channel(update, context):
    context.user_data["state"] = "await_add_channel"
    channels = "\n".join(db.list_force_channels()) or "---"
    await reply_any(update, f"کانال‌های فعلی:\n{channels}\n\n💻 آیدی کانال جدید (مثال: @channel) را ارسال کنید:")


async def admin_transfer_points(update, context):
    context.user_data["state"] = "await_transfer_uid"
    await reply_any(update, "⭐️ آیدی عددی کاربر مورد نظر را ارسال کنید:")


async def admin_ban_user(update, context):
    context.user_data["state"] = "await_ban_id"
    await reply_any(update, "👨‍🔧 آیدی عددی کاربری که می‌خواهید مسدود شود را ارسال کنید:")


async def admin_unban_user(update, context):
    context.user_data["state"] = "await_unban_id"
    await reply_any(update, "👨‍🔧 آیدی عددی کاربری که می‌خواهید رفع مسدودیت شود را ارسال کنید:")


async def admin_user_stats(update, context):
    context.user_data["state"] = "await_user_stats_id"
    await reply_any(update, "🗽 آیدی عددی کاربر مورد نظر را ارسال کنید:")


async def admin_button_style(update, context):
    current = button_style()
    new_style = "reply" if current == "inline" else "inline"
    db.set_setting("button_style", new_style)
    label = "رنگی (کیبورد معمولی)" if new_style == "reply" else "شیشه‌ای (اینلاین)"
    await reply_any(update, f"✅ سبک دکمه‌ها به «{label}» تغییر یافت.")
    await show_admin_main(update, context)


# ---- توابع کمکی برای زیرمنوهای تنظیمات و پکیج‌ها (فراخوانی با nv:) ----
async def admin_set_card(update, context):
    context.user_data["state"] = "await_card_number"
    await reply_any(update, "💳 شماره کارت جدید را ارسال کنید:")


async def admin_set_channel(update, context):
    context.user_data["state"] = "await_sales_channel"
    await reply_any(update, "📢 آیدی کانال فروش جدید را ارسال کنید (مثال: @channel):")


async def admin_set_welcome(update, context):
    context.user_data["state"] = "await_welcome_text"
    await reply_any(update, "✏️ متن خوش‌آمدگویی جدید را ارسال کنید:")


async def admin_add_cfg_pkg(update, context):
    context.user_data["state"] = "await_cfg_volume"
    await reply_any(update, "➕ افزودن پکیج کانفینگ\n\nحجم پکیج را وارد کنید (مثلا: 10 گیگ):")


async def admin_add_pt_pkg(update, context):
    context.user_data["state"] = "await_pt_volume"
    await reply_any(update, "➕ افزودن پکیج امتیازی\n\nحجم پکیج را وارد کنید (مثلا: 4 گیگ):")


async def admin_add_custom_btn(update, context):
    context.user_data["state"] = "await_custom_btn_text"
    await reply_any(update, "➕ متن دکمه سفارشی جدید را وارد کنید:")


async def reply_any(update, text, markup=None):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


# ==================================================================
#                          نقشه اکشن دکمه‌ها
# ==================================================================
ACTION_MAP = {
    "buy_config": show_buy_config,
    "gift_code": start_gift_code,
    "my_purchases": show_my_purchases,
    "charge_balance": start_charge_balance,
    "buy_points": show_buy_points,
    "my_points": show_my_points,
    "referral": show_referral,
    "support": start_support,
    "admin_main": show_admin_main,
    "back": show_user_main,
    "check_join": None,  # جداگانه هندل می‌شود
    "gift_create": admin_gift_create,
    "charge_requests": admin_charge_requests,
    "broadcast": admin_broadcast,
    "bot_settings": admin_bot_settings,
    "bot_stats": admin_bot_stats,
    "manage_packages": admin_manage_packages,
    "panel_manage": admin_panel_manage,
    "add_admin": admin_add_admin,
    "add_channel": admin_add_channel,
    "transfer_points": admin_transfer_points,
    "ban_user": admin_ban_user,
    "unban_user": admin_unban_user,
    "user_stats": admin_user_stats,
    "button_style": admin_button_style,
    "set_card": admin_set_card,
    "set_channel": admin_set_channel,
    "set_welcome": admin_set_welcome,
    "add_cfg_pkg": admin_add_cfg_pkg,
    "add_pt_pkg": admin_add_pt_pkg,
    "add_custom_btn": admin_add_custom_btn,
}


# ==================================================================
#                          هندلر کالبک (دکمه شیشه‌ای)
# ==================================================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    if db.is_banned(user_id) and not data.startswith("nv:check_join"):
        await query.answer("⛔️ شما مسدود شده‌اید.", show_alert=True)
        return

    if data == "noop":
        await query.answer()
        return

    if data == "nv:check_join":
        await check_join_callback(update, context)
        return

    if not await ensure_joined(update, context):
        return

    if data.startswith("nv:"):
        key = data.split(":", 1)[1]
        if key in ADMIN_KEY2LABEL or key in ("admin_main", "gift_create", "charge_requests", "broadcast",
                                              "bot_settings", "bot_stats", "manage_packages", "panel_manage",
                                              "add_admin", "add_channel", "transfer_points", "ban_user",
                                              "unban_user", "user_stats", "button_style", "set_card",
                                              "set_channel", "set_welcome", "add_cfg_pkg", "add_pt_pkg",
                                              "add_custom_btn"):
            if not db.is_admin(user_id):
                await query.answer("شما دسترسی ادمین ندارید.", show_alert=True)
                return
        await dispatch_action(update, context, key)
        return

    if data.startswith("cbtn:"):
        btn_id = int(data.split(":")[1])
        cb = db.get_custom_button(btn_id)
        await query.answer()
        if cb:
            await query.message.reply_text(cb["response_text"])
        return

    if data.startswith("bc:"):
        await select_config_package(update, context, int(data.split(":")[1]))
        return
    if data.startswith("bp:"):
        await select_point_package(update, context, int(data.split(":")[1]))
        return
    if data.startswith("pc:"):
        await purchase_confirm(update, context, int(data.split(":")[1]))
        return
    if data.startswith("pr:"):
        await purchase_reject(update, context, int(data.split(":")[1]))
        return
    if data.startswith("cc:"):
        await charge_confirm(update, context, int(data.split(":")[1]))
        return
    if data.startswith("cr:"):
        await charge_reject(update, context, int(data.split(":")[1]))
        return

    if not db.is_admin(user_id):
        await query.answer()
        return

    if data.startswith("tc:"):
        db.toggle_config_package(int(data.split(":")[1]))
        await query.answer("وضعیت تغییر کرد")
        await admin_manage_packages(update, context)
        return
    if data.startswith("dc:"):
        db.delete_config_package(int(data.split(":")[1]))
        await query.answer("حذف شد")
        await admin_manage_packages(update, context)
        return
    if data.startswith("tp:"):
        db.toggle_point_package(int(data.split(":")[1]))
        await query.answer("وضعیت تغییر کرد")
        await admin_manage_packages(update, context)
        return
    if data.startswith("dp:"):
        db.delete_point_package(int(data.split(":")[1]))
        await query.answer("حذف شد")
        await admin_manage_packages(update, context)
        return
    if data.startswith("tb:"):
        db.toggle_button_visibility(data.split(":", 1)[1])
        await query.answer("وضعیت تغییر کرد")
        await admin_panel_manage(update, context)
        return
    if data.startswith("db:"):
        db.delete_custom_button(int(data.split(":")[1]))
        await query.answer("حذف شد")
        await admin_panel_manage(update, context)
        return

    await query.answer()


# ==================================================================
#                                main
# ==================================================================
async def on_error(update, context):
    logger.exception("خطای غیرمنتظره", exc_info=context.error)


def main():
    db.init_db()
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", show_admin_main))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_receipt_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    app.add_error_handler(on_error)

    logger.info("ربات اجرا شد...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
