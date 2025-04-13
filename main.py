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
candidatos_db = None

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

# ---- Funciones de mensajería ----
async def enviar_mensaje_a_usuario(context: CallbackContext, chat_id: int, mensaje: str):
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=mensaje,
            parse_mode='Markdown'
        )
        return True
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje a {chat_id}: {e}")
        return False

async def enviar_mensaje_admin(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Uso: /enviar <mensaje>")
        return
    
    mensaje = ' '.join(context.args)
    await update.message.reply_text(
        f"¿Enviar este mensaje a todos los usuarios?\n\n{mensaje}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, enviar a todos", callback_data=f"confirmar_envio:{mensaje}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_envio")]
        ])
    )

async def confirmar_envio(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("confirmar_envio:"):
        mensaje = query.data.split(":", 1)[1]
        usuarios = usuarios_db.get_all_records()
        total = exitosos = 0
        
        await query.edit_message_text(f"⏳ Enviando mensaje a {len(usuarios)} usuarios...")
        
        for usuario in usuarios:
            if usuario.get("Notificaciones", "activo") == "activo":
                try:
                    await enviar_mensaje_a_usuario(context, int(usuario["ChatID"]), mensaje)
                    exitosos += 1
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error enviando a {usuario['ChatID']}: {e}")
                total += 1
        
        await query.edit_message_text(
            f"✅ Envío completado!\nTotal: {total}\nExitosos: {exitosos}\nFallidos: {total - exitosos}"
        )
    else:
        await query.edit_message_text("❌ Envío cancelado")

# ---- Funciones del menú ----
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
    await update.message.reply_text("📲 Elige una opción:", reply_markup=InlineKeyboardMarkup(teclado))

async def manejar_botones(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buscar":
        await buscar_ofertas(query, context)
    elif query.data == "ofertar":
        await iniciar_oferta(query, context)
    elif query.data == "registro":
        await iniciar_registro_trabajador(query, context)
    elif query.data == "buscar_candidatos":
        await buscar_candidatos(query, context)
    elif query.data == "ayuda":
        await ayuda(query, context)

# ---- Flujos de conversación ----
async def iniciar_oferta(update: Update, context: CallbackContext):
    if update.callback_query:
        await update.callback_query.message.reply_text("💼 ¿Cuál es el puesto de trabajo?")
    else:
        await update.message.reply_text("💼 ¿Cuál es el puesto de trabajo?")
    return PUESTO

async def recibir_puesto(update: Update, context: CallbackContext):
    context.user_data["puesto"] = update.message.text
    await update.message.reply_text("🏢 ¿Nombre de la empresa?")
    return EMPRESA

async def recibir_empresa(update: Update, context: CallbackContext):
    context.user_data["empresa"] = update.message.text
    await update.message.reply_text("💰 ¿Salario ofrecido?")
    return SALARIO

async def recibir_salario(update: Update, context: CallbackContext):
    context.user_data["salario"] = update.message.text
    await update.message.reply_text("📝 Breve descripción del puesto:")
    return DESCRIPCION

async def recibir_descripcion(update: Update, context: CallbackContext):
    context.user_data["descripcion"] = update.message.text
    await update.message.reply_text("📱 ¿Forma de contacto?")
    return CONTACTO

async def recibir_contacto(update: Update, context: CallbackContext):
    context.user_data["contacto"] = update.message.text
    user = update.effective_user
    if nueva_oferta(user.id, context.user_data):
        await update.message.reply_text("✅ ¡Oferta publicada con éxito!")
    else:
        await update.message.reply_text("❌ Error al guardar la oferta.")
    return ConversationHandler.END

async def iniciar_registro_trabajador(update: Update, context: CallbackContext):
    if update.callback_query:
        await update.callback_query.message.reply_text("👤 ¿Cuál es tu nombre completo?")
    else:
        await update.message.reply_text("👤 ¿Cuál es tu nombre completo?")
    return NOMBRE

async def recibir_nombre(update: Update, context: CallbackContext):
    context.user_data["nombre"] = update.message.text
    await update.message.reply_text("🛠️ ¿Qué tipo de trabajo estás buscando?")
    return TRABAJO

async def recibir_trabajo(update: Update, context: CallbackContext):
    context.user_data["trabajo"] = update.message.text
    await update.message.reply_text("🎓 ¿Cuál es tu escolaridad o título?")
    return ESCOLARIDAD

async def recibir_escolaridad(update: Update, context: CallbackContext):
    context.user_data["escolaridad"] = update.message.text
    await update.message.reply_text("📞 ¿Cómo te pueden contactar?")
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
        await update.message.reply_text("✅ ¡Tu perfil fue registrado correctamente!")
    except Exception as e:
        logger.error(f"❌ Error registrando candidato: {e}")
        await update.message.reply_text("❌ Ocurrió un error al guardar tu información.")
    return ConversationHandler.END

# ---- Búsquedas ----
async def buscar_ofertas(update: Update, context: CallbackContext):
    if not ofertas_db:
        await update.message.reply_text("⚠️ No se puede acceder a la base de datos.")
        return
    
    try:
        todas = ofertas_db.get_all_records()
        if not todas:
            await update.message.reply_text("😕 Aún no hay ofertas publicadas.")
            return
        
        for oferta in reversed(todas[:5]):  # Mostrar las 5 más recientes
            msg = (
                f"💼 *Puesto:* {oferta['Puesto']}\n"
                f"🏢 *Empresa:* {oferta['Empresa']}\n"
                f"💰 *Salario:* {oferta['Salario']}\n"
                f"📝 *Descripción:* {oferta['Descripción']}\n"
                f"📱 *Contacto:* {oferta['Contacto']}\n"
                f"📅 *Fecha:* {oferta['Fecha']}"
            )
            await update.message.reply_markdown(msg)
            
    except Exception as e:
        logger.error(f"❌ Error buscando ofertas: {e}")
        await update.message.reply_text("❌ Error buscando ofertas.")

async def buscar_candidatos(update: Update, context: CallbackContext):
    if not candidatos_db:
        await update.message.reply_text("⚠️ No se puede acceder a la base de datos.")
        return
    
    try:
        todos = candidatos_db.get_all_records()
        if not todos:
            await update.message.reply_text("😕 No hay personas registradas buscando empleo.")
            return
        
        for candidato in reversed(todos[:5]):  # Mostrar los 5 más recientes
            msg = (
                f"👤 *Nombre:* {candidato['Nombre']}\n"
                f"🛠️ *Trabajo buscado:* {candidato['Trabajo']}\n"
                f"🎓 *Escolaridad:* {candidato['Escolaridad']}\n"
                f"📱 *Contacto:* {candidato['Contacto']}\n"
                f"📅 *Fecha:* {candidato['Fecha']}"
            )
            await update.message.reply_markdown(msg)
            
    except Exception as e:
        logger.error(f"❌ Error al buscar candidatos: {e}")
        await update.message.reply_text("❌ Error al consultar la base de datos.")

# ---- Función principal ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configurar comandos
    async def establecer_comandos(app):
        await app.bot.set_my_commands([
            ("start", "Iniciar el bot"),
            ("menu", "Ver menú interactivo"),
            ("ofertar", "Publicar oferta de empleo"),
            ("buscar", "Buscar ofertas"),
            ("buscoempleo", "Registrarte como buscador de empleo"),
            ("buscarcandidatos", "Buscar trabajadores"),
            ("help", "Ver ayuda")
        ])
    
    app.post_init = establecer_comandos
    
    # Handlers para administradores
    app.add_handler(CommandHandler("enviar", enviar_mensaje_admin, filters=filters.User(ADMIN_IDS)))
    app.add_handler(CallbackQueryHandler(confirmar_envio, pattern="^(confirmar_envio|cancelar_envio)"))
    
    # Handlers para usuarios
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
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
        fallbacks=[CommandHandler("cancelar", lambda u,c: ConversationHandler.END)],
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
        fallbacks=[CommandHandler("cancelar", lambda u,c: ConversationHandler.END)],
        per_message=False
    )
    
    app.add_handler(ofertar_handler)
    app.add_handler(registro_handler)
    
    # Handler para botones del menú
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    logger.info("🤖 Bot iniciado y escuchando...")
    app.run_polling()

if __name__ == '__main__':
    main()
