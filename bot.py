import os
import base64
import logging
import aiohttp
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "YOUR_ANTHROPIC_KEY_HERE")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ذخیره موقت عکس‌ها (file_id → bytes)
photo_cache: dict[str, bytes] = {}

# ─── پرامپت‌های مختلف برای هر ابزار ────────────────────────
PROMPTS = {
    "midjourney": """You are an expert Midjourney prompt engineer.
Analyze the image and write a prompt optimized for Midjourney v6.
Format: detailed description --ar 1:1 --v 6 --style raw
Include: subject, environment, lighting, colors, mood, camera style.
Preserve ALL facial features, skin tone, hair, expression.
Output ONLY the prompt, nothing else.""",

    "chatgpt": """You are an expert DALL-E 3 / ChatGPT image prompt engineer.
Analyze the image and write a detailed natural-language prompt for DALL-E 3.
Write it as a clear descriptive paragraph (no special syntax).
Include: subject details, facial features, clothing, background, lighting, style, mood.
Preserve ALL visual details faithfully.
Output ONLY the prompt, nothing else.""",

    "flux": """You are an expert Flux / Stable Diffusion prompt engineer.
Analyze the image and write a prompt optimized for Flux or Stable Diffusion.
Use comma-separated tags and descriptors.
Include: subject, face details, clothing, background, lighting style, camera, quality tags.
Add quality boosters: masterpiece, best quality, ultra-detailed, 8k.
Output ONLY the prompt, nothing else.""",

    "ideogram": """You are an expert Ideogram prompt engineer.
Analyze the image and write a prompt optimized for Ideogram v2.
Write natural descriptive sentences, very detailed.
Include: subject, style, colors, mood, lighting, environment.
Preserve ALL facial and physical details.
Output ONLY the prompt, nothing else.""",

    "universal": """You are an expert AI image prompt engineer.
Analyze the image and write a universal detailed prompt that works with ANY AI image generator.
Cover ALL of: subject/face details, clothing, pose, background, lighting, camera style, art style, colors, mood, quality.
Write as a detailed paragraph followed by key descriptors.
Preserve ALL visual details so the recreation looks nearly identical.
Output ONLY the prompt, nothing else.""",
}

TOOL_LABELS = {
    "midjourney": "🎨 Midjourney",
    "chatgpt":    "🤖 ChatGPT / DALL·E",
    "flux":       "⚡ Flux / Stable Diffusion",
    "ideogram":   "🖼 Ideogram",
    "universal":  "🌐 همه ابزارها (Universal)",
}

# ─── تحلیل با Claude ────────────────────────────────────────
async def analyze_image(image_bytes: bytes, tool: str) -> str:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    system_prompt = PROMPTS.get(tool, PROMPTS["universal"])

    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": "Analyze this image and give me the exact generation prompt."},
            ],
        }],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise RuntimeError(f"API error {resp.status}: {err}")
            data = await resp.json()
            return data["content"][0]["text"].strip()

# ─── هندلرها ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 سلام! ربات استخراج پرامپت تصویر 🎨\n\n"
        "📸 یک عکس بفرست\n"
        "🎯 ابزار مورد نظرت رو انتخاب کن\n"
        "✅ پرامپت دقیق دریافت کن!\n\n"
        "پشتیبانی از: Midjourney · DALL·E · Flux · Ideogram و بقیه"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    photo_cache[photo.file_id] = buf.getvalue()

    # نمایش دکمه‌های انتخاب ابزار
    keyboard = [
        [InlineKeyboardButton(TOOL_LABELS["midjourney"], callback_data=f"tool:{photo.file_id}:midjourney")],
        [InlineKeyboardButton(TOOL_LABELS["chatgpt"],    callback_data=f"tool:{photo.file_id}:chatgpt")],
        [InlineKeyboardButton(TOOL_LABELS["flux"],       callback_data=f"tool:{photo.file_id}:flux")],
        [InlineKeyboardButton(TOOL_LABELS["ideogram"],   callback_data=f"tool:{photo.file_id}:ideogram")],
        [InlineKeyboardButton(TOOL_LABELS["universal"],  callback_data=f"tool:{photo.file_id}:universal")],
    ]
    await update.message.reply_text(
        "✅ عکس دریافت شد!\n\n🎯 پرامپت رو برای کدوم ابزار می‌خوای؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text("⚠️ لطفاً فقط فایل تصویری بفرست.")
        return
    file = await context.bot.get_file(doc.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    photo_cache[doc.file_id] = buf.getvalue()

    keyboard = [
        [InlineKeyboardButton(TOOL_LABELS["midjourney"], callback_data=f"tool:{doc.file_id}:midjourney")],
        [InlineKeyboardButton(TOOL_LABELS["chatgpt"],    callback_data=f"tool:{doc.file_id}:chatgpt")],
        [InlineKeyboardButton(TOOL_LABELS["flux"],       callback_data=f"tool:{doc.file_id}:flux")],
        [InlineKeyboardButton(TOOL_LABELS["ideogram"],   callback_data=f"tool:{doc.file_id}:ideogram")],
        [InlineKeyboardButton(TOOL_LABELS["universal"],  callback_data=f"tool:{doc.file_id}:universal")],
    ]
    await update.message.reply_text(
        "✅ عکس دریافت شد!\n\n🎯 پرامپت رو برای کدوم ابزار می‌خوای؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, file_id, tool = query.data.split(":", 2)
    image_bytes = photo_cache.get(file_id)

    if not image_bytes:
        await query.edit_message_text("❌ عکس پیدا نشد. دوباره عکس بفرست.")
        return

    tool_label = TOOL_LABELS.get(tool, tool)
    await query.edit_message_text(f"⏳ در حال ساخت پرامپت برای {tool_label}...")

    try:
        prompt = await analyze_image(image_bytes, tool)
        # پاک کردن از cache بعد از استفاده
        photo_cache.pop(file_id, None)

        msg = (
            f"✅ پرامپت برای {tool_label}:\n\n"
            f"`{prompt}`"
        )
        # اگر پیام خیلی طولانی بود بدون Markdown بفرست
        try:
            await query.edit_message_text(msg, parse_mode="Markdown")
        except Exception:
            await query.edit_message_text(f"✅ پرامپت برای {tool_label}:\n\n{prompt}")

    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text(f"❌ خطا: {str(e)}\n\nدوباره امتحان کن.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 یک عکس بفرست تا پرامپتش رو استخراج کنم!")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(CallbackQueryHandler(handle_button, pattern="^tool:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("🤖 ربات شروع به کار کرد...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
