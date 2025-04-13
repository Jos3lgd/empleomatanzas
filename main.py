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
logging.basicConfig(format='[%(asctime)s] [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- Constantes ----
ADMIN_IDS = [12345678]  # Reemplaza con tu ID de Telegram
PALABRAS_PROHIBIDAS = {"singar", "fraude", "spam", "http://", "https://"}
ULTIMOS_MENSAJES = {}
PUESTO, EMPRESA, SALARIO, DESCRIPCION, CONTACTO = range(5)
NOMBRE, TRABAJO, ESCOLARIDAD, CONTACTO_TRABAJADOR = range(5, 9)

# ---- Conexión con Google Sheets ----
TOKEN = os.getenv('TELEGRAM_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

sheet = None
ofertas_db = None
usuarios_db = None

try:
    logger.info("🔧 Intentando conectar con Google Sheets...")
    
    # Cargar credenciales desde variable de entorno
    creds_json = os.getenv('GOOGLE_CREDS_JSON')
    if creds_json:
        creds_dict = json.loads(creds_json)
        CREDS = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        logger.info("✅ Credenciales cargadas desde variable de entorno")
    else:
        # Fallback a archivo local para desarrollo
        CREDS = Credentials.from_service_account_file('credenciales.json', scopes=SCOPES)
        logger.info("✅ Credenciales cargadas desde archivo local")
    
    # Conectar con Google Sheets
    client = gspread.authorize(CREDS)
    sheet = client.open("EmpleoMatanzasDB")
    ofertas_db = sheet.worksheet("Ofertas")
    usuarios_db = sheet.worksheet("Usuarios")
    logger.info("✅ Conexión exitosa con Google Sheets")
    
except Exception as e:
    logger.error(f"❌ Error conectando con Google Sheets: {e}")
    # El bot puede continuar funcionando sin Sheets, pero con funcionalidad limitada

# ---- Funciones de base de datos ----
def registrar_usuario(user_id: int, nombre: str, username: str, chat_id: int):
    if not usuarios_db:
        return False
    try:
        # Verificar si el usuario ya existe
        try:
            cell = usuarios_db.find(str(user_id))
            # Actualizar chat_id por si cambió
            usuarios_db.update_cell(cell.row, 4, str(chat_id))
            return True
        except gspread.exceptions.CellNotFound:
            # Usuario nuevo
            usuarios_db.append_row([
                str(user_id), 
                nombre,
                f"@{username}" if username else "Sin username",
                str(chat_id),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "0",  # Contador de ofertas
                "activo"  # Estado de notificaciones
            ])
            logger.info(f"👤 Usuario registrado: {user_id}")
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
        logger.info("📝 Oferta guardada")
        return True
    except Exception as e:
        logger.error(f"❌ Error guardando oferta: {e}")
        return False

# ---- Funciones de mensajería masiva ----
async def enviar_mensaje_a_usuario(context: CallbackContext, chat_id: int, mensaje: str):
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=mensaje,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Mensaje enviado a {chat_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje a {chat_id}: {e}")
        return False

async def enviar_mensaje_admin(update: Update, context: CallbackContext):
    """Permite al admin enviar mensajes a todos los usuarios"""
    if not context.args:
        await update.message.reply_text("Uso: /enviar <mensaje>")
        return
    
    mensaje = ' '.join(context.args)
    confirmacion = await update.message.reply_text(
        f"¿Enviar este mensaje a todos los usuarios?\n\n{mensaje}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, enviar a todos", callback_data=f"confirmar_envio:{mensaje}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_envio")]
        ])
    )
    context.user_data["mensaje_original"] = mensaje
    context.user_data["mensaje_id"] = confirmacion.message_id

async def confirmar_envio(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("confirmar_envio:"):
        mensaje = query.data.split(":", 1)[1]
        usuarios = usuarios_db.get_all_records()
        total = 0
        exitosos = 0
        
        await query.edit_message_text(f"⏳ Enviando mensaje a {len(usuarios)} usuarios...")
        
        for usuario in usuarios:
            if usuario.get("Notificaciones", "activo") == "activo":
                try:
                    await enviar_mensaje_a_usuario(
                        context,
                        int(usuario["ChatID"]),
                        mensaje
                    )
                    exitosos += 1
                    time.sleep(0.5)  # Evitar flood
                except Exception as e:
                    logger.error(f"Error enviando a {usuario['ChatID']}: {e}")
                total += 1
        
        await query.edit_message_text(
            f"✅ Envío completado!\n"
            f"• Total: {total}\n"
            f"• Exitosos: {exitosos}\n"
            f"• Fallidos: {total - exitosos}"
        )
    else:
        await query.edit_message_text("❌ Envío cancelado")

# ---- Comandos para usuarios ----
async def start(update: Update, context: CallbackContext):
    logger.info("🚀 /start recibido")
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if usuarios_db:
        registrar_usuario(user.id, user.first_name, user.username, chat_id)
    
    await update.message.reply_photo(
        photo="https://github.com/Jos3lgd/mapa-circuitos-matanzas/blob/main/empleoMTZ.jpg?raw=true",
        caption="👋 ¡Bienvenid@ al Bot Empleo Matanzas!\n\n"
        "💻 Este Bot está desarrollado por el equipo de @infomatanzas\n"
        "Usa /menu para ver opciones.\n"
        "Usa /help o el Botón Ayuda para conocer como funciona"
    )

async def menu(update: Update, context: CallbackContext):
    teclado = [
        [InlineKeyboardButton("🔍 Ofertas de trabajo", callback_data="buscar")],
        [InlineKeyboardButton("💼 Ofrecer trabajo", callback_data="ofertar")],
        [InlineKeyboardButton("🧑‍💼 Solicitar trabajo", callback_data="registro")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="ayuda")]
    ]
    await update.message.reply_text("📲 Elige una opción:", reply_markup=InlineKeyboardMarkup(teclado))

async def silenciar_notificaciones(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    try:
        cell = usuarios_db.find(str(user_id))
        usuarios_db.update_cell(cell.row, 7, "silenciado")  # Columna 7 = Estado
        await update.message.reply_text("🔕 Has desactivado las notificaciones. Usa /activar para volver a recibirlas.")
    except Exception as e:
        logger.error(f"Error al silenciar: {e}")
        await update.message.reply_text("❌ Error al procesar tu solicitud")

async def activar_notificaciones(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    try:
        cell = usuarios_db.find(str(user_id))
        usuarios_db.update_cell(cell.row, 7, "activo")
        await update.message.reply_text("🔔 Notificaciones activadas. Usa /silenciar para dejar de recibirlas.")
    except Exception as e:
        logger.error(f"Error al activar: {e}")
        await update.message.reply_text("❌ Error al procesar tu solicitud")

# ---- Función principal ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configurar comandos del bot
    async def establecer_comandos(app):
        await app.bot.set_my_commands([
            ("start", "Iniciar el bot"),
            ("menu", "Ver menú interactivo"),
            ("ofertar", "Publicar oferta de empleo"),
            ("buscar", "Buscar ofertas"),
            ("buscoempleo", "Registrarte como buscador de empleo"),
            ("silenciar", "Desactivar notificaciones"),
            ("activar", "Activar notificaciones"),
            ("help", "Ver ayuda")
        ])
    
    app.post_init = establecer_comandos
    
    # Handlers para administradores
    app.add_handler(CommandHandler("enviar", enviar_mensaje_admin, filters=filters.User(ADMIN_IDS)))
    app.add_handler(CallbackQueryHandler(confirmar_envio, pattern="^(confirmar_envio|cancelar_envio)"))
    
    # Handlers para usuarios
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("silenciar", silenciar_notificaciones))
    app.add_handler(CommandHandler("activar", activar_notificaciones))
    
    # (Aquí añade el resto de tus handlers existentes...)
    
    logger.info("🤖 Bot iniciado y escuchando...")
    app.run_polling()

if __name__ == '__main__':
    main()
