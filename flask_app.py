from dotenv import load_dotenv
load_dotenv()

import logging, os, json, requests, io, base64, time
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, PreCheckoutQueryHandler, ContextTypes
from deep_translator import GoogleTranslator

# ==================== Flask ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Frnd is alive!"

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
STRIPE_PROVIDER_TOKEN = os.environ.get("STRIPE_PROVIDER_TOKEN", "")

SWIFT_CODE = "PUBABDDH"
BANK_NAME = "Pubali Bank Limited"
BANK_BRANCH = "Jalapur, Sylhet"
PRICE_BDT = 300
OWNER_USERNAME = "@Blini_Cupee"

HISTORY_FILE = "chat_history.json"
CONFIG_FILE = "bot_config.json"
pending_purchase = {}

TRIAL_MINUTES = 30
user_trial_start = {}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ---------- Gender answer ----------
GENDER_QUESTION_ANSWER = (
    "There are three genders: male, female, and the natural third gender "
    "(often called intersex or third gender). Society may also recognize "
    "non‑binary identities, but biologically the three fundamental categories "
    "are male, female, and intersex/third gender."
)

def is_gender_question(text: str) -> bool:
    low = text.lower().strip()
    if "how many gender" in low:
        return True
    if "লিঙ্গ" in low and ("কয়টা" in low or "কয়টি" in low or "সংখ্যা" in low):
        return True
    return False

# ---------- Hugging Face AI ----------
def ask_gemini(prompt: str, image_bytes: bytes = None) -> str:
    if not HF_API_TOKEN:
        return "Hugging Face API token not configured."

    if image_bytes:
        api_url = "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-base"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        try:
            resp = requests.post(api_url, headers=headers, data=image_bytes, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data[0]["generated_text"]
        except Exception as e:
            logging.error(f"Image caption error: {e}")
            return "I couldn't describe this image."

    api_url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 250, "temperature": 0.7, "return_full_text": False}
    }
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0].get("generated_text", "").strip()
        elif isinstance(data, dict):
            return data.get("generated_text", "").strip()
        else:
            return "I'm not sure how to respond to that."
    except Exception as e:
        logging.error(f"Hugging Face error: {e}")
        return "I'm slightly confused, but I've been trained to be polite. How can I help?"

def detect_language(text: str) -> str:
    try: return GoogleTranslator(source='auto', target='en').detect(text)
    except: return 'en'

def translate(text: str, target: str) -> str:
    if target == 'en': return text
    try: return GoogleTranslator(source='auto', target=target).translate(text)
    except: return text

def save_history(user_id, msg, reply):
    data = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            try: data = json.load(f)
            except: data = []
    data.append({"user_id": user_id, "time": datetime.now().isoformat(), "message": msg, "reply": reply})
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_trial_expired(user_id: int) -> bool:
    if user_id == OWNER_CHAT_ID:
        return False
    now = datetime.now()
    start = user_trial_start.get(user_id)
    if start is None:
        user_trial_start[user_id] = now
        return False
    return (now - start) > timedelta(minutes=TRIAL_MINUTES)

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'hello')
    msg = translate(
        f"Hello! I am Frnd, your intelligent assistant powered by Hugging Face AI. "
        f"You have a {TRIAL_MINUTES}-minute free trial. After that, purchase via /buy.\n"
        "Send a photo or ask me anything!",
        user_lang
    )
    await update.message.reply_text(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'help')
    msg = translate(
        "Commands:\n/start - Welcome\n/help - This message\n/buy - Purchase ownership (Stripe or SWIFT)\n",
        user_lang)
    await update.message.reply_text(msg)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'buy')
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay with Card / PayPal (Stripe)", callback_data="pay_stripe")],
        [InlineKeyboardButton("🏦 Bank Transfer (SWIFT)", callback_data="pay_swift")]
    ])
    msg = translate("Choose a payment method. Stripe is fully automatic. SWIFT requires manual confirmation.", user_lang)
    await update.message.reply_text(msg, reply_markup=keyboard)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "pay_stripe":
        if not STRIPE_PROVIDER_TOKEN:
            await query.message.reply_text("Stripe payment is not available. Please use SWIFT.")
            return
        await context.bot.send_invoice(
            chat_id=user.id,
            title="Frnd Bot Ownership",
            description="One-time purchase of the Frnd Telegram bot.",
            payload="buy_ownership",
            provider_token=STRIPE_PROVIDER_TOKEN,
            currency="USD",
            prices=[LabeledPrice("Bot Ownership", 250)],  # $2.50
            need_name=True,
            need_phone_number=True,
            need_email=True,
            is_flexible=False
        )

    elif data == "pay_swift":
        msg = (
            "International Bank Transfer via SWIFT:\n\n"
            f"SWIFT Code: `{SWIFT_CODE}`\n"
            f"Bank: {BANK_NAME}\n"
            f"Branch: {BANK_BRANCH}\n\n"
            "For the full account number, contact the owner privately.\n"
            "After payment, send the transaction ID or screenshot here."
        )
        await query.message.reply_text(msg)

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text("Payment successful! Transferring ownership...")
    deploy_url = "https://heroku.com/deploy?template=https://github.com/grazaxyz678-creator/frnd_bot"
    instruction = (
        f"🎉 Congratulations! You are now the owner of Frnd.\n\n"
        f"🔑 Token: `{BOT_TOKEN}`\n\n"
        f"To deploy the bot 24/7 on Heroku for free, click the button below:\n{deploy_url}\n\n"
        f"After deploying, fill in your Hugging Face token and Telegram ID.\n\n"
        f"To claim manually:\n1. @BotFather -> /mybots\n2. Select bot -> API Token -> Revoke\n3. Generate new token and use it in your own code.\n⚠️ Keep secret!"
    )
    await context.bot.send_message(chat_id=user.id, text=instruction)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"status": "sold", "sold_to": user.id}, f)
    await context.bot.send_message(chat_id=OWNER_CHAT_ID, text=f"Bot sold via Stripe to {user.full_name} ({user.id}). Shutting down.")
    os._exit(0)

async def receive_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    if len(text) < 4: return
    user_lang = detect_language(text)
    pending_purchase[user.id] = {
        "txn_id": text, "timestamp": datetime.now().isoformat(),
        "full_name": user.full_name, "username": user.username,
        "chat_id": user.id, "user_lang": user_lang
    }
    await update.message.reply_text(translate(f"Received! Transaction: {text}. Owner will verify.", user_lang))
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Confirm", callback_data=f"confirm_{user.id}"),
         InlineKeyboardButton("Reject", callback_data=f"reject_{user.id}")]
    ])
    await context.bot.send_message(
        chat_id=OWNER_CHAT_ID,
        text=f"New purchase request\n\n{user.full_name} (ID: {user.id})\n@{user.username or 'None'}\nTransaction: `{text}`\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nCheck your bank statement and click:",
        reply_markup=keyboard)

async def confirm_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("confirm_") and not data.startswith("reject_"): return
    action, uid = data.split("_")
    buyer_id = int(uid)
    if query.from_user.id != OWNER_CHAT_ID:
        await query.message.reply_text("You are not the owner.")
        return
    if action == "confirm":
        if buyer_id not in pending_purchase:
            await query.edit_message_text("No pending request.")
            return
        txn = pending_purchase.pop(buyer_id)
        await query.edit_message_text(f"Payment confirmed!\nBuyer: {txn['full_name']}\nTransaction: {txn['txn_id']}\nSending token...")
        deploy_url = "https://heroku.com/deploy?template=https://github.com/grazaxyz678-creator/frnd_bot"
        instruction = (
            f"🎉 Congratulations! You are now the owner of Frnd.\n\n"
            f"🔑 Token: `{BOT_TOKEN}`\n\n"
            f"To deploy 24/7 on Heroku for free, click:\n{deploy_url}\n\n"
            f"After deploying, set your Hugging Face token and Telegram ID.\n\n"
            f"Keep the token secret!"
        )
        await context.bot.send_message(chat_id=buyer_id, text=instruction)
        with open(CONFIG_FILE, "w") as f:
            json.dump({"status": "sold", "sold_to": txn}, f)
        await context.bot.send_message(chat_id=OWNER_CHAT_ID, text="Bot sold. Shutting down.")
        os._exit(0)
    elif action == "reject":
        if buyer_id in pending_purchase:
            rejected = pending_purchase.pop(buyer_id)
            await context.bot.send_message(chat_id=buyer_id, text=translate("Payment not verified. Contact owner.", rejected.get("user_lang", "en")))
        await query.edit_message_text(f"User {buyer_id} rejected.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_trial_expired(user.id):
        await update.message.reply_text(translate("Your free trial has expired. To continue, purchase ownership via /buy.", detect_language("buy")))
        return
    photo_file = await update.message.photo[-1].get_file()
    img_bytes = await photo_file.download_as_bytearray()
    prompt = "Describe this image in detail, including what is happening, who or what is present, colors, and any interesting details."
    desc_en = ask_gemini(prompt, image_bytes=bytes(img_bytes))
    user_lang = "en"
    if update.message.caption:
        user_lang = detect_language(update.message.caption)
    desc_final = translate(desc_en, user_lang)
    await update.message.reply_text(f"{desc_final}")
    save_history(update.effective_user.id, "[Photo]", desc_final)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    user = update.effective_user
    user_lang = detect_language(text)

    if len(text) >= 6 and not text.startswith("@") and ("txn" in text.lower() or "0174" in text or "swift" in text.lower()):
        await receive_transaction_id(update, context)
        return

    if is_trial_expired(user.id):
        await update.message.reply_text(translate("Your free trial has expired. To continue, purchase ownership via /buy.", user_lang))
        return

    if is_gender_question(text):
        reply = translate(GENDER_QUESTION_ANSWER, user_lang)
        await update.message.reply_text(reply)
        save_history(update.effective_user.id, text, reply)
        return

    system_prompt = (
        "You are an elite-level economist and strategic military planner. "
        "Answer the user's message with deep, data-driven insights. "
        "When discussing economics (especially sanctions, trade, development), "
        "provide actionable strategies, historical analogies, and quantitative reasoning. "
        "When discussing military/strategic questions, think like a Pentagon planner—"
        "consider logistics, alliances, cyber warfare, and unconventional tactics. "
        "Always be concise but comprehensive. "
        "If the message is not about economics or strategy, answer normally with high intelligence."
    )
    full_prompt = f"{system_prompt}\n\nUser: {text}\nAssistant:"
    response_en = ask_gemini(full_prompt)
    reply = translate(response_en, user_lang)
    await update.message.reply_text(reply)
    save_history(update.effective_user.id, text, reply)

def run_bot():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            if json.load(f).get("status") == "sold":
                print("Frnd already sold.")
                return
    if not BOT_TOKEN or not OWNER_CHAT_ID:
        print("Missing BOT_TOKEN or OWNER_CHAT_ID environment variables.")
        return
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    telegram_app.add_handler(CommandHandler("buy", buy))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    telegram_app.add_handler(CallbackQueryHandler(button_callback, pattern="^pay_(stripe|swift)$"))
    telegram_app.add_handler(CallbackQueryHandler(confirm_payment_callback, pattern="^(confirm|reject)_"))
    telegram_app.add_handler(PreCheckoutQueryHandler(precheckout))
    telegram_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    logging.info("Frnd started with Hugging Face AI, automatic Stripe payments, and manual SWIFT.")
    telegram_app.run_polling()

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
