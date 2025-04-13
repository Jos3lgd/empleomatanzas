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

# ---- Configuración inicial ----
logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---- Constantes ----
ADMIN_IDS = [12345678]  # Reemplaza con tu ID real de Telegram
PALABRAS_PROHIBIDAS = {"singar", "fraude", "spam", "http://", "https://"}
ULTIMOS_MENSAJES = {}
PUESTO, EMPRESA, SALARIO, DESCRIPCION, CONTACTO = range(5)
NOMBRE, TRABAJO, ESCOLARIDAD, CONTACTO_TRABAJADOR = range(5, 9)
RESULTADOS_POR_PAGINA = 3

# ---- Conexión con Google Sheets ----
TOKEN = os.getenv('TELEGRAM_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

sheet = None
ofertas_db = None
usuarios_db = None
candidatos_db = None

try:
    logger.info("🔧 Intentando conectar con Google Sheets...")
    
    # Cargar credenciales
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
    logger.info("✅ Conexión exitosa con Google Sheets")
    
except Exception as e:
    logger.error(f"❌ Error conectando con Google Sheets: {e}")

# ---- Funciones de base de datos ----
def registrar_usuario(user_id: int, nombre: str, username: str, chat_id: int):
    if not usuarios_db:
        return False
    
    try:
        try:
            cell = usuarios_db.find(str(user_id))
            usuarios_db.update_cell(cell.row, 4, str(chat_id))
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
            logger.info(f"👤 Nuevo usuario registrado: {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Error registrando usuario: {e}")
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
        cell = usuarios_db.find(str(user_id))
        count = int(usuarios_db.cell(cell.row, 6).value)
        usuarios_db.update_cell(cell.row, 6, str(count + 1))
        logger.info("📝 Nueva oferta guardada")
        return True
    except Exception as e:
        logger.error(f"❌ Error guardando oferta: {e}")
        return False

# ---- Comandos básicos ----
async def start(update: Update, context: CallbackContext):
    try:
        logger.info("🚀 Comando /start recibido")
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        # Registrar usuario
        if usuarios_db:
            registrar_usuario(user.id, user.first_name, user.username, chat_id)
        
        # Enviar mensaje de bienvenida
        await update.message.reply_photo(
            photo="https://github.com/Jos3lgd/mapa-circuitos-matanzas/blob/main/empleoMTZ.jpg?raw=true",
            caption=(
                "👋 ¡Bienvenid@ al Bot Empleo Matanzas!\n\n"
                "💻 Desarrollado por @infomatanzas\n"
                "📲 Usa /menu para ver todas las opciones"
            )
        )
    except Exception as e:
        logger.error(f"❌ Error en comando start: {e}")
        await update.message.reply_text("🚫 Ocurrió un error al iniciar. Por favor intenta nuevamente.")

async def menu(update: Update, context: CallbackContext):
    try:
        teclado = [
            [InlineKeyboardButton("🔍 Ofertas de trabajo", callback_data="buscar")],
            [InlineKeyboardButton("💼 Ofrecer trabajo", callback_data="ofertar")],
            [InlineKeyboardButton("🧑‍💼 Solicitar trabajo", callback_data="registro")],
            [InlineKeyboardButton("🔎 Buscar trabajadores", callback_data="buscar_candidatos")],
            [InlineKeyboardButton("ℹ️ Ayuda", callback_data="ayuda")]
        ]
        reply_markup = InlineKeyboardMarkup(teclado)
        await update.message.reply_text(
            "📲 Menú Principal - Elige una opción:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"❌ Error mostrando menú: {e}")

# ... (resto del código permanece igual)

# ---- Función Principal ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configurar comandos del menú
    async def establecer_comandos(app):
        await app.bot.set_my_commands([
            ("start", "Iniciar el bot"),
            ("menu", "Mostrar menú interactivo"),
            ("ofertar", "Publicar oferta de trabajo"),
            ("buscar", "Buscar ofertas disponibles"),
            ("buscoempleo", "Registrarse como candidato"),
            ("buscarcandidatos", "Buscar trabajadores"),
            ("ayuda", "Mostrar ayuda")
        ])
        logger.info("✅ Comandos del menú configurados")
    
    app.post_init = establecer_comandos
    
    # Handlers principales
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    
    # ... (resto de los handlers permanece igual)
    
    logger.info("🤖 Bot iniciado correctamente")
    app.run_polling()

if __name__ == '__main__':
    main()
