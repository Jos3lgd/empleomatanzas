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
        logger.error("No se pudo acceder a usuarios_db")
        return False
    try:
        # Buscar si el usuario ya existe
        cell = usuarios_db.find(str(user_id), in_column=1)
        # Usuario existe, actualizar la fecha
        row = cell.row
        usuarios_db.update_cell(row, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info(f"Fecha actualizada para usuario {user_id}")
        return True
    except gspread.exceptions.CellNotFound:
        # Usuario no existe, crear nueva fila
        usuarios_db.append_row([
            str(user_id),
            nombre,
            f"@{username}" if username else "Sin username",
            str(chat_id),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "0",
            "activo"
        ])
        logger.info(f"Nuevo usuario registrado: {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error registrando usuario {user_id}: {e}")
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
    if registrar_usuario(user.id, user.first_name, user.username, chat_id):
        logger.info(f"Usuario {user.id} registrado o actualizado correctamente")
    else:
        logger.error(f"Fallo al registrar usuario {user.id}")
    await update.message.reply_photo(
        photo="https://github.com/Jos3lgd/mapa-circuitos-matanzas/blob/main/empleoMTZ.jpg?raw=true",
        caption="👋 ¡Bienvenid@ al Bot Empleo Matanzas!\n\nUsa /menu para ver opciones.\nUsa /ayuda para ver cómo funciona."
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
        "*Hola, gracias por utilizar nuestro Bot*\n\n"
        "Puedes utilizar los comandos disponibles en el menú en la parte inferior izquierda o teclearlos:\n\n"
        "📎 /start \\— Iniciar el bot\n"
        "📋 /menu \\— Ver el menú interactivo\n"
        "💼 /ofertar \\— Publicar una oferta de empleo\n"
        "🔍 /buscar \\— Buscar ofertas publicadas\n"
        "🧑‍💼 /buscoempleo \\— Registrarte como buscador de empleo\n"
        "❌ /cancelar \\— Cancelar una acción activa\n\n"
        "👩‍💻 Este Bot está en fase Beta, si encuentras algún problema o tienes sugerencias puedes contactar con Soporte @AtencionPoblacionBot\n\n"
        "*⚠️ ATENCIÓN\\!\\!\\!* Las ofertas se irán eliminando automáticamente cada 15 días, tenga eso en cuenta",
        parse_mode="MarkdownV2"
    )

# Búsquedas
async def buscar_ofertas(update: Update, context: CallbackContext):
    context.user_data['pagina_ofertas'] = 0  # Inicializar en 0 para la primera página
    logger.info("Iniciando búsqueda de ofertas")
    if not ofertas_db:
        await update.message.reply_text("Error al acceder a ofertas")
        return
    
    ofertas = ofertas_db.get_all_records()
    logger.info(f"Se encontraron {len(ofertas)} ofertas")
    if not ofertas:
        await update.message.reply_text("No hay ofertas disponibles")
        return
    
    # Mostrar primeras ofertas
    inicio = 0
    fin = RESULTADOS_POR_PAGINA
    ofertas_pagina = ofertas[inicio:fin]
    
    mensaje = ""
    for oferta in reversed(ofertas_pagina):
        mensaje += (
            f"💼 {oferta['Puesto']}\n"
            f"🏢 {oferta['Empresa']}\n"
            f"💰 {oferta['Salario']}\n"
            f"📞 {oferta['Contacto']}\n\n"
        )
    
    # Crear teclado con botón "Ver más" si hay más resultados
    keyboard = []
    if len(ofertas) > fin:
        keyboard.append([InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_ofertas")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(
        mensaje or "No hay ofertas para mostrar",
        reply_markup=reply_markup
    )

async def buscar_candidatos(update: Update, context: CallbackContext):
    context.user_data['pagina_candidatos'] = 0  # Inicializar en 0 para la primera página
    logger.info("Iniciando búsqueda de candidatos")
    if not candidatos_db:
        await update.message.reply_text("Error al acceder a candidatos")
        return
    
    candidatos = candidatos_db.get_all_records()
    logger.info(f"Se encontraron {len(candidatos)} candidatos")
    if not candidatos:
        await update.message.reply_text("No hay candidatos registrados")
        return
    
    # Mostrar primeros candidatos
    inicio = 0
    fin = RESULTADOS_POR_PAGINA
    candidatos_pagina = candidatos[inicio:fin]
    
    mensaje = ""
    for candidato in reversed(candidatos_pagina):
        mensaje += (
            f"👤 {candidato['Nombre']}\n"
            f"🛠️ {candidato['Trabajo']}\n"
            f"📞 {candidato['Contacto']}\n\n"
        )
    
    # Crear teclado con botón "Ver más" si hay más resultados
    keyboard = []
    if len(candidatos) > fin:
        keyboard.append([InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_candidatos")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(
        mensaje or "No hay candidatos para mostrar",
        reply_markup=reply_markup
    )

# Paginación
async def ver_mas_ofertas(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    logger.info("Procesando ver_mas_ofertas")
    
    # Incrementar página
    pagina = context.user_data.get('pagina_ofertas', 0) + 1
    context.user_data['pagina_ofertas'] = pagina
    logger.info(f"Mostrando página {pagina} de ofertas")
    
    if not ofertas_db:
        await query.message.edit_text("Error al acceder a ofertas")
        return
    
    ofertas = ofertas_db.get_all_records()
    if not ofertas:
        await query.message.edit_text("No hay más ofertas disponibles")
        context.user_data['pagina_ofertas'] = 0
        return
    
    # Calcular índices
    inicio = pagina * RESULTADOS_POR_PAGINA
    fin = inicio + RESULTADOS_POR_PAGINA
    ofertas_pagina = ofertas[inicio:fin]
    logger.info(f"Ofertas en página {pagina}: {len(ofertas_pagina)}")
    
    if not ofertas_pagina:
        await query.message.edit_text("No hay más ofertas para mostrar")
        context.user_data['pagina_ofertas'] = 0
        return
    
    # Construir mensaje
    mensaje = ""
    for oferta in reversed(ofertas_pagina):
        mensaje += (
            f"💼 {oferta['Puesto']}\n"
            f"🏢 {oferta['Empresa']}\n"
            f"💰 {oferta['Salario']}\n"
            f"📞 {oferta['Contacto']}\n\n"
        )
    
    # Actualizar teclado
    keyboard = []
    if fin < len(ofertas):
        keyboard.append([InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_ofertas")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    try:
        await query.message.edit_text(
            mensaje or "No hay más ofertas para mostrar",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error editando mensaje: {e}")
        await query.message.reply_text(
            mensaje or "No hay más ofertas para mostrar",
            reply_markup=reply_markup
        )

async def ver_mas_candidatos(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    logger.info("Procesando ver_mas_candidatos")
    
    # Incrementar página
    pagina = context.user_data.get('pagina_candidatos', 0) + 1
    context.user_data['pagina_candidatos'] = pagina
    logger.info(f"Mostrando página {pagina} de candidatos")
    
    if not candidatos_db:
        await query.message.edit_text("Error al acceder a candidatos")
        return
    
    candidatos = candidatos_db.get_all_records()
    if not candidatos:
        await query.message.edit_text("No hay más candidatos disponibles")
        context.user_data['pagina_candidatos'] = 0
        return
    
    # Calcular índices
    inicio = pagina * RESULTADOS_POR_PAGINA
    fin = inicio + RESULTADOS_POR_PAGINA
    candidatos_pagina = candidatos[inicio:fin]
    logger.info(f"Candidatos en página {pagina}: {len(candidatos_pagina)}")
    
    if not candidatos_pagina:
        await query.message.edit_text("No hay más candidatos para mostrar")
        context.user_data['pagina_candidatos'] = 0
        return
    
    # Construir mensaje
    mensaje = ""
    for candidato in reversed(candidatos_pagina):
        mensaje += (
            f"👤 {candidato['Nombre']}\n"
            f"🛠️ {candidato['Trabajo']}\n"
            f"📞 {candidato['Contacto']}\n\n"
        )
    
    # Actualizar teclado
    keyboard = []
    if fin < len(candidatos):
        keyboard.append([InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_candidatos")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    try:
        await query.message.edit_text(
            mensaje or "No hay más candidatos para mostrar",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error editando mensaje: {e}")
        await query.message.reply_text(
            mensaje or "No hay más candidatos para mostrar",
            reply_markup=reply_markup
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
    logger.info(f"Callback recibido: {query.data}")
    
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
        await ver_mas_ofertas(update, context)
    elif query.data == "ver_mas_candidatos":
        await ver_mas_candidatos(update, context)

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
