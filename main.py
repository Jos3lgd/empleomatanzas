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
            str(len(ofertas_db.col_values(1)) + 1,
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
        await update.message.reply_text(
            "📲 Menú Principal - Elige una opción:",
            reply_markup=InlineKeyboardMarkup(teclado)
        )
    except Exception as e:
        logger.error(f"❌ Error mostrando menú: {e}")

async def ayuda(update: Update, context: CallbackContext):
    try:
        mensaje = (
            "ℹ️ *Ayuda del Bot*\n\n"
            "📌 *Comandos disponibles:*\n"
            "/start - Reiniciar el bot\n"
            "/menu - Mostrar menú interactivo\n"
            "/ofertar - Publicar una oferta\n"
            "/buscar - Buscar ofertas\n"
            "/buscoempleo - Registrarse como candidato\n"
            "/buscarcandidatos - Buscar trabajadores\n"
            "/ayuda - Mostrar esta ayuda\n\n"
            "⚠️ Las ofertas se eliminan automáticamente después de 15 días."
        )
        await update.message.reply_text(mensaje, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"❌ Error mostrando ayuda: {e}")

# ---- Sistema de Mensajería Masiva ----
async def enviar_mensaje_admin(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("🚫 Acceso restringido a administradores")
            return
        
        if not context.args:
            await update.message.reply_text("ℹ️ Uso: /enviar <mensaje>")
            return
        
        mensaje = ' '.join(context.args)
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"env_confirm:{mensaje}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="env_cancel")]
        ]
        await update.message.reply_text(
            f"📢 Mensaje preparado:\n\n{mensaje}\n\n¿Enviar a todos los usuarios?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"❌ Error en mensajería masiva: {e}")

async def manejar_confirmacion_envio(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("env_confirm:"):
            mensaje = query.data.split(":", 1)[1]
            await query.edit_message_text("⏳ Enviando mensajes...")
            
            usuarios = usuarios_db.get_all_records()
            exitosos = 0
            total = len(usuarios)
            
            for usuario in usuarios:
                try:
                    if usuario["Notificaciones"] == "activo" and usuario["ChatID"]:
                        await context.bot.send_message(
                            chat_id=int(usuario["ChatID"]),
                            text=mensaje,
                            parse_mode='Markdown'
                        )
                        exitosos += 1
                        time.sleep(0.3)
                except Exception as e:
                    logger.error(f"Error enviando a {usuario.get('ChatID')}: {e}")
            
            await query.edit_message_text(
                f"✅ Envío completado\n"
                f"Total: {total}\n"
                f"Exitosos: {exitosos}\n"
                f"Fallidos: {total - exitosos}"
            )
        else:
            await query.edit_message_text("❌ Envío cancelado")
    except Exception as e:
        logger.error(f"❌ Error en confirmación de envío: {e}")

# ---- Flujos de Conversación ----
async def iniciar_oferta(update: Update, context: CallbackContext):
    try:
        if update.callback_query:
            await update.callback_query.message.reply_text("💼 ¿Cuál es el puesto de trabajo?")
        else:
            await update.message.reply_text("💼 ¿Cuál es el puesto de trabajo?")
        return PUESTO
    except Exception as e:
        logger.error(f"❌ Error iniciando oferta: {e}")
        return ConversationHandler.END

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

async def iniciar_registro_trabajador(update: Update, context: CallbackContext):
    try:
        if update.callback_query:
            await update.callback_query.message.reply_text("👤 ¿Cuál es tu nombre completo?")
        else:
            await update.message.reply_text("👤 ¿Cuál es tu nombre completo?")
        return NOMBRE
    except Exception as e:
        logger.error(f"❌ Error iniciando registro: {e}")
        return ConversationHandler.END

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
        await update.message.reply_text("✅ ¡Registro completado exitosamente!")
    except Exception as e:
        logger.error(f"❌ Error registrando candidato: {e}")
        await update.message.reply_text("❌ Error al guardar tu información")
    
    return ConversationHandler.END

# ---- Búsquedas con Paginación ----
async def buscar_ofertas(update: Update, context: CallbackContext):
    try:
        if not ofertas_db:
            await update.message.reply_text("⚠️ Error al acceder a las ofertas")
            return
        
        all_ofertas = ofertas_db.get_all_records()
        if not all_ofertas:
            await update.message.reply_text("ℹ️ No hay ofertas disponibles")
            return
        
        page = context.user_data.get("oferta_page", 0)
        start_idx = page * RESULTADOS_POR_PAGINA
        end_idx = start_idx + RESULTADOS_POR_PAGINA
        
        for oferta in reversed(all_ofertas[start_idx:end_idx]):
            msg = (
                f"💼 *Puesto:* {oferta['Puesto']}\n"
                f"🏢 *Empresa:* {oferta['Empresa']}\n"
                f"💰 *Salario:* {oferta['Salario']}\n"
                f"📝 *Descripción:* {oferta['Descripción']}\n"
                f"📱 *Contacto:* {oferta['Contacto']}\n"
                f"📅 *Publicado:* {oferta['Fecha']}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        
        # Mostrar botones de paginación
        if end_idx < len(all_ofertas):
            context.user_data["oferta_page"] = page + 1
            await update.message.reply_text(
                "¿Ver más ofertas?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➡️ Siguiente página", callback_data="ver_mas_ofertas")]
                ))
        else:
            context.user_data["oferta_page"] = 0
            await update.message.reply_text("✅ Has visto todas las ofertas")
            
    except Exception as e:
        logger.error(f"❌ Error buscando ofertas: {e}")
        await update.message.reply_text("❌ Error al buscar ofertas")

async def buscar_candidatos(update: Update, context: CallbackContext):
    try:
        if not candidatos_db:
            await update.message.reply_text("⚠️ Error al acceder a candidatos")
            return
        
        all_candidatos = candidatos_db.get_all_records()
        if not all_candidatos:
            await update.message.reply_text("ℹ️ No hay candidatos registrados")
            return
        
        page = context.user_data.get("candidato_page", 0)
        start_idx = page * RESULTADOS_POR_PAGINA
        end_idx = start_idx + RESULTADOS_POR_PAGINA
        
        for candidato in reversed(all_candidatos[start_idx:end_idx]):
            msg = (
                f"👤 *Nombre:* {candidato['Nombre']}\n"
                f"🛠️ *Buscando:* {candidato['Trabajo']}\n"
                f"🎓 *Escolaridad:* {candidato['Escolaridad']}\n"
                f"📱 *Contacto:* {candidato['Contacto']}\n"
                f"📅 *Registrado:* {candidato['Fecha']}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        
        # Mostrar botones de paginación
        if end_idx < len(all_candidatos):
            context.user_data["candidato_page"] = page + 1
            await update.message.reply_text(
                "¿Ver más candidatos?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➡️ Siguiente página", callback_data="ver_mas_candidatos")]
                ))
        else:
            context.user_data["candidato_page"] = 0
            await update.message.reply_text("✅ Has visto todos los candidatos")
            
    except Exception as e:
        logger.error(f"❌ Error buscando candidatos: {e}")
        await update.message.reply_text("❌ Error al buscar candidatos")

# ---- Manejador de Botones ----
async def manejar_botones(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "buscar":
            context.user_data["oferta_page"] = 0
            await buscar_ofertas(update, context)
        elif query.data == "ofertar":
            await iniciar_oferta(update, context)
        elif query.data == "registro":
            await iniciar_registro_trabajador(update, context)
        elif query.data == "buscar_candidatos":
            context.user_data["candidato_page"] = 0
            await buscar_candidatos(update, context)
        elif query.data == "ayuda":
            await ayuda(update, context)
        elif query.data == "ver_mas_ofertas":
            await buscar_ofertas(update, context)
        elif query.data == "ver_mas_candidatos":
            await buscar_candidatos(update, context)
            
    except Exception as e:
        logger.error(f"❌ Error manejando botones: {e}")

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
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("buscar", buscar_ofertas))
    app.add_handler(CommandHandler("buscarcandidatos", buscar_candidatos))
    
    # Handlers para administradores
    app.add_handler(CommandHandler("enviar", enviar_mensaje_admin, filters=filters.User(ADMIN_IDS)))
    app.add_handler(CallbackQueryHandler(manejar_confirmacion_envio, pattern=r"^(env_confirm|env_cancel)"))
    
    # Handlers de conversación
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
    
    # Manejador de botones
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    logger.info("🤖 Bot iniciado correctamente")
    app.run_polling()

if __name__ == '__main__':
    main()
