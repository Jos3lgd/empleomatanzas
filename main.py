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
ADMIN_IDS = [8046846584]  # Reemplaza con tu ID real
PALABRAS_PROHIBIDAS = {"singar", "fraude", "spam", "http://", "https://"}
ULTIMOS_MENSAJES = {}
PUESTO, EMPRESA, SALARIO, DESCRIPCION, CONTACTO = range(5)
NOMBRE, TRABAJO, ESCOLARIDAD, CONTACTO_TRABAJADOR = range(4)
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

def nuevo_candidato(user_id: int, datos: dict):
    if not candidatos_db:
        return False
    try:
        candidatos_db.append_row([
            str(len(candidatos_db.col_values(1)) + 1),
            datos["nombre"],
            datos["trabajo"],
            datos["escolaridad"],
            datos["contacto"],
            datetime.now().strftime("%Y-%m-%d"),
            str(user_id)
        ])
        return True
    except Exception as e:
        logger.error(f"Error guardando candidato: {e}")
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
        "/cancelar - Cancelar acción\n"
        "/enviar - Enviar mensaje masivo (admin)\n"
        "/ayuda - Mostrar esta ayuda"
    )

# Búsquedas
async def buscar_ofertas(update: Update, context: CallbackContext):
    context.user_data['pagina_ofertas'] = 1  # Inicializar página
    if not ofertas_db:
        await update.message.reply_text("Error al acceder a ofertas")
        return
    
    ofertas = ofertas_db.get_all_records()
    if not ofertas:
        await update.message.reply_text("No hay ofertas disponibles")
        return
    
    for oferta in reversed(ofertas[:RESULTADOS_POR_PAGINA]):
        await update.message.reply_text(
            f"💼 {oferta['Puesto']}\n"
            f"🏢 {oferta['Empresa']}\n"
            f"💰 {oferta['Salario']}\n"
            f"📞 {oferta['Contacto']}"
        )
    
    if len(ofertas) > RESULTADOS_POR_PAGINA:
        await update.message.reply_text(
            "¿Ver más ofertas?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_ofertas")]
            ])
        )

async def buscar_candidatos(update: Update, context: CallbackContext):
    context.user_data['pagina_candidatos'] = 1  # Inicializar página
    if not candidatos_db:
        await update.message.reply_text("Error al acceder a candidatos")
        return
    
    candidatos = candidatos_db.get_all_records()
    if not candidatos:
        await update.message.reply_text("No hay candidatos registrados")
        return
    
    for candidato in reversed(candidatos[:RESULTADOS_POR_PAGINA]):
        await update.message.reply_text(
            f"👤 {candidato['Nombre']}\n"
            f"🛠️ {candidato['Trabajo']}\n"
            f"📞 {candidato['Contacto']}"
        )
    
    if len(candidatos) > RESULTADOS_POR_PAGINA:
        await update.message.reply_text(
            "¿Ver más candidatos?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_candidatos")]
            ])
        )

# Paginación
async def ver_mas_ofertas(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    pagina = context.user_data.get('pagina_ofertas', 1) + 1
    context.user_data['pagina_ofertas'] = pagina
    
    if not ofertas_db:
        await query.message.reply_text("Error al acceder a ofertas")
        return
    
    ofertas = ofertas_db.get_all_records()
    if not ofertas:
        await query.message.reply_text("No hay más ofertas disponibles")
        return
    
    inicio = (pagina - 1) * RESULTADOS_POR_PAGINA
    fin = inicio + RESULTADOS_POR_PAGINA
    ofertas_pagina = ofertas[inicio:fin]
    
    if not ofertas_pagina:
        await query.message.reply_text("No hay más ofertas para mostrar")
        context.user_data['pagina_ofertas'] = 1
        return
    
    for oferta in reversed(ofertas_pagina):
        await query.message.reply_text(
            f"💼 {oferta['Puesto']}\n"
            f"🏢 {oferta['Empresa']}\n"
            f"💰 {oferta['Salario']}\n"
            f"📞 {oferta['Contacto']}"
        )
    
    if fin < len(ofertas):
        await query.message.reply_text(
            "¿Ver más ofertas?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_ofertas")]
            ])
        )

async def ver_mas_candidatos(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    pagina = context.user_data.get('pagina_candidatos', 1) + 1
    context.user_data['pagina_candidatos'] = pagina
    
    if not candidatos_db:
        await query.message.reply_text("Error al acceder a candidatos")
        return
    
    candidatos = candidatos_db.get_all_records()
    if not candidatos:
        await query.message.reply_text("No hay más candidatos disponibles")
        return
    
    inicio = (pagina - 1) * RESULTADOS_POR_PAGINA
    fin = inicio + RESULTADOS_POR_PAGINA
    candidatos_pagina = candidatos[inicio:fin]
    
    if not candidatos_pagina:
        await query.message.reply_text("No hay más candidatos para mostrar")
        context.user_data['pagina_candidatos'] = 1
        return
    
    for candidato in reversed(candidatos_pagina):
        await query.message.reply_text(
            f"👤 {candidato['Nombre']}\n"
            f"🛠️ {candidato['Trabajo']}\n"
            f"📞 {candidato['Contacto']}"
        )
    
    if fin < len(candidatos):
        await query.message.reply_text(
            "¿Ver más candidatos?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_candidatos")]
            ])
        )

# ConversationHandler para oferta
async def iniciar_oferta(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("💼 Ingresa el puesto de trabajo:")
    return PUESTO

async def guardar_puesto(update: Update, context: CallbackContext):
    context.user_data['oferta'] = {'puesto': update.message.text}
    await update.message.reply_text("🏢 Ingresa el nombre de la empresa:")
    return EMPRESA

async def guardar_empresa(update: Update, context: CallbackContext):
    context.user_data['oferta']['empresa'] = update.message.text
    await update.message.reply_text("💰 Ingresa el salario:")
    return SALARIO

async def guardar_salario(update: Update, context: CallbackContext):
    context.user_data['oferta']['salario'] = update.message.text
    await update.message.reply_text("📝 Ingresa la descripción del puesto:")
    return DESCRIPCION

async def guardar_descripcion(update: Update, context: CallbackContext):
    context.user_data['oferta']['descripcion'] = update.message.text
    await update.message.reply_text("📞 Ingresa el contacto (teléfono, email, etc.):")
    return CONTACTO

async def guardar_contacto(update: Update, context: CallbackContext):
    context.user_data['oferta']['contacto'] = update.message.text
    user_id = update.effective_user.id
    if nueva_oferta(user_id, context.user_data['oferta']):
        await update.message.reply_text("✅ Oferta registrada con éxito.")
    else:
        await update.message.reply_text("❌ Error al registrar la oferta.")
    context.user_data.clear()
    return ConversationHandler.END

# ConversationHandler para registro de candidato
async def iniciar_registro(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("👤 Ingresa tu nombre completo:")
    return NOMBRE

async def guardar_nombre(update: Update, context: CallbackContext):
    context.user_data['candidato'] = {'nombre': update.message.text}
    await update.message.reply_text("🛠️ Ingresa el tipo de trabajo que buscas:")
    return TRABAJO

async def guardar_trabajo(update: Update, context: CallbackContext):
    context.user_data['candidato']['trabajo'] = update.message.text
    await update.message.reply_text("🎓 Ingresa tu nivel de escolaridad:")
    return ESCOLARIDAD

async def guardar_escolaridad(update: Update, context: CallbackContext):
    context.user_data['candidato']['escolaridad'] = update.message.text
    await update.message.reply_text("📞 Ingresa tu contacto (teléfono, email, etc.):")
    return CONTACTO_TRABAJADOR

async def guardar_contacto_trabajador(update: Update, context: CallbackContext):
    context.user_data['candidato']['contacto'] = update.message.text
    user_id = update.effective_user.id
    if nuevo_candidato(user_id, context.user_data['candidato']):
        await update.message.reply_text("✅ Registro como candidato completado.")
    else:
        await update.message.reply_text("❌ Error al registrar candidato.")
    context.user_data.clear()
    return ConversationHandler.END

# Comando para cancelar
async def cancelar(update: Update, context: CallbackContext):
    await update.message.reply_text("Acción cancelada. Usa /menu para continuar.")
    context.user_data.clear()
    return ConversationHandler.END

# Comando para enviar mensajes masivos
async def enviar_mensaje(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Solo los administradores pueden usar este comando.")
        return
    
    if not context.args:
        await update.message.reply_text("📝 Por favor, proporciona el mensaje a enviar. Ejemplo: /enviar Hola a todos")
        return
    
    mensaje = " ".join(context.args)
    usuarios = usuarios_db.get_all_records()
    
    if not usuarios:
        await update.message.reply_text("No hay usuarios registrados.")
        return
    
    enviados = 0
    fallidos = 0
    for usuario in usuarios:
        try:
            chat_id = int(usuario['ChatID'])
            await context.bot.send_message(chat_id=chat_id, text=mensaje)
            enviados += 1
            time.sleep(0.05)  # Evitar límites de Telegram
        except Exception as e:
            logger.error(f"Error enviando mensaje a {usuario['ChatID']}: {e}")
            fallidos += 1
    
    await update.message.reply_text(
        f"📬 Mensaje enviado a {enviados} usuarios. "
        f"{'No se pudo enviar a ' + str(fallidos) + ' usuarios.' if fallidos else ''}"
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
            ("cancelar", "Cancelar acción"),
            ("enviar", "Enviar mensaje masivo (admin)"),
            ("ayuda", "Mostrar ayuda")
        ])
    
    app.post_init = set_commands
    
    # Configurar ConversationHandlers
    oferta_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(iniciar_oferta, pattern="ofertar_trabajo")],
        states={
            PUESTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_puesto)],
            EMPRESA: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_empresa)],
            SALARIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_salario)],
            DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_descripcion)],
            CONTACTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_contacto)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )
    
    registro_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(iniciar_registro, pattern="registro_trabajador")],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_nombre)],
            TRABAJO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_trabajo)],
            ESCOLARIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_escolaridad)],
            CONTACTO_TRABAJADOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_contacto_trabajador)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("buscar", buscar_ofertas))
    app.add_handler(CommandHandler("buscarcandidatos", buscar_candidatos))
    app.add_handler(CommandHandler("cancelar", cancelar))
    app.add_handler(CommandHandler("enviar", enviar_mensaje))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(oferta_conv)
    app.add_handler(registro_conv)
    
    logger.info("Bot iniciado")
    app.run_polling()

if __name__ == '__main__':
    main()
