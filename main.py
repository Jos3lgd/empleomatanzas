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

# ---- Sistema de Mensajería Masiva ----
async def enviar_mensaje_admin(update: Update, context: CallbackContext):
    """Maneja el comando /enviar para mensajes masivos"""
    user = update.effective_user
    
    # Verificar permisos
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 No tienes permisos para usar este comando.")
        return
    
    if not context.args:
        await update.message.reply_text("ℹ️ Uso: /enviar <tu mensaje aquí>")
        return
    
    mensaje = ' '.join(context.args)
    
    # Crear teclado de confirmación
    keyboard = [
        [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"env_confirm:{mensaje}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="env_cancel")]
    ]
    
    await update.message.reply_text(
        f"✉️ Mensaje preparado:\n\n{mensaje}\n\n"
        f"¿Enviar este mensaje a todos los usuarios?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def manejar_confirmacion_envio(update: Update, context: CallbackContext):
    """Gestiona la confirmación del envío masivo"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("env_confirm:"):
        mensaje = query.data.split(":", 1)[1]
        await query.edit_message_text("⏳ Enviando mensajes...")
        
        try:
            usuarios = usuarios_db.get_all_records()
            total = exitosos = 0
            
            for usuario in usuarios:
                try:
                    if usuario.get("Notificaciones") == "activo":
                        await context.bot.send_message(
                            chat_id=int(usuario["ChatID"]),
                            text=mensaje,
                            parse_mode='Markdown'
                        )
                        exitosos += 1
                        time.sleep(0.3)  # Pausa para evitar límites
                except Exception as e:
                    logger.error(f"Error enviando a {usuario.get('ChatID')}: {e}")
                finally:
                    total += 1
            
            await query.edit_message_text(
                f"✅ Envío completado\n"
                f"• Total usuarios: {len(usuarios)}\n"
                f"• Enviados: {exitosos}\n"
                f"• Fallidos: {len(usuarios) - exitosos}"
            )
        except Exception as e:
            logger.error(f"❌ Error en envío masivo: {e}")
            await query.edit_message_text("❌ Error durante el envío masivo")
    else:
        await query.edit_message_text("❌ Envío cancelado")

# ---- Handlers de Comandos ----
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if usuarios_db:
        registrar_usuario(user.id, user.first_name, user.username, chat_id)
    
    await update.message.reply_photo(
        photo="https://github.com/Jos3lgd/mapa-circuitos-matanzas/blob/main/empleoMTZ.jpg?raw=true",
        caption="👋 ¡Bienvenid@ al Bot Empleo Matanzas!"
    )

async def menu(update: Update, context: CallbackContext):
    teclado = [
        [InlineKeyboardButton("🔍 Ofertas de trabajo", callback_data="buscar")],
        [InlineKeyboardButton("💼 Ofrecer trabajo", callback_data="ofertar")],
        [InlineKeyboardButton("🧑‍💼 Solicitar trabajo", callback_data="registro")],
        [InlineKeyboardButton("🔎 Buscar trabajadores", callback_data="buscar_candidatos")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="ayuda")]
    ]
    await update.message.reply_text(
        "📲 Menú Principal - Elige una opción:",
        reply_markup=InlineKeyboardMarkup(teclado)
    )

async def ayuda(update: Update, context: CallbackContext):
    mensaje = (
        "ℹ️ *Ayuda del Bot*\n\n"
        "📌 *Comandos disponibles:*\n"
        "/start - Iniciar el bot\n"
        "/menu - Mostrar menú interactivo\n"
        "/ofertar - Publicar una oferta de trabajo\n"
        "/buscar - Ver ofertas disponibles\n"
        "/buscoempleo - Registrarse como buscador\n"
        "/buscarcandidatos - Buscar trabajadores\n"
        "/ayuda - Mostrar esta ayuda\n\n"
        "⚠️ Las ofertas se eliminan automáticamente después de 15 días."
    )
    await update.message.reply_text(mensaje, parse_mode='Markdown')

# ---- Flujo de Conversación para Ofertas ----
async def iniciar_oferta(update: Update, context: CallbackContext):
    if update.callback_query:
        await update.callback_query.message.reply_text("💼 ¿Cuál es el puesto de trabajo?")
    else:
        await update.message.reply_text("💼 ¿Cuál es el puesto de trabajo?")
    return PUESTO

async def recibir_puesto(update: Update, context: CallbackContext):
    context.user_data["puesto"] = update.message.text
    await update.message.reply_text("🏢 ¿Nombre de la empresa o empleador?")
    return EMPRESA

async def recibir_empresa(update: Update, context: CallbackContext):
    context.user_data["empresa"] = update.message.text
    await update.message.reply_text("💰 ¿Salario ofrecido?")
    return SALARIO

async def recibir_salario(update: Update, context: CallbackContext):
    context.user_data["salario"] = update.message.text
    await update.message.reply_text("📝 Descripción del puesto:")
    return DESCRIPCION

async def recibir_descripcion(update: Update, context: CallbackContext):
    context.user_data["descripcion"] = update.message.text
    await update.message.reply_text("📱 ¿Cómo contactar para esta oferta?")
    return CONTACTO

async def recibir_contacto(update: Update, context: CallbackContext):
    context.user_data["contacto"] = update.message.text
    user = update.effective_user
    
    if nueva_oferta(user.id, context.user_data):
        await update.message.reply_text("✅ ¡Oferta publicada con éxito!")
    else:
        await update.message.reply_text("❌ Error al publicar la oferta")
    
    return ConversationHandler.END

# ---- Flujo de Registro de Trabajadores ----
async def iniciar_registro_trabajador(update: Update, context: CallbackContext):
    if update.callback_query:
        await update.callback_query.message.reply_text("👤 ¿Cuál es tu nombre completo?")
    else:
        await update.message.reply_text("👤 ¿Cuál es tu nombre completo?")
    return NOMBRE

async def recibir_nombre(update: Update, context: CallbackContext):
    context.user_data["nombre"] = update.message.text
    await update.message.reply_text("🛠️ ¿Qué tipo de trabajo buscas?")
    return TRABAJO

async def recibir_trabajo(update: Update, context: CallbackContext):
    context.user_data["trabajo"] = update.message.text
    await update.message.reply_text("🎓 ¿Cuál es tu nivel de escolaridad?")
    return ESCOLARIDAD

async def recibir_escolaridad(update: Update, context: CallbackContext):
    context.user_data["escolaridad"] = update.message.text
    await update.message.reply_text("📱 ¿Cómo pueden contactarte?")
    return CONTACTO_TRABAJADOR

async def recibir_contacto_trabajador(update: Update, context: CallbackContext):
    context.user_data["contacto"] = update.message.text
    
    try:
        candidatos_db.append_row([
            context.user_data["nombre"],
            context.user_data["trabajo"],
            context.user_data["escolaridad"],
            context.user_data["contacto"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
        await update.message.reply_text("✅ ¡Registro completado con éxito!")
    except Exception as e:
        logger.error(f"❌ Error registrando candidato: {e}")
        await update.message.reply_text("❌ Error al guardar tu información")
    
    return ConversationHandler.END

# ---- Funciones de Búsqueda ----
async def buscar_ofertas(update: Update, context: CallbackContext):
    if not ofertas_db:
        await update.message.reply_text("⚠️ No se puede acceder a las ofertas")
        return
    
    try:
        ofertas = ofertas_db.get_all_records()
        if not ofertas:
            await update.message.reply_text("ℹ️ No hay ofertas disponibles actualmente")
            return
        
        # Mostrar las 3 ofertas más recientes
        for oferta in reversed(ofertas[-3:]):
            mensaje = (
                f"💼 *Puesto:* {oferta['Puesto']}\n"
                f"🏢 *Empresa:* {oferta['Empresa']}\n"
                f"💰 *Salario:* {oferta['Salario']}\n"
                f"📝 *Descripción:* {oferta['Descripción']}\n"
                f"📱 *Contacto:* {oferta['Contacto']}\n"
                f"📅 *Publicado:* {oferta['Fecha']}"
            )
            await update.message.reply_text(mensaje, parse_mode='Markdown')
        
        if len(ofertas) > 3:
            await update.message.reply_text(
                "ℹ️ Mostrando las 3 ofertas más recientes. Usa /buscar más tarde para ver nuevas ofertas."
            )
    except Exception as e:
        logger.error(f"❌ Error buscando ofertas: {e}")
        await update.message.reply_text("❌ Error al buscar ofertas")

async def buscar_candidatos(update: Update, context: CallbackContext):
    if not candidatos_db:
        await update.message.reply_text("⚠️ No se puede acceder a los candidatos")
        return
    
    try:
        candidatos = candidatos_db.get_all_records()
        if not candidatos:
            await update.message.reply_text("ℹ️ No hay candidatos registrados")
            return
        
        # Mostrar los 3 candidatos más recientes
        for candidato in reversed(candidatos[-3:]):
            mensaje = (
                f"👤 *Nombre:* {candidato['Nombre']}\n"
                f"🛠️ *Buscando:* {candidato['Trabajo']}\n"
                f"🎓 *Escolaridad:* {candidato['Escolaridad']}\n"
                f"📱 *Contacto:* {candidato['Contacto']}\n"
                f"📅 *Registrado:* {candidato['Fecha']}"
            )
            await update.message.reply_text(mensaje, parse_mode='Markdown')
        
        if len(candidatos) > 3:
            await update.message.reply_text(
                "ℹ️ Mostrando los 3 candidatos más recientes."
            )
    except Exception as e:
        logger.error(f"❌ Error buscando candidatos: {e}")
        await update.message.reply_text("❌ Error al buscar candidatos")

# ---- Función Principal ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configurar comandos del bot
    async def establecer_comandos(app):
        await app.bot.set_my_commands([
            ("start", "Iniciar el bot"),
            ("menu", "Mostrar menú"),
            ("ofertar", "Publicar oferta"),
            ("buscar", "Buscar ofertas"),
            ("buscoempleo", "Registrarse como candidato"),
            ("buscarcandidatos", "Buscar trabajadores"),
            ("ayuda", "Mostrar ayuda")
        ])
        logger.info("✅ Comandos configurados")
    
    app.post_init = establecer_comandos
    
    # Handlers para administradores
    app.add_handler(CommandHandler("enviar", enviar_mensaje_admin, filters=filters.User(ADMIN_IDS)))
    app.add_handler(CallbackQueryHandler(manejar_confirmacion_envio, pattern="^(env_confirm|env_cancel)"))
    
    # Handlers básicos
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
    
    # Handler para botones del menú
    app.add_handler(CallbackQueryHandler(lambda u, c: manejar_botones(u, c)))
    
    logger.info("🤖 Bot iniciado y listo para recibir mensajes...")
    app.run_polling()

# ---- Función para manejar botones ----
async def manejar_botones(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buscar":
        await buscar_ofertas(update, context)
    elif query.data == "ofertar":
        await iniciar_oferta(update, context)
    elif query.data == "registro":
        await iniciar_registro_trabajador(update, context)
    elif query.data == "buscar_candidatos":
        await buscar_candidatos(update, context)
    elif query.data == "ayuda":
        await ayuda(update, context)

if __name__ == '__main__':
    main()
