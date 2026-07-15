import logging, os, json, requests, io, base64, time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from deep_translator import GoogleTranslator

# ==================== CONFIG FROM ENVIRONMENT ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PRODIA_API_KEY = os.environ.get("PRODIA_API_KEY", "")
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
# Bank details
BANK_NAME = "Pubali Bank Limited"
BANK_BRANCH = "Jalapur, Sylhet"
BANK_ACCOUNT_MASKED = "3961XXXXXXXX (last 4 digits: 1290)"
SWIFT_CODE = "PUBABDDH"
PRICE_BDT = 300
OWNER_USERNAME = "@Blini_Cupee"

HISTORY_FILE = "chat_history.json"
CONFIG_FILE = "bot_config.json"
pending_purchase = {}

# ---------- Trial system ----------
TRIAL_MINUTES = 30
user_trial_start = {}  # user_id -> datetime

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ---------- Fixed gender answer ----------
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

def ask_gemini(prompt: str, image_bytes: bytes = None) -> str:
    if not GEMINI_API_KEY:
        return "Gemini API key not configured."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    parts = [{"text": prompt}]
    if image_bytes:
        img_b64 = base64.b64encode(image_bytes).decode()
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_b64}})
    payload = {"contents": [{"parts": parts}]}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return "I'm slightly confused, but I've been trained to be polite. How can I help?"

def generate_image(prompt: str) -> bytes:
    if not PRODIA_API_KEY:
        raise Exception("Prodia API key missing")
    url = "https://api.prodia.com/v1/job"
    headers = {"accept": "application/json", "content-type": "application/json", "X-Prodia-Key": PRODIA_API_KEY}
    payload = {"prompt": prompt, "steps": 20, "cfg_scale": 7, "sampler": "Euler a", "width": 512, "height": 512}
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"Job creation failed: {resp.text}")
    job_id = resp.json()["job"]
    for _ in range(30):
        time.sleep(4)
        status_url = f"https://api.prodia.com/v1/job/{job_id}"
        status_resp = requests.get(status_url, headers={"X-Prodia-Key": PRODIA_API_KEY})
        status_json = status_resp.json()
        if status_json["status"] == "succeeded":
            return requests.get(status_json["image_url"]).content
        elif status_json["status"] == "failed":
            raise Exception("Generation failed")
    raise Exception("Timeout")

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'hello')
    msg = translate(
        f"Hello! I am Frnd, your intelligent assistant powered by Google Gemini. "
        f"You have a {TRIAL_MINUTES}-minute free trial. After that, you'll need to purchase ownership via /buy.\n"
        "Send a photo or ask me anything!",
        user_lang
    )
    await update.message.reply_text(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'help')
    msg = translate(
        "Commands:\n/start - Welcome\n/help - This message\n/buy - Purchase Frnd's ownership via bank transfer\n/generate <prompt> - Create AI image (if available)\n",
        user_lang)
    await update.message.reply_text(msg)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'buy')
    msg = (
        f"Buy Frnd's ownership\n\n"
        f"Price: *{PRICE_BDT}* BDT ~$2.5 USD\n\n"
        f"Bank Transfer:\n"
        f"   Bank: {BANK_NAME}\n"
        f"   Branch: {BANK_BRANCH}\n"
        f"   Account: `{BANK_ACCOUNT_MASKED}`\n"
        f"   SWIFT: `{SWIFT_CODE}`\n\n"
        f"For full account number, contact {OWNER_USERNAME}.\n"
        f"International buyers can use SWIFT.\n\n"
        f"After payment, send transaction ID or screenshot here."
    )
    translated = translate(msg, user_lang)
    await update.message.reply_text(translated)

async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = detect_language(update.message.text or 'generate')
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text(translate("Provide a prompt. Example: /generate a cat in space", user_lang))
        return
    if not PRODIA_API_KEY:
        await update.message.reply_text(translate("Image generation is not available.", user_lang))
        return
    await update.message.reply_text(translate("Generating image...", user_lang))
    try:
        img_bytes = generate_image(prompt)
        await update.message.reply_photo(photo=img_bytes, caption=f"Prompt: {prompt}")
    except Exception as e:
        await update.message.reply_text(translate(f"Failed: {e}", user_lang))

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
        await query.edit_message_text(f"Payment confirmed!\nBuyer: {txn['full_name']}\nTransaction: {txn['txn_id']}\nSending token and deployment button...")
        deploy_url = "https://heroku.com/deploy?template=https://github.com/grazaxyz678-creator/frnd_bot"
        instruction = (
            f"Congratulations! You are now the owner of Frnd.\n\n"
            f"Token: `{BOT_TOKEN}`\n\n"
            f"To deploy the bot 24/7 on Heroku for free, click the button below:\n{deploy_url}\n\n"
            f"After deploying, fill in your Gemini API key (get from https://aistudio.google.com/apikey) and your Telegram ID.\n\n"
            f"To claim the bot manually:\n1. @BotFather -> /mybots\n2. Select bot -> API Token -> Revoke\n3. Generate new token and use it in your own code.\nKeep secret!"
        )
        await context.bot.send_message(chat_id=buyer_id, text=instruction)
        with open(CONFIG_FILE, "w") as f:
            json.dump({"status": "sold", "sold_to": txn}, f)
        await context.bot.send_message(chat_id=OWNER_CHAT_ID, text="Frnd has been sold. Shutting down.")
        os._exit(0)
    elif action == "reject":
        if buyer_id in pending_purchase:
            rejected = pending_purchase.pop(buyer_id)
            await context.bot.send_message(chat_id=buyer_id, text=translate("Payment not verified. Contact owner.", rejected.get("user_lang", "en")))
        await query.edit_message_text(f"User {buyer_id} rejected.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Trial check
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
        # Commands are handled by other handlers, we just return
        return
    user = update.effective_user
    user_lang = detect_language(text)

    # Always allow transaction ID submission
    if len(text) >= 6 and not text.startswith("@") and ("txn" in text.lower() or "0174" in text):
        await receive_transaction_id(update, context)
        return

    # Check trial
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

def main():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            if json.load(f).get("status") == "sold":
                print("Frnd already sold.")
                return
    if not BOT_TOKEN or not OWNER_CHAT_ID:
        print("Missing BOT_TOKEN or OWNER_CHAT_ID environment variables.")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("generate", generate_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(confirm_payment_callback, pattern="^(confirm|reject)_"))
    logging.info("Frnd started with Gemini API, gender rule, trial system, and strategic/economics expert system.")
    app.run_polling()

if __name__ == "__main__":
    main()
