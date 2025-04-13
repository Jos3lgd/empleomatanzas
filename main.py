import os
import json
import logging
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
import gspread
from google.oauth2.service_account import Credentials

# Configuración de logging
logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constantes
ADMIN_IDS = [TU_ID_DE_TELEGRAM]  # Reemplaza con tu ID real
PALABRAS_PROHIBIDAS = {"singar", "fraude", "spam", "http://", "https://"}
ULTIMOS_MENSAJES = {}
PUESTO, EMPRESA, SALARIO, DESCRIPCION, CONTACTO = range(5)
NOMBRE, TRABAJO, ESCOLARIDAD, CONTACTO_TRABAJADOR = range(5, 9)
RESULTADOS_POR_PAGINA = 3

# Conexión con Google Sheets
TOKEN = os.getenv('TELEGRAM_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

sheet = None
ofertas_db = None
usuarios_db = None
candidatos_db = None

try:
    logger.info("Conectando con Google Sheets...")
    creds_json = os.getenv('GOOGLE_CREDS_JSON')
    if creds_json:
        creds_dict = json.loads(creds_json)
        CREDS = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        CREDS = Credentials.from_service_account_file('credenciales.json', scopes=SCOPES)
    
    client = gspread.authorize(CREDS)
    sheet = client.open("EmpleoMatanzasDB")
    ofertas_db = sheet.worksheet("Ofertas")
    usuarios_db = sheet.worksheet("Usuarios")
    candidatos_db = sheet.worksheet("Candidatos")
    logger.info("Conexión exitosa con Google Sheets")
except Exception as e:
    logger.error(f"Error conectando con Google Sheets: {e}")

# Funciones de base de datos
def registrar_usuario(user_id: int, nombre: str, username: str, chat_id: int):
    if not usuarios_db:
        return False
    try:
        try:
            usuarios_db.find(str(user_id))
            return True
        except gspread.exceptions.CellNotFound:
            usuarios_db.append_row([
                str(user_id),
                nombre,
                f"@{username}" if username else "Sin username",
                str(chat_id),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "0",
                "activo"
            ])
            return True
    except Exception as e:
        logger.error(f"Error registrando usuario: {e}")
        return False

def nueva_oferta(user_id: int, datos: dict):
    if not ofertas_db:
        return False
    try:
        ofertas_db.append_row([
            str(len(ofertas_db.col_values(1)) + 1),
            datos["puesto"],
            datos["empresa"],
            datos["salario"],
            datos["descripcion"],
            datos["contacto"],
            datetime.now().strftime("%Y-%m-%d"),
            str(user_id)
        ])
        return True
    except Exception as e:
        logger.error(f"Error guardando oferta: {e}")
        return False

# Comandos básicos
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    registrar_usuario(user.id, user.first_name, user.username, chat_id)
    await update.message.reply_photo(
        photo="https://github.com/Jos3lgd/mapa-circuitos-matanzas/blob/main/empleoMTZ.jpg?raw=true",
        caption="👋 ¡Bienvenid@ al Bot Empleo Matanzas!\n\nUsa /menu para ver opciones."
    )

async def menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("🔍 Ofertas de trabajo", callback_data="buscar_ofertas")],
        [InlineKeyboardButton("💼 Ofrecer trabajo", callback_data="ofertar_trabajo")],
        [InlineKeyboardButton("🧑‍💼 Solicitar trabajo", callback_data="registro_trabajador")],
        [InlineKeyboardButton("🔎 Buscar trabajadores", callback_data="buscar_candidatos")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="mostrar_ayuda")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📲 Menú Principal:",
        reply_markup=reply_markup
    )

async def ayuda(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "ℹ️ Ayuda del Bot:\n\n"
        "/start - Iniciar el bot\n"
        "/menu - Mostrar menú\n"
        "/ofertar - Publicar oferta\n"
        "/buscar - Buscar ofertas\n"
        "/buscoempleo - Registrarse\n"
        "/buscarcandidatos - Buscar trabajadores\n"
        "/ayuda - Mostrar esta ayuda"
    )

# Búsquedas
async def buscar_ofertas(update: Update, context: CallbackContext):
    if not ofertas_db:
        await update.message.reply_text("Error al acceder a ofertas")
        return
    
    ofertas = ofertas_db.get_all_records()
    if not ofertas:
        await update.message.reply_text("No hay ofertas disponibles")
        return
    
    for oferta in reversed(ofertas[:3]):
        await update.message.reply_text(
            f"💼 {oferta['Puesto']}\n"
            f"🏢 {oferta['Empresa']}\n"
            f"💰 {oferta['Salario']}\n"
            f"📞 {oferta['Contacto']}"
        )
    
    if len(ofertas) > 3:
        await update.message.reply_text(
            "¿Ver más ofertas?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_ofertas")]
            ])
        )

async def buscar_candidatos(update: Update, context: CallbackContext):
    if not candidatos_db:
        await update.message.reply_text("Error al acceder a candidatos")
        return
    
    candidatos = candidatos_db.get_all_records()
    if not candidatos:
        await update.message.reply_text("No hay candidatos registrados")
        return
    
    for candidato in reversed(candidatos[:3]):
        await update.message.reply_text(
            f"👤 {candidato['Nombre']}\n"
            f"🛠️ {candidato['Trabajo']}\n"
            f"📞 {candidato['Contacto']}"
        )
    
    if len(candidatos) > 3:
        await update.message.reply_text(
            "¿Ver más candidatos?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_candidatos")]
            ])
        )

# Manejador de botones
async def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buscar_ofertas":
        await buscar_ofertas(query, context)
    elif query.data == "ofertar_trabajo":
        await iniciar_oferta(query, context)
    elif query.data == "registro_trabajador":
        await iniciar_registro(query, context)
    elif query.data == "buscar_candidatos":
        await buscar_candidatos(query, context)
    elif query.data == "mostrar_ayuda":
        await ayuda(query, context)
    elif query.data == "ver_mas_ofertas":
        await ver_mas_ofertas(query, context)
    elif query.data == "ver_mas_candidatos":
        await ver_mas_candidatos(query, context)

# Función principal
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configurar comandos del menú
    async def set_commands(app):
        await app.bot.set_my_commands([
            ("start", "Iniciar el bot"),
            ("menu", "Mostrar menú"),
            ("ofertar", "Publicar oferta"),
            ("buscar", "Buscar ofertas"),
            ("buscoempleo", "Registrarse"),
            ("buscarcandidatos", "Buscar trabajadores"),
            ("ayuda", "Mostrar ayuda")
        ])
    
    app.post_init = set_commands
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("buscar", buscar_ofertas))
    app.add_handler(CommandHandler("buscarcandidatos", buscar_candidatos))
    app.add_handler(CallbackQueryHandler(handle_button))
    
    logger.info("Bot iniciado")
    app.run_polling()

if __name__ == '__main__':
    main()
