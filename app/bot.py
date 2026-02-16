import os
import logging
import sentry_sdk
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from core.analyze_portfolio import generate_analysis_report, validate_kraken_ledger, validate_wallet_csv

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize Sentry
sentry_dsn = os.getenv('SENTRY_DSN')
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
    logging.info("Sentry initialized.")

# States
UPLOAD_LEDGER, UPLOAD_WALLET = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the Crypto Portfolio Bot!\n\n"
        "I can analyze your Kraken ledger and verify it against your Wallet history.\n"
        "ℹ️ **Note**: Currently, I only support **Trezor Suite** CSV exports for wallet verification.\n\n"
        "1️⃣ Please upload your **Kraken Ledger CSV** file to begin.",
        parse_mode='Markdown'
    )
    return UPLOAD_LEDGER

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    glossary = (
        "📊 **REPORT GUIDE**\n\n"
        "**Asset**: The cryptocurrency symbol (e.e.g., BTC).\n"
        "**Balance**: Total coins currently in your account.\n"
        "**Cost Basis**: Total Euros spent to specific coins.\n"
        "**P/L (€)**: Profit or Loss (Value - Cost Basis).\n"
        "**Rewards**: Coins earned from passive income.\n"
        "**Wallet**: Total coins withdrawn to private wallet.\n\n"
        "**DCA Strategy**:\n"
        "Buying more at a lower price reduces your average entry price."
    )
    await update.message.reply_text(glossary, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Developed by Alireza for fun :)\nv1.0 - Python & Docker")

import uuid
import datetime
import shutil

async def receive_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    
    # 1. Check File Name/Extension
    if not document.file_name.lower().endswith('.csv'):
        await update.message.reply_text("❌ Invalid file format. Please upload a **CSV** file.", parse_mode='Markdown')
        return UPLOAD_LEDGER

    file = await context.bot.get_file(document.file_id)
    
    # Generate Unique Session ID
    user_id = str(update.effective_user.id)
    session_id = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{str(uuid.uuid4())[:8]}"
    
    # Create session directory
    session_dir = os.path.join('data', user_id, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    context.user_data['session_dir'] = session_dir
    
    filename = os.path.join(session_dir, "ledger.csv")
    await file.download_to_drive(filename)
    
    # 2. Validate Content
    is_valid, error_msg = validate_kraken_ledger(filename)
    if not is_valid:
        # Cleanup and ask retry
        shutil.rmtree(session_dir)
        await update.message.reply_text(
            f"❌ **Invalid File**: {error_msg}\n"
            "Please check your file and upload a valid **Kraken Ledger CSV**.",
            parse_mode='Markdown'
        )
        return UPLOAD_LEDGER
    
    context.user_data['ledger_path'] = filename
    
    await update.message.reply_text(
        "✅ Kraken Ledger verified.\n\n"
        "2️⃣ Now, please upload your **Wallet History CSV** (Trezor Suite export).\n"
        "Or press the button below to skip verification.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip Verification", callback_data="skip")]]),
        parse_mode='Markdown'
    )
    return UPLOAD_WALLET

async def skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['wallet_path'] = None
    await query.edit_message_text("Skipping wallet verification. Analyzing portfolio...")
    await run_analysis(query, context)
    return ConversationHandler.END

async def receive_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    
    # 1. Check Extension
    if not document.file_name.lower().endswith('.csv'):
        await update.message.reply_text("❌ Invalid format. Please upload a **CSV** file.", parse_mode='Markdown')
        return UPLOAD_WALLET

    file = await context.bot.get_file(document.file_id)
    
    session_dir = context.user_data.get('session_dir')
    if not session_dir:
        await update.message.reply_text("❌ Session error. Please start over.")
        return ConversationHandler.END

    filename = os.path.join(session_dir, "wallet.csv")
    await file.download_to_drive(filename)
    
    # 2. Validate Content
    is_valid, error_msg = validate_wallet_csv(filename)
    if not is_valid:
        # Delete invalid file but keep session open for retry
        os.remove(filename)
        await update.message.reply_text(
            f"❌ **Invalid Wallet CSV**: {error_msg}\n"
            "Please upload a valid **Trezor Suite** export or skip this step.",
            parse_mode='Markdown'
        )
        return UPLOAD_WALLET
    
    context.user_data['wallet_path'] = filename
    
    await update.message.reply_text("✅ Wallet CSV verified. Analyzing...")
    await run_analysis(update, context)
    return ConversationHandler.END

async def run_analysis(update_obj, context: ContextTypes.DEFAULT_TYPE):
    # update_obj can be Update or CallbackQuery, so we look for message
    message = update_obj.message if hasattr(update_obj, 'message') else update_obj
    
    ledger_path = context.user_data.get('ledger_path')
    wallet_path = context.user_data.get('wallet_path')
    session_dir = context.user_data.get('session_dir')
    
    try:
        # Pass session_dir as output_dir for charts
        report = generate_analysis_report(ledger_path, wallet_path, output_dir=session_dir)
        
        # 1. Send Chart Images (Portfolio Summary + DCA Analysis)
        chart_paths = report.get('chart_paths', [])
        for chart_path in chart_paths:
            if os.path.exists(chart_path):
                await message.reply_photo(photo=open(chart_path, 'rb'))
            
        # 2. Wallet Verification Result (Keep as text for searchability/copy-paste)
        if 'wallet_verification' in report and report['wallet_verification']:
            verif = report['wallet_verification']
            totals = verif['totals']
            diff = totals['diff']
            
            verif_msg = "<b>🛡️ WALLET VERIFICATION</b>\n"
            verif_msg += f"Kraken Out: <code>{totals['kraken_out']:.6f} BTC</code>\n"
            verif_msg += f"Wallet In:  <code>{totals['wallet_in']:.6f} BTC</code>\n"
            
            if abs(diff) < 0.0001:
                 verif_msg += "✅ <b>Totals Match!</b>\n"
            else:
                 verif_msg += f"⚠️ <b>Mismatch</b>: <code>{diff:+.6f} BTC</code>\n"
            
            # Show Mismatches (Orphans)
            if verif.get('orphans'):
                verif_msg += f"\n⚠️ <b>Found in Wallet ONLY ({len(verif['orphans'])}):</b>\n"
                verif_msg += "<pre>"
                verif_msg += f"{'Date':<12} {'Amount':<10}\n"
                verif_msg += "-" * 24 + "\n"
                for t in verif['orphans']:
                    verif_msg += f"{str(t['date'])[:10]:<12} {t['amount']:<10.6f}\n"
                verif_msg += "</pre>"
                
            await message.reply_text(verif_msg, parse_mode='HTML')

    except Exception as e:
        await message.reply_text(f"❌ Error during analysis: {str(e)}")
        if sentry_dsn:
            sentry_sdk.capture_exception(e)
        logging.error(e)
        
    finally:
        # Cleanup
        if session_dir and os.path.exists(session_dir):
            try:
                shutil.rmtree(session_dir)
                logging.info(f"Cleaned up session: {session_dir}")
            except Exception as cleanup_error:
                logging.error(f"Failed to cleanup {session_dir}: {cleanup_error}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Analysis cancelled. Type /start to try again.", reply_markup=ReplyKeyboardRemove())
    # Cleanup if needed
    session_dir = context.user_data.get('session_dir')
    if session_dir and os.path.exists(session_dir):
         shutil.rmtree(session_dir, ignore_errors=True)
    return ConversationHandler.END

if __name__ == '__main__':
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        print("Error: TELEGRAM_TOKEN environment variable not set.")
        exit(1)
        
    application = ApplicationBuilder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            UPLOAD_LEDGER: [MessageHandler(filters.Document.ALL, receive_ledger)],
            UPLOAD_WALLET: [
                MessageHandler(filters.Document.ALL, receive_wallet),
                CallbackQueryHandler(skip_callback, pattern='^skip$')
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('about', about_command))

    print("Bot is running...")
    application.run_polling()
