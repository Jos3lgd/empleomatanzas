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

# ---- [Resto de funciones de base de datos y mensajería masiva permanecen igual] ----

# ---- Función Principal ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configurar comandos del bot para el menú inferior izquierdo
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
    
    # Handlers para administradores
    app.add_handler(CommandHandler("enviar", enviar_mensaje_admin, filters=filters.User(ADMIN_IDS)))
    app.add_handler(CallbackQueryHandler(manejar_confirmacion_envio, pattern="^(env_confirm|env_cancel)"))
    
    # Handlers básicos con menú de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("buscar", buscar_ofertas))
    app.add_handler(CommandHandler("buscarcandidatos", buscar_candidatos))
    
    # Handlers para flujos de conversación
    ofertar_handler = ConversationHandler(
        entry_points=[
            CommandHandler("ofertar", iniciar_oferta),
            CallbackQueryHandler(iniciar_oferta, pattern="^ofertar$")
        ],
        states={
            PUESTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_puesto)],
            EMPRESA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_empresa)],
            SALARIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_salario)],
            DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_descripcion)],
            CONTACTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_contacto)],
        },
        fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)],
        per_message=False
    )
    
    registro_handler = ConversationHandler(
        entry_points=[
            CommandHandler("buscoempleo", iniciar_registro_trabajador),
            CallbackQueryHandler(iniciar_registro_trabajador, pattern="^registro$")
        ],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
            TRABAJO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_trabajo)],
            ESCOLARIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_escolaridad)],
            CONTACTO_TRABAJADOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_contacto_trabajador)],
        },
        fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)],
        per_message=False
    )
    
    app.add_handler(ofertar_handler)
    app.add_handler(registro_handler)
    
    # Handler para botones del menú interactivo
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    logger.info("🤖 Bot iniciado y listo para recibir mensajes...")
    app.run_polling()

if __name__ == '__main__':
    main()
