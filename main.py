import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
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
import requests
import time

# ---- Logging ----
logging.basicConfig(format='[%(asctime)s] [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- Token y conexión ----
TOKEN = os.getenv('TELEGRAM_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

sheet = None
ofertas_db = None
usuarios_db = None

try:
    logger.info("🔧 Intentando conectar con Google Sheets...")
    
    # Opción 1: Credenciales desde variable de entorno (para Railway)
    creds_json = os.getenv('GOOGLE_CREDS_JSON')  # Nombre exacto de tu variable
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            CREDS = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            logger.info("✅ Credenciales cargadas desde variable de entorno")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decodificando JSON de credenciales: {str(e)}")
            raise
    else:
        # Opción 2: Credenciales desde archivo (para desarrollo local)
        try:
            CREDS = Credentials.from_service_account_file('credenciales.json', scopes=SCOPES)
            logger.info("✅ Credenciales cargadas desde archivo local")
        except Exception as e:
            logger.error(f"❌ Error cargando credenciales desde archivo: {str(e)}")
            raise
    
    # Conexión con Google Sheets
    client = gspread.authorize(CREDS)
    sheet = client.open("EmpleoMatanzasDB")
    ofertas_db = sheet.worksheet("Ofertas")
    usuarios_db = sheet.worksheet("Usuarios")
    logger.info("✅ Conexión exitosa con Google Sheets")
    
except Exception as e:
    logger.error(f"❌ Error crítico conectando con Google Sheets: {str(e)}")
    # Decide si quieres que el bot continúe sin funcionalidad de Sheets
    # raise  # Descomenta si quieres que falle completamente sin Sheets

# ---- Constantes ----
PALABRAS_PROHIBIDAS = {"singar", "fraude", "spam", "http://", "https://"}
ULTIMOS_MENSAJES = {}
PUESTO, EMPRESA, SALARIO, DESCRIPCION, CONTACTO = range(5)
NOMBRE, TRABAJO, ESCOLARIDAD, CONTACTO_TRABAJADOR = range(5, 9)

# ---- Base de datos y limpieza ----
def registrar_usuario(user_id: int, nombre: str, username: str):
    if not usuarios_db:
        return False
    try:
        try:
            usuarios_db.find(str(user_id))
            return True
        except gspread.exceptions.CellNotFound:
            pass
        usuarios_db.append_row([
            str(user_id), nombre,
            f"@{username}" if username else "Sin username",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "0"
        ])
        logger.info(f"👤 Usuario registrado: {user_id}")
        return True
    except Exception as e:
        logger.error("❌ Error registrando usuario: %s", str(e))
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
        count = int(usuarios_db.cell(cell.row, 5).value)
        usuarios_db.update_cell(cell.row, 5, str(count + 1))
        logger.info("📝 Oferta guardada")
        limpiar_ofertas_y_candidatos()
        return True
    except Exception as e:
        logger.error("❌ Error guardando oferta: %s", str(e))
        return False

def limpiar_hoja_por_fecha(hoja, nombre_hoja=""):
    try:
        datos = hoja.get_all_values()
        if len(datos) < 2:
            return
        encabezado = datos[0]
        filas = datos[1:]
        idx_fecha = encabezado.index("Fecha")
        hoy = datetime.now()
        nuevas_filas = [encabezado]
        for fila in filas:
            try:
                fecha = datetime.strptime(fila[idx_fecha], "%Y-%m-%d")
                if (hoy - fecha).days <= 15:
                    nuevas_filas.append(fila)
            except:
                nuevas_filas.append(fila)
        if len(nuevas_filas) != len(datos):
            hoja.clear()
            hoja.append_rows(nuevas_filas)
            logger.info(f"🧹 Limpieza realizada en hoja '{nombre_hoja}'")
    except Exception as e:
        logger.error(f"❌ Error limpiando hoja '{nombre_hoja}': {str(e)}")

def limpiar_ofertas_y_candidatos():
    if ofertas_db:
        limpiar_hoja_por_fecha(ofertas_db, "Ofertas")
    if sheet:
        try:
            candidatos_db = sheet.worksheet("Candidatos")
            limpiar_hoja_por_fecha(candidatos_db, "Candidatos")
        except Exception as e:
            logger.warning("⚠️ No se pudo limpiar la hoja Candidatos: %s", str(e))

# ---- Antispam y comandos generales ----
async def anti_spam(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    ahora = datetime.now()
    texto = update.message.text.lower() if update.message.text else ""
    if any(p in texto for p in PALABRAS_PROHIBIDAS):
        await update.message.delete()
        await update.effective_chat.send_message("🚫 No se permiten enlaces o contenido sospechoso")
        return
    ULTIMOS_MENSAJES.setdefault(user_id, [])
    ULTIMOS_MENSAJES[user_id] = [t for t in ULTIMOS_MENSAJES[user_id] if ahora - t < timedelta(minutes=1)]
    if len(ULTIMOS_MENSAJES[user_id]) >= 5:
        await update.message.reply_text("⏳ Por favor, espera antes de enviar más mensajes.")
        return
    ULTIMOS_MENSAJES[user_id].append(ahora)

async def start(update: Update, context: CallbackContext):
    logger.info("🚀 /start recibido")
    await anti_spam(update, context)
    user = update.effective_user
    if usuarios_db:
        registrar_usuario(user.id, user.first_name, user.username)
    await update.message.reply_photo(
        photo="https://github.com/Jos3lgd/mapa-circuitos-matanzas/blob/main/empleoMTZ.jpg?raw=true",
        caption="👋 ¡Bienvenid@ al Bot Empleo Matanzas!\n\n"
        "💻 Este Bot está desarrollado por el equipo de @infomatanzas y está en fase Beta.\n"
        "Usa /menu para ver opciones."
    )

async def ayuda(update: Update, context: CallbackContext):
    logger.info("ℹ️ Ayuda solicitada")
    mensaje = (
        "*Hola, gracias por utilizar nuestro Bot*\n\n"
        "Puedes utilizar los comandos disponibles en el menú en la parte inferior izquierda o teclearlos:\n\n"
        "📎 /start — Iniciar el bot\n"
        "📋 /menu — Ver el menú interactivo\n"
        "💼 /ofertar — Publicar una oferta de empleo\n"
        "🔍 /buscar — Buscar ofertas publicadas\n"
        "🧑‍💼 /buscoempleo — Registrarte como buscador de empleo\n"
        "❌ /cancelar — Cancelar una acción activa\n\n"
        "👩‍💻 Este Bot está en fase Beta, si encuentras algún problema o tienes sugerencias puedes contactar con Soporte @AtencionPoblacionBot\n\n"
        "⚠️ ATENCIÓN!!! Las ofertas se irán eliminando automáticamente cada 15 días, tenga eso en cuenta"
    )
    if update.message:
        await update.message.reply_markdown(mensaje)
    elif update.callback_query:
        await update.callback_query.message.reply_markdown(mensaje)
        await update.callback_query.answer()

async def menu(update: Update, context: CallbackContext):
    teclado = [
        [InlineKeyboardButton("🔍 Ofertas de trabajo", callback_data="buscar")],
        [InlineKeyboardButton("💼 Ofrecer trabajo", callback_data="ofertar")],
        [InlineKeyboardButton("🧑‍💼 Solicitar trabajo", callback_data="registro")],
        [InlineKeyboardButton("🔎 Buscar trabajadores", callback_data="buscar_candidatos")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="ayuda")]
    ]
    await update.message.reply_text("📲 Elige una opción:", reply_markup=InlineKeyboardMarkup(teclado))

# ---- Buscar ofertas (con paginación) ----
async def buscar_ofertas(update: Update, context: CallbackContext):
    logger.info("🔍 Buscar ofertas iniciado")
    if not ofertas_db:
        await update.message.reply_text("⚠️ No se puede acceder a la base de datos.")
        return
    try:
        todas = ofertas_db.get_all_records()
        total = len(todas)
        if total == 0:
            await update.message.reply_text("😕 Aún no hay ofertas publicadas.")
            return
        inicio = context.user_data.get("oferta_index", 0)
        fin = inicio + 3
        mostrar = todas[max(0, total - fin):total - inicio]
        for oferta in reversed(mostrar):
            msg = (
                f"💼 *Puesto:* {oferta['Puesto']}\n"
                f"🏢 *Empresa:* {oferta['Empresa']}\n"
                f"💰 *Salario:* {oferta['Salario']}\n"
                f"📝 *Descripción:* {oferta['Descripción']}\n"
                f"📱 *Contacto:* {oferta['Contacto']}\n"
                f"📅 *Fecha:* {oferta['Fecha']}"
            )
            await update.message.reply_markdown(msg)
        if fin < total:
            await update.message.reply_text("¿Ver más ofertas?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas")]
            ]))
            context.user_data["oferta_index"] = fin
        else:
            await update.message.reply_text("✅ Ya has visto todas las ofertas.")
            context.user_data["oferta_index"] = 0
    except Exception as e:
        logger.error("❌ Error buscando ofertas: %s", str(e))
        await update.message.reply_text("❌ Error buscando ofertas.")

async def ver_mas_ofertas(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await buscar_ofertas(query, context)

# ---- Flujo publicar oferta ----
async def iniciar_oferta(update: Update, context: CallbackContext):
    if update.callback_query:
        await update.callback_query.answer()
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
    success = nueva_oferta(user.id, context.user_data)
    if success:
        await update.message.reply_text("✅ ¡Oferta publicada con éxito!")
    else:
        await update.message.reply_text("❌ Error al guardar la oferta.")
    return ConversationHandler.END

async def cancelar_oferta(update: Update, context: CallbackContext):
    await update.message.reply_text("❌ Publicación cancelada.")
    return ConversationHandler.END

# ---- Flujo: Registro de candidato (busco empleo) ----
async def iniciar_registro_trabajador(update: Update, context: CallbackContext):
    if update.callback_query:
        await update.callback_query.answer()
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
    datos = context.user_data
    if not sheet:
        await update.message.reply_text("⚠️ No se puede acceder a la base de datos.")
        return ConversationHandler.END
    try:
        candidatos_db = sheet.worksheet("Candidatos")
        candidatos_db.append_row([
            datos["nombre"],
            datos["trabajo"],
            datos["escolaridad"],
            datos["contacto"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
        await update.message.reply_text("✅ ¡Tu perfil fue registrado correctamente!")
        limpiar_ofertas_y_candidatos()
    except Exception as e:
        logger.error("❌ Error registrando candidato: %s", str(e))
        await update.message.reply_text("❌ Ocurrió un error al guardar tu información.")
    return ConversationHandler.END

async def cancelar_registro(update: Update, context: CallbackContext):
    await update.message.reply_text("❌ Registro cancelado.")
    return ConversationHandler.END

# ---- Buscar candidatos (con paginación) ----
async def buscar_candidatos(update: Update, context: CallbackContext):
    logger.info("🔎 Buscar candidatos iniciado")
    if not sheet:
        await update.message.reply_text("⚠️ No se puede acceder a la base de datos.")
        return
    try:
        candidatos_db = sheet.worksheet("Candidatos")
        todos = candidatos_db.get_all_records()
        total = len(todos)

        if total == 0:
            await update.message.reply_text("😕 No hay personas registradas buscando empleo.")
            return

        inicio = context.user_data.get("candidato_index", 0)
        fin = inicio + 3
        mostrar = todos[max(0, total - fin):total - inicio]

        for candidato in reversed(mostrar):
            msg = (
                f"👤 *Nombre:* {candidato['Nombre']}\n"
                f"🛠️ *Trabajo buscado:* {candidato['Trabajo']}\n"
                f"🎓 *Escolaridad:* {candidato['Escolaridad']}\n"
                f"📱 *Contacto:* {candidato['Contacto']}\n"
                f"📅 *Fecha:* {candidato['Fecha']}"
            )
            await update.message.reply_markdown(msg)

        if fin < total:
            context.user_data["candidato_index"] = fin
            await update.message.reply_text(
                "¿Ver más candidatos?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➡️ Ver más", callback_data="ver_mas_candidatos")]
                ])
            )
        else:
            await update.message.reply_text("✅ Ya has visto todos los perfiles.")
            context.user_data["candidato_index"] = 0

    except Exception as e:
        logger.error("❌ Error al buscar candidatos: %s", str(e))
        await update.message.reply_text("❌ Error al consultar la base de datos.")

async def ver_mas_candidatos(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await buscar_candidatos(query, context)

# ---- Botones del menú interactivo ----
async def manejar_botones(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == "buscar":
        context.user_data["oferta_index"] = 0
        await buscar_ofertas(query, context)
    elif query.data == "ofertar":
        await iniciar_oferta(query, context)
    elif query.data == "registro":
        await iniciar_registro_trabajador(query, context)
    elif query.data == "buscar_candidatos":
        context.user_data["candidato_index"] = 0
        await buscar_candidatos(query, context)
    elif query.data == "ayuda":
        await ayuda(update, context)

# ---- Función principal ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    async def establecer_comandos(app):
        await app.bot.set_my_commands([
            ("start", "Iniciar el bot"),
            ("menu", "Ver menú interactivo"),
            ("ofertar", "Publicar oferta de empleo"),
            ("buscar", "Buscar ofertas"),
            ("buscoempleo", "Registrarte como buscador de empleo"),
            ("cancelar", "Cancelar una acción"),
            ("help", "Ver ayuda")
        ])
        logger.info("✅ Comandos establecidos para el menú izquierdo")
    
    app.post_init = establecer_comandos
    
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
        fallbacks=[CommandHandler("cancelar", cancelar_oferta)],
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
        fallbacks=[CommandHandler("cancelar", cancelar_registro)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("buscar", buscar_ofertas))
    app.add_handler(CallbackQueryHandler(ver_mas_ofertas, pattern="^ver_mas$"))
    app.add_handler(CallbackQueryHandler(ver_mas_candidatos, pattern="^ver_mas_candidatos$"))
    app.add_handler(ofertar_handler)
    app.add_handler(registro_handler)
    app.add_handler(CallbackQueryHandler(manejar_botones))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_spam))

    limpiar_ofertas_y_candidatos()

    # Inicia el bot
    logger.info("🤖 Bot iniciado y escuchando...")
    app.run_polling()

if __name__ == '__main__':
    main()
