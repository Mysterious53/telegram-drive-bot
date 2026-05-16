from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, TypeHandler, filters,
)
from telegram.ext import ApplicationHandlerStop

from .start import start_command, check_join_callback
from .account import account_callback, disconnect_drive_callback
from .upload import (
    upload_link_callback, upload_file_callback,
    drive_choice_callback,
    handle_url_message, handle_file_message,
    quality_callback,
)
from .files import files_callback, file_delete_callback
from .tutorial import (
    tutorial_callback, tutorial_admin_callback, tutorial_admin_add_callback,
    tutorial_list_callback, tutorial_del_callback, handle_admin_tutorial_media,
)
from .software import (
    software_os_callback, software_list_callback,
    software_admin_callback, software_admin_platform_callback,
    software_admin_add_callback, software_del_callback, handle_admin_sw_file,
)
from .admin import (
    admin_command, admin_callback,
    handle_admin_search, handle_admin_add_channel,
    handle_admin_set_google_id, handle_admin_set_google_secret,
)
from .public_drive_admin import (
    public_drive_menu_callback, public_drive_callback,
    handle_admin_public_drive_label,
)
from bot.keyboards import main_menu
from bot.states import (
    IDLE, ADMIN_SET_GOOGLE_ID, ADMIN_SET_GOOGLE_SECRET,
    ADMIN_TUTORIAL_ADD, ADMIN_SW_ADD, ADMIN_PUBLIC_DRIVE_LABEL,
)

_CANCEL_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ لغو آپلود", callback_data="cancel_upload")]]
)


async def _upload_lock(update: Update, context):
    """Group -1: blocks all updates for users who are actively uploading."""
    queue = context.application.bot_data.get("upload_queue")
    if not queue:
        return
    user_id = getattr(update.effective_user, "id", None)
    if not user_id or not queue.is_uploading(user_id):
        return
    # Always let the cancel callback through
    if update.callback_query and update.callback_query.data == "cancel_upload":
        return

    if update.callback_query:
        await update.callback_query.answer(
            "⏳ آپلود در حال انجام است! لطفاً منتظر بمانید یا لغو کنید.",
            show_alert=True,
        )
    elif update.message:
        await update.message.reply_text(
            "⏳ *آپلود در حال انجام است*\n\nلطفاً منتظر بمانید یا آن را لغو کنید.",
            parse_mode="Markdown",
            reply_markup=_CANCEL_KB,
        )
    raise ApplicationHandlerStop()


async def _cancel_upload_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    queue = context.application.bot_data.get("upload_queue")
    user_id = update.effective_user.id
    if queue and queue.cancel_upload(user_id):
        await query.edit_message_text("⏹ در حال لغو آپلود...")
    else:
        await query.edit_message_text("هیچ آپلودی در حال انجام نیست.", reply_markup=main_menu())


async def _main_menu_callback(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = IDLE
    await query.edit_message_text("یک گزینه را انتخاب کنید:", reply_markup=main_menu())


def register(app: Application):
    # Upload lock — runs before everything else
    app.add_handler(TypeHandler(Update, _upload_lock), group=-1)

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))

    # Callback queries — ordered by specificity
    app.add_handler(CallbackQueryHandler(_cancel_upload_callback,     pattern="^cancel_upload$"))
    app.add_handler(CallbackQueryHandler(check_join_callback,         pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(_main_menu_callback,         pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(account_callback,            pattern="^account$"))
    app.add_handler(CallbackQueryHandler(disconnect_drive_callback,   pattern="^disconnect_drive$"))
    app.add_handler(CallbackQueryHandler(upload_link_callback,        pattern="^upload_link$"))
    app.add_handler(CallbackQueryHandler(upload_file_callback,        pattern="^upload_file$"))
    app.add_handler(CallbackQueryHandler(drive_choice_callback,       pattern="^drive_choice:"))
    app.add_handler(CallbackQueryHandler(quality_callback,                  pattern="^yt_q:"))
    app.add_handler(CallbackQueryHandler(files_callback,                    pattern="^files:"))
    app.add_handler(CallbackQueryHandler(file_delete_callback,              pattern="^file:del:"))
    # Tutorial
    app.add_handler(CallbackQueryHandler(tutorial_callback,                 pattern="^tutorial$"))
    app.add_handler(CallbackQueryHandler(tutorial_admin_callback,           pattern="^tutorial:admin$"))
    app.add_handler(CallbackQueryHandler(tutorial_admin_add_callback,       pattern="^tutorial:admin:add$"))
    app.add_handler(CallbackQueryHandler(tutorial_list_callback,            pattern="^tutorial:admin:list$"))
    app.add_handler(CallbackQueryHandler(tutorial_del_callback,             pattern="^tutorial:admin:del:"))
    # Software
    app.add_handler(CallbackQueryHandler(software_os_callback,              pattern="^sw:os$"))
    app.add_handler(CallbackQueryHandler(software_list_callback,            pattern="^sw:list:"))
    app.add_handler(CallbackQueryHandler(software_admin_callback,           pattern="^sw:admin$"))
    app.add_handler(CallbackQueryHandler(software_admin_platform_callback,  pattern="^sw:admin:platform:"))
    app.add_handler(CallbackQueryHandler(software_admin_add_callback,       pattern="^sw:admin:add:"))
    app.add_handler(CallbackQueryHandler(software_del_callback,             pattern="^sw:admin:del:"))
    # Public drives admin
    app.add_handler(CallbackQueryHandler(public_drive_menu_callback,        pattern="^pubdrv:menu$"))
    app.add_handler(CallbackQueryHandler(public_drive_callback,             pattern="^pubdrv:"))
    # Admin (generic — must come last)
    app.add_handler(CallbackQueryHandler(admin_callback,                    pattern="^admin:"))

    # Text messages — route by state
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_text))

    # File/media messages — route by state
    app.add_handler(MessageHandler(
        (
            filters.Document.ALL | filters.VIDEO | filters.AUDIO |
            filters.PHOTO | filters.VOICE | filters.VIDEO_NOTE |
            filters.ANIMATION
        ) & ~filters.COMMAND,
        _route_media,
    ))


async def _route_text(update, context):
    state = context.user_data.get("state", IDLE)
    if state == "wait_url":
        await handle_url_message(update, context)
    elif state == "admin_search":
        await handle_admin_search(update, context)
    elif state == "admin_add_channel":
        await handle_admin_add_channel(update, context)
    elif state == ADMIN_SET_GOOGLE_ID:
        await handle_admin_set_google_id(update, context)
    elif state == ADMIN_SET_GOOGLE_SECRET:
        await handle_admin_set_google_secret(update, context)
    elif state == ADMIN_PUBLIC_DRIVE_LABEL:
        await handle_admin_public_drive_label(update, context)


async def _route_media(update, context):
    state = context.user_data.get("state", IDLE)
    if state == ADMIN_TUTORIAL_ADD:
        await handle_admin_tutorial_media(update, context)
    elif state == ADMIN_SW_ADD:
        await handle_admin_sw_file(update, context)
    else:
        await handle_file_message(update, context)