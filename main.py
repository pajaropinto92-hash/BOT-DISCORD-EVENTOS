# main.py
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json
import uuid
from keep_alive import keep_alive  # Para Koyeb u otros hosts

# -----------------------------
# CARGAR VARIABLES DE ENTORNO
# -----------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

# -----------------------------
# CONFIGURACIÓN DEL BOT
# -----------------------------
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
# -----------------------------
# EVENTO ON_READY
# -----------------------------
@bot.event
async def on_ready():
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"📌 Slash commands sincronizados en {GUILD_ID}: {[cmd.name for cmd in synced]}")
    except Exception as e:
        print(f"❌ Error al sincronizar: {e}")

    print(f"✅ Bot conectado como {bot.user}")

    # Iniciar el loop de recordatorios solo si no está corriendo
    if not check_event_reminders.is_running():
        check_event_reminders.start()


# -----------------------------
# ARCHIVO DE EVENTOS
# -----------------------------
EVENTS_FILE = "eventos.json"

# -----------------------------
# BOTONES CON EMOJIS VÁLIDOS
# -----------------------------
BUTTONS = {
    'INF': ('🪖', discord.ButtonStyle.success),
    'OFICIAL': ('🎖️', discord.ButtonStyle.primary),
    'TANQUE': ('🛡️', discord.ButtonStyle.success),
    'RECON': ('🔭', discord.ButtonStyle.secondary),
    'COMANDANTE': ('⭐', discord.ButtonStyle.danger),
    'DECLINADO': ('❌', discord.ButtonStyle.secondary),
    'TENTATIVO': ('⚠️', discord.ButtonStyle.primary)
}

# -----------------------------
# CARGAR / GUARDAR EVENTOS
# -----------------------------
def load_events():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r") as f:
            return json.load(f)
    return []

def save_events(events):
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=4, default=str)

events = load_events()

# -----------------------------
# ESPERA POR MENSAJES
# -----------------------------
# -----------------------------
# FUNCIONES AUXILIARES
# -----------------------------
async def wait_for_number(user, dm, min_val, max_val, cancel_word="cancelar"):
    def check(m):
        return m.author == user and m.guild is None
    while True:
        msg = await bot.wait_for("message", check=check)
        if msg.content.lower() == cancel_word:
            return None
        if msg.content.isdigit() and min_val <= int(msg.content) <= max_val:
            return int(msg.content)
        await dm.send(f"Introduce un número entre {min_val} y {max_val}, o '{cancel_word}' para salir.")

async def wait_for_text(user, dm, max_length, allow_none=False, cancel_word="cancelar"):
    def check(m):
        return m.author == user and m.guild is None
    while True:
        msg = await bot.wait_for("message", check=check)
        if msg.content.lower() == cancel_word:
            return None
        if allow_none and msg.content.lower() == "none":
            return ""
        if len(msg.content) <= max_length:
            return msg.content
        await dm.send(f"Texto demasiado largo. Máximo {max_length} caracteres. Escribe '{cancel_word}' para salir.")

# -----------------------------
# CREAR EMBED DE EVENTO
# -----------------------------
async def create_event_embed(event):
    embed = discord.Embed(
        title=event.get("title", "Evento sin título"),
        description=event.get("description", "Sin descripción"),
        color=discord.Color(event.get("color", 0x00ff00))
    )

    embed.add_field(name="📅 Fecha de inicio", value=event.get("start", "No especificado"), inline=True)
    embed.add_field(name="⏱️ Duración/Fin", value=event.get("end", "No especificado"), inline=True)

    guild = bot.get_guild(GUILD_ID)
    for key, (emoji, _) in BUTTONS.items():
        user_ids = event.get("participants_roles", {}).get(key, [])
        if user_ids:
            names = []
            for uid in user_ids:
                member = guild.get_member(uid) if guild else None
                names.append(member.display_name if member else f"❓({uid})")
            field_name = f"{emoji} {key} ({len(user_ids)})"  # número a la par
            text = "\n".join(f"- {n}" for n in names)
            
        else:
            field_name = f"{emoji} {key} (0)"
            text = "Nadie aún"
        embed.add_field(name=field_name, value=text, inline=False)

    # Menciones de roles
    if event.get("mention_roles"):
        mentions = " ".join(f"<@&{r}>" for r in event["mention_roles"])
        embed.add_field(name="Roles mencionados", value=mentions, inline=False)

    if event.get("image"):
        embed.set_image(url=event["image"])

    return embed



# -----------------------------
# 🔹 FUNCION DE ACTUALIZACIÓN DE EMBED Y HILO
# -----------------------------
async def update_event_embed_and_thread(event):
    """Actualiza el embed del evento y el hilo si ya fue creado"""
    channel = bot.get_channel(event["channel_id"])
    if not channel:
        return

    embed = create_event_embed(event)  # Usamos la función que ya tiene todo: título, descripción, hora, duración, imagen

    mentions = []
    for role_key, (emoji, _) in BUTTONS.items():
        if role_key == "DECLINADO":
            continue
        names = event.get("participants_roles", {}).get(role_key, [])
        for name in names:
            member = discord.utils.find(lambda m: m.display_name == name, channel.guild.members)
            if member and member not in mentions:
                mentions.append(member)

    # Actualizar mensaje original
    if "message_id" in event:
        try:
            msg = await channel.fetch_message(event["message_id"])
            await msg.edit(embed=embed)
        except:
            sent_msg = await channel.send(embed=embed)
            event["message_id"] = sent_msg.id
            save_events(events)

    # Actualizar hilo si existe
    if "thread_id" in event:
        try:
            thread = await channel.fetch_message(event["thread_id"])
            await thread.channel.send(f"Nuevos inscritos: {', '.join([m.mention for m in mentions])}")
        except:
            pass

# -----------------------------
# BOTONES DE INSCRIPCIÓN
# -----------------------------
class EventButton(discord.ui.Button):
    def __init__(self, label, emoji, style, event_id, role_key):
        super().__init__(label=label, emoji=emoji, style=style)
        self.event_id = event_id
        self.role_key = role_key

async def callback(self, interaction: discord.Interaction):
    global events
    user_id = interaction.user.id
    nickname = interaction.user.display_name

    for event in events:
        if event["id"] == self.event_id:
            if "participants_roles" not in event:
                event["participants_roles"] = {key: [] for key in BUTTONS.keys()}

            # Registrar al usuario en el rol seleccionado
            if not event.get("multi_response", False):
                # Quitar de otros roles primero
                for key, lst in event["participants_roles"].items():
                    if key != self.role_key and nickname in lst:
                        lst.remove(nickname)

            if nickname not in event["participants_roles"][self.role_key]:
                event["participants_roles"][self.role_key].append(nickname)

            save_events(events)
            await update_event_embed_and_thread(event)

            await interaction.response.send_message(
                f"Te has inscrito como {self.role_key}", ephemeral=True
            )
            return



class EventActionButton(discord.ui.Button):
    def __init__(self, label, style, event_id, creator_id):
        super().__init__(label=label, style=style)
        self.event_id = event_id
        self.creator_id = creator_id

    async def callback(self, interaction: discord.Interaction):
        global events
        event = next((e for e in events if e["id"] == self.event_id), None)
        if not event:
            await interaction.response.send_message("Evento no encontrado.", ephemeral=True)
            return

        if self.label == "Eliminar evento":
            events.remove(event)
            save_events(events)
            channel = bot.get_channel(event["channel_id"])
            if channel and "message_id" in event:
                try:
                    msg = await channel.fetch_message(event["message_id"])
                    await msg.delete()
                except:
                    pass
            await interaction.response.send_message("Evento eliminado ✅", ephemeral=True)

        elif self.label == "Editar evento":
            await interaction.response.send_message("Te enviaré un DM para editar el evento.", ephemeral=True)
            # Aquí va tu flujo de edición existente

# -----------------------------
# CLASES DE BOTONES Y VISTA
# -----------------------------
class EventButton(discord.ui.Button):
    def __init__(self, label, emoji, style, event_id, role_key):
        super().__init__(label=label, emoji=emoji, style=style)
        self.event_id = event_id
        self.role_key = role_key

    async def callback(self, interaction: discord.Interaction):
        global events
        user_id = interaction.user.id
        channel = interaction.channel

        for event in events:
            if event["id"] == self.event_id:
                if "participants_roles" not in event:
                    event["participants_roles"] = {key: [] for key in BUTTONS.keys()}

                # Agregar usuario al rol seleccionado
                if user_id not in event["participants_roles"][self.role_key]:
                    event["participants_roles"][self.role_key].append(user_id)

                # Quitar de otros roles si no es multi-respuesta
                if not event.get("multi_response", False):
                    for key, lst in event["participants_roles"].items():
                        if key != self.role_key and user_id in lst:
                            lst.remove(user_id)

                save_events(events)

                # Crear embed actualizado
                embed = await create_event_embed(event)

                # Actualizar mensaje original
                if channel and "message_id" in event:
                    try:
                        msg = await channel.fetch_message(event["message_id"])
                        await msg.edit(embed=embed, view=EventView(self.event_id, event["creator_id"]))
                    except:
                        pass

                # Actualizar hilo si existe
                if "thread_id" in event:
                    thread = channel.guild.get_channel(event["thread_id"])
                    if thread:
                        mentions = []
                        for role_key, user_ids in event.get("participants_roles", {}).items():  
                            if role_key == "DECLINADO":
                                continue
                            for uid in user_ids:    
                                member = guild.get_member(uid)
                                if member and member not in mentions:
                                    mentions.append(member.mention)
                        if mentions:
                            await thread.send(f"👥 Nuevos inscritos: {', '.join(mentions)}")

                await interaction.response.send_message(
                    f"✅ Te has inscrito como **{self.role_key}**",
                    ephemeral=True
                )
                return

        # Acciones de botón especiales
        if self.label == "Eliminar evento":
            events.remove(event)
            save_events(events)
            if channel and "message_id" in event:
                try:
                    msg = await channel.fetch_message(event["message_id"])
                    await msg.delete()
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    await interaction.response.send_message("No tengo permisos para eliminar el mensaje.", ephemeral=True)
                    return
                except Exception as e:
                    await interaction.response.send_message(f"Ocurrió un error: {e}", ephemeral=True)
                    return
            await interaction.response.send_message("Evento eliminado ✅", ephemeral=True)

        elif self.label == "Editar evento":
            await interaction.response.send_message("Te enviaré un DM para editar el evento paso a paso.", ephemeral=True)
            user = interaction.user
            dm = await user.create_dm()

            # Valores actuales
            current_title = event["title"]
            current_description = event["description"]
            current_channel_id = event["channel_id"]
            current_start = event["start"]
            current_end = event.get("end")
            current_max = event.get("max_attendees")

            # 1️⃣ Título
            await dm.send(f"Título actual: **{current_title}**\nEscribe el nuevo título o 'skip' para dejarlo igual:")
            new_title = await wait_for_text(user, dm, 200, allow_none=True)
            if new_title is None:
                await dm.send("Edición cancelada.")
                return
            if new_title.lower() != "skip" and new_title != "":
                event["title"] = new_title

            # 2️⃣ Descripción
            await dm.send(f"Descripción actual: **{current_description or 'Ninguna'}**\nEscribe la nueva o 'skip':")
            new_description = await wait_for_text(user, dm, 1600, allow_none=True)
            if new_description is None:
                await dm.send("Edición cancelada.")
                return
            if new_description.lower() != "skip":
                event["description"] = new_description

            # 3️⃣ Canal
            guild = bot.get_guild(GUILD_ID)
            text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
            await dm.send(f"Canal actual: <#{current_channel_id}>\nSelecciona nuevo canal por número o 'skip':\n" +
                          "\n".join(f"{i+1}. {c.name}" for i, c in enumerate(text_channels)))
            chan_option = await wait_for_number(user, dm, 1, len(text_channels))
            if chan_option is not None:
                event["channel_id"] = text_channels[chan_option-1].id

            # 4️⃣ Fecha inicio
            await dm.send(f"Fecha y hora actual: **{current_start}**\nEscribe nueva fecha ('YYYY-MM-DD HH:MM') o 'skip':")
            while True:
                msg_time = await bot.wait_for("message", check=lambda m: m.author == user and m.guild is None)
                if msg_time.content.lower() == "cancelar":
                    await dm.send("Edición cancelada.")
                    return
                if msg_time.content.lower() == "skip":
                    break
                try:
                    start_dt = datetime.strptime(msg_time.content, "%Y-%m-%d %H:%M")
                    event["start"] = start_dt.strftime("%Y-%m-%d %H:%M")
                    break
                except:
                    await dm.send("Formato inválido. Intenta de nuevo o 'skip'.")

            # 5️⃣ Duración
            await dm.send(f"Duración actual: **{current_end or 'Ninguna'}**\nEscribe nueva duración o 'skip':")
            new_duration = await wait_for_text(user, dm, 100, allow_none=True)
            if new_duration.lower() != "skip":
                event["end"] = new_duration

            # 6️⃣ Máximo asistentes
            await dm.send(f"Número máximo de asistentes actual: **{current_max or 'Ninguno'}**\nEscribe nuevo número (1-250) o 'skip':")
            while True:
                msg = await bot.wait_for("message", check=lambda m: m.author == user and m.guild is None)
                if msg.content.lower() == "cancelar":
                    await dm.send("Edición cancelada.")
                    return
                if msg.content.lower() == "skip":
                    break
                if msg.content.isdigit() and 1 <= int(msg.content) <= 250:
                    event["max_attendees"] = int(msg.content)
                    break
                await dm.send("Número inválido. Intenta de nuevo o 'skip'.")

            save_events(events)

            # Actualizar embed original
            channel = bot.get_channel(event["channel_id"])
            if channel and "message_id" in event:
                try:
                    msg = await channel.fetch_message(event["message_id"])
                    embed = await create_event_embed(event)
                    await msg.edit(embed=embed, view=EventView(event["id"], event["creator_id"]))
                except:
                    await channel.send("No se pudo actualizar el evento, enviando uno nuevo...",
                                       embed=await create_event_embed(event),
                                       view=EventView(event["id"], event["creator_id"]))

            await dm.send("Evento editado correctamente ✅")


class EventView(discord.ui.View):
    def __init__(self, event_id, creator_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.creator_id = creator_id
        for role_key, (emoji, style) in BUTTONS.items():
            self.add_item(EventButton(label=role_key, emoji=emoji, style=style, event_id=event_id, role_key=role_key))
        self.add_item(EventButton("Editar evento", discord.ButtonStyle.primary, event_id, creator_id))
        self.add_item(EventButton("Eliminar evento", discord.ButtonStyle.danger, event_id, creator_id))



# -----------------------------
# VISTA DEL EVENTO
# -----------------------------
class EventView(discord.ui.View):
    def __init__(self, event_id, creator_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.creator_id = creator_id
        for role_key, (emoji, style) in BUTTONS.items():
            self.add_item(EventButton(label=role_key, emoji=emoji, style=style, event_id=event_id, role_key=role_key))
        self.add_item(EventActionButton("Editar evento", discord.ButtonStyle.primary, event_id, creator_id))
        self.add_item(EventActionButton("Eliminar evento", discord.ButtonStyle.danger, event_id, creator_id))

# -----------------------------
# LOOP DE RECORDATORIOS
# -----------------------------
@tasks.loop(seconds=60)
async def check_events():
    global events
    now = datetime.now()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    for event in events:
        start_dt = datetime.strptime(event["start"], "%Y-%m-%d %H:%M")

        # Recordatorio 15 minutos antes
        if not event.get("reminder_sent") and start_dt - timedelta(minutes=15) <= now < start_dt:
            # Preparar menciones de todos los participantes (excepto DECLINADO)
            mentions = []
            for role_key, user_ids in event.get("participants_roles", {}).items():
                if role_key == "DECLINADO":
                    continue
                for user_id in user_ids:
                    member = guild.get_member(user_id)
                    if member and member not in mentions:
                        mentions.append(member.mention)

            channel = bot.get_channel(event["channel_id"])
            if channel:
                # Enviar recordatorio en el canal
                message = await channel.send(
                    f"⏰ Recordatorio! 15 minutos para el inicio del evento.\n"
                    f"Participantes: {', '.join(mentions) if mentions else 'Nadie registrado aún.'}"
                )

                # Crear hilo a partir del mensaje
                thread_name = f"Hilo de {event.get('name', 'Evento')}"
                thread = await message.create_thread(name=thread_name, auto_archive_duration=60)

                # Menciones de los confirmados
                confirmed_ids = event.get("participants_roles", {}).get("✅ Confirmado", [])
                confirmed_members = [guild.get_member(uid) for uid in confirmed_ids]
                confirmed_mentions = [member.mention for member in confirmed_members if member]

                # Enviar mensaje de bienvenida en el hilo
                welcome_msg = f"👋 Bienvenidos al evento **{event.get('name', 'Evento')}**\nEstá por iniciar, prepárense!"
                if confirmed_mentions:
                    welcome_msg += f"\n\n{' '.join(confirmed_mentions)}"

                await thread.send(welcome_msg)

            # Marcar como recordatorio enviado y guardar cambios
            event["reminder_sent"] = True
            save_events(events)

        # Si quieres hacer algo justo al inicio del evento, puedes usar esta sección:
        # if not event.get("channel_created") and now >= start_dt:
        #     event["channel_created"] = True
        #     save_events(events)
# -----------------------------
# 🔹 FUNCION DE ACTUALIZACIÓN DE EMBED ORIGINAL
# -----------------------------
async def update_event_embed(event):
    """Actualiza solo el embed original del evento con los participantes"""
    channel = bot.get_channel(event["channel_id"])
    if not channel or "message_id" not in event:
        return

    embed = create_event_embed(event)  # Título, descripción, hora, duración, imagen
    try:
        msg = await channel.fetch_message(event["message_id"])
        await msg.edit(embed=embed, view=EventView(event["id"], event["creator_id"]))
    except:
        # Si no se encuentra el mensaje, lo enviamos de nuevo
        sent_msg = await channel.send(embed=embed, view=EventView(event["id"], event["creator_id"]))
        event["message_id"] = sent_msg.id
        save_events(events)


# -----------------------------
# 🔹 FUNCION DE RECORDATORIO
# -----------------------------
async def send_event_reminder(event):
    """Envía un recordatorio 15 min antes, crea hilo y menciona participantes correctamente"""
    channel = bot.get_channel(event["channel_id"])
    if not channel:
        return

    guild = channel.guild

    # Crear embed del recordatorio
    reminder_embed = discord.Embed(
        title=f"⏰ Recordatorio: {event['title']}",
        description=f"El evento empieza en 15 minutos en <#{channel.id}>!",
        color=discord.Color.green()
    )

    # Preparar menciones y agregar campos por rol
    mentions = []
    for role_key, names in event.get("participants_roles", {}).items():
        if role_key == "DECLINADO":
            continue
        if names:
            reminder_embed.add_field(
                name=f"{BUTTONS[role_key][0]} {role_key} ({len(names)})",
                value="\n".join(f"- {n}" for n in names),
                inline=False
            )
        for name in names:
            member = discord.utils.find(lambda m: m.display_name == name, guild.members)
            if member and member not in mentions:
                mentions.append(member)

    # Enviar embed en el canal principal
    await channel.send(
    embed=reminder_embed,
    content=f"Participantes confirmados: {', '.join(mentions)}" if mentions else None)

    # Crear hilo si no existe
    thread = None
    if "thread_id" not in event:
        thread = await channel.create_thread(
            name=f"Hilo - {event['title']}",
            type=discord.ChannelType.public_thread
        )
        event["thread_id"] = thread.id
        save_events(events)
    else:
        thread = bot.get_channel(event["thread_id"])

    # Mensaje dentro del hilo
    if thread:
        if mentions:
            await thread.send(f"¡Bienvenidos al evento! {' '.join([m.mention for m in mentions])}")
        else:
            await thread.send("¡Bienvenidos al evento! No hay participantes aún.")



    # Enviar DM a cada participante
    for member in mentions:
        try:
            await member.send(f"⏰ Tu evento **{event['title']}** empieza en 15 minutos en <#{channel.id}>!")
        except:
            pass

    event["reminder_sent"] = True
    save_events(events)

# -----------------------------
# 🔹 LOOP DE RECORDATORIOS
# -----------------------------
@tasks.loop(seconds=60)
async def check_event_reminders():
    now = datetime.now()
    for event in events:
        start_dt = datetime.strptime(event["start"], "%Y-%m-%d %H:%M")
        reminder_time = start_dt - timedelta(minutes=15)
        if not event.get("reminder_sent") and now >= reminder_time:
            await send_event_reminder(event)


# -----------------------------
# COMANDO /ping
# -----------------------------
@bot.tree.command(name="ping", description="Responde con Pong!", guild=discord.Object(id=GUILD_ID))
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)

# -----------------------------
# COMANDO /hola
# -----------------------------
@bot.tree.command(name="hola", description="Te saluda el bot", guild=discord.Object(id=GUILD_ID))
async def hola(interaction: discord.Interaction):
    await interaction.response.send_message("👋 Hola! ¿Cómo estás?", ephemeral=True)

# -----------------------------
# COMANDO /eventos
# -----------------------------
@bot.tree.command(
    name="eventos",
    description="Crear un evento paso a paso",
    guild=discord.Object(id=GUILD_ID)
)
async def eventos(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)  # Dice a Discord "espera"
    await interaction.followup.send("Te enviaré un DM para crear el evento paso a paso.", ephemeral=True)
    user = interaction.user
    dm = await user.create_dm()

    event = {}  # Diccionario temporal

    # -----------------------------
    # 1️⃣ Canal
    # -----------------------------
    await dm.send("¿Dónde publicar el evento?\n1️⃣ Canal actual\n2️⃣ Otro canal\nEscribe el número o 'cancelar'.")
    option = await wait_for_number(user, dm, 1, 2)
    if option is None:
        await dm.send("Creación cancelada.")
        return

    if option == 1:
        channel_id = interaction.channel_id
    else:
        guild = bot.get_guild(GUILD_ID)
        text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        await dm.send("Listado de canales:\n" + "\n".join(f"{i+1}. {c.name}" for i, c in enumerate(text_channels)))
        chan_option = await wait_for_number(user, dm, 1, len(text_channels))
        if chan_option is None:
            await dm.send("Creación cancelada.")
            return
        channel_id = text_channels[chan_option - 1].id
    event["channel_id"] = channel_id

    # -----------------------------
    # 2️⃣ Título
    # -----------------------------
    await dm.send("Ingresa el título del evento (máx 200 caracteres):")
    title = await wait_for_text(user, dm, 200)
    if title is None:
        await dm.send("Creación cancelada.")
        return
    event["title"] = title

    # -----------------------------
    # 3️⃣ Descripción
    # -----------------------------
    await dm.send("Ingresa la descripción (máx 1600 caracteres, 'None' para sin descripción):")
    description = await wait_for_text(user, dm, 1600, allow_none=True)
    if description is None:
        await dm.send("Creación cancelada.")
        return
    event["description"] = description or "Sin descripción"

    # -----------------------------
    # 4️⃣ Máximo asistentes
    # -----------------------------
    await dm.send("Número máximo de asistentes (1-250, 'None' para sin límite):")
    while True:
        msg = await bot.wait_for("message", check=lambda m: m.author == user and m.guild is None)
        if msg.content.lower() == "cancelar":
            await dm.send("Creación cancelada.")
            return
        if msg.content.lower() == "none":
            max_attendees = None
            break
        if msg.content.isdigit() and 1 <= int(msg.content) <= 250:
            max_attendees = int(msg.content)
            break
        await dm.send("Número inválido. Intenta de nuevo.")
    event["max_attendees"] = max_attendees

    # -----------------------------
    # 5️⃣ Fecha inicio
    # -----------------------------
    await dm.send("Fecha y hora de inicio ('YYYY-MM-DD HH:MM') o 'ahora':")
    while True:
        msg_time = await bot.wait_for("message", check=lambda m: m.author == user and m.guild is None)
        if msg_time.content.lower() == "cancelar":
            await dm.send("Creación cancelada.")
            return
        try:
            start_dt = datetime.now() if msg_time.content.lower() == "ahora" else datetime.strptime(msg_time.content, "%Y-%m-%d %H:%M")
            break
        except:
            await dm.send("Formato inválido. Intenta de nuevo.")
    event["start"] = start_dt.strftime("%Y-%m-%d %H:%M")

    # -----------------------------
    # 6️⃣ Duración
    # -----------------------------
    await dm.send("Duración del evento (ej. '2 horas', '1 día', '30 minutos') o 'None' si no hay duración:")
    duration = await wait_for_text(user, dm, 100, allow_none=True)
    event["end"] = duration or "No especificada"

    # -----------------------------
    # 7️⃣ OPCIONES AVANZADAS
    # -----------------------------
    guild = bot.get_guild(GUILD_ID)
    roles = [r for r in guild.roles if not r.is_default() and not r.managed]

    while True:
        await dm.send(
            "Opciones avanzadas:\n"
            "1️⃣ Mencionar roles al publicar\n"
            "2️⃣ Añadir imagen al embed\n"
            "3️⃣ Cambiar color del evento\n"
            "4️⃣ Restringir registro a ciertos roles\n"
            "5️⃣ Permitir múltiples respuestas por usuario\n"
            "6️⃣ Asignar un rol a los asistentes\n"
            "7️⃣ Configurar cierre de inscripciones\n"
            "8️⃣ Finalizar creación del evento\n"
            "Escribe el número de la opción que quieres configurar, o '8' para finalizar."
        )
        option = await wait_for_number(user, dm, 1, 8)
        if option is None:
            await dm.send("Creación cancelada.")
            return

        # -----------------------------
        # 1️⃣ Mencionar roles
        # -----------------------------
        if option == 1:
            if not roles:
                await dm.send("No hay roles disponibles para mencionar.")
                continue
            roles_text = "\n".join(f"{i+1}. {r.name}" for i, r in enumerate(roles))
            await dm.send("Selecciona los roles a mencionar escribiendo sus números separados por comas, o 'none':\n" + roles_text)
            while True:
                response = await wait_for_text(user, dm, 200)
                if response.lower() == "none":
                    event["mention_roles"] = []
                    break
                try:
                    indices = [int(x.strip()) - 1 for x in response.split(",")]
                    selected_roles = [roles[i].id for i in indices if 0 <= i < len(roles)]
                    if selected_roles:
                        event["mention_roles"] = selected_roles
                        break
                    else:
                        await dm.send("Ningún rol válido seleccionado. Intenta de nuevo o 'none'.")
                except:
                    await dm.send("Entrada inválida. Escribe los números separados por comas o 'none'.")

        # -----------------------------
        # 2️⃣ Añadir imagen
        # -----------------------------
        elif option == 2:
            await dm.send("Envía la imagen directamente al chat o un URL de imagen, o escribe 'none' para omitir:")

            def check_img(m):
                return m.author == user and m.guild is None and (m.attachments or m.content)

            while True:
                msg_img = await bot.wait_for("message", check=check_img)
                if msg_img.content.lower() == "cancelar":
                    await dm.send("Creación cancelada.")
                    return
                if msg_img.content.lower() == "none":
                    break

                # Archivo
                if msg_img.attachments:
                    attachment = msg_img.attachments[0]
                    if attachment.content_type.startswith("image/"):
                        event["image"] = attachment.url
                        await dm.send("Imagen añadida correctamente ✅")
                        break
                    else:
                        await dm.send("El archivo no es una imagen válida. Intenta otra vez.")
                        continue

                # URL
                elif msg_img.content.startswith("http"):
                    event["image"] = msg_img.content
                    await dm.send("Imagen añadida correctamente ✅")
                    break
                else:
                    await dm.send("Debes enviar un URL válido o subir una imagen directamente.")

        # -----------------------------
        # 3️⃣ Color
        # -----------------------------
        elif option == 3:
            await dm.send("Escribe el color en hexadecimal (ej. FF0000) o 'skip' para dejarlo verde:")
            color_hex = await wait_for_text(user, dm, 7, allow_none=True)
            if color_hex.lower() != "skip":
                try:
                    color_str = color_hex.replace("#", "")
                    event["color"] = int(color_str, 16)
                except ValueError:
                    await dm.send("Color inválido, se usará verde por defecto.")

        # -----------------------------
        # 4️⃣ Restringir registro
        # -----------------------------
        elif option == 4:
            if not roles:
                await dm.send("No hay roles disponibles.")
                continue
            roles_text = "\n".join(f"{i+1}. {r.name}" for i, r in enumerate(roles))
            await dm.send("Selecciona los roles permitidos escribiendo sus números separados por comas, o 'none':\n" + roles_text)
            while True:
                response = await wait_for_text(user, dm, 200)
                if response.lower() == "none":
                    event["allowed_roles"] = []
                    break
                try:
                    indices = [int(x.strip()) - 1 for x in response.split(",")]
                    allowed_roles = [roles[i].id for i in indices if 0 <= i < len(roles)]
                    if allowed_roles:
                        event["allowed_roles"] = allowed_roles
                        break
                    else:
                        await dm.send("Ningún rol válido. Intenta de nuevo o escribe 'none'.")
                except:
                    await dm.send("Entrada inválida. Intenta de nuevo.")

        # -----------------------------
        # 5️⃣ Multi-respuesta
        # -----------------------------
        elif option == 5:
            await dm.send("Permitir que un usuario elija múltiples roles? (si/no)")
            multi = await wait_for_text(user, dm, 3)
            event["multi_response"] = True if multi.lower() == "si" else False

        # -----------------------------
        # 6️⃣ Asignar rol automáticamente
        # -----------------------------
        elif option == 6:
            if not roles:
                await dm.send("No hay roles disponibles.")
                continue
            roles_text = "\n".join(f"{i+1}. {r.name}" for i, r in enumerate(roles))
            await dm.send("Selecciona el rol que se asignará automáticamente a los asistentes o 'none':\n" + roles_text)
            while True:
                response = await wait_for_text(user, dm, 100)
                if response.lower() == "none":
                    event["assign_role"] = None
                    break
                try:
                    index = int(response.strip()) - 1
                    if 0 <= index < len(roles):
                        event["assign_role"] = roles[index].id
                        break
                    else:
                        await dm.send("Número inválido. Intenta de nuevo o 'none'.")
                except:
                    await dm.send("Entrada inválida. Intenta de nuevo o 'none'.")
        elif option == 7:  # Cierre de inscripciones
            await dm.send("Escribe cuándo cerrar las inscripciones ('10 minutos', '1 hora', 'none'):")
            close_time = await wait_for_text(user, dm, 50, allow_none=True)
            if close_time.lower() != "none":
                event["registration_close"] = close_time
        elif option == 8:  # Finalizar
            break

    # -----------------------------
    # Guardar evento
    # -----------------------------
    event_id = str(uuid.uuid4())
    event["id"] = event_id
    event["creator_id"] = user.id
    event["participants_roles"] = {key: [] for key in BUTTONS.keys()}
    event["registration_open"] = True
    event["reminder_sent"] = False
    event["channel_created"] = False

    events.append(event)
    save_events(events)

    # -----------------------------
    # Enviar embed con roles mencionados
    # -----------------------------
    channel = bot.get_channel(event["channel_id"])
    if channel:
        embed = await create_event_embed(event)  # ✅
        sent_message = await channel.send(embed=embed, view=EventView(event_id, user.id))
        event["message_id"] = sent_message.id
        save_events(events)
        await dm.send(f"Evento creado correctamente en <#{channel.id}>")
    else:
        await dm.send("No se pudo enviar el evento al canal, pero se guardó en la base de datos.")

# -----------------------------
# COMANDO /proximos_eventos_visual
# -----------------------------
@bot.tree.command(name="proximos_eventos_visual", description="Muestra los próximos eventos tipo calendario con emojis", guild=discord.Object(id=GUILD_ID))
async def proximos_eventos_visual(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    global events
    now = datetime.now()

    # Filtrar eventos futuros
    upcoming = [e for e in events if datetime.strptime(e["start"], "%Y-%m-%d %H:%M") >= now]

    if not upcoming:
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Ordenar por fecha
    upcoming.sort(key=lambda e: datetime.strptime(e["start"], "%Y-%m-%d %H:%M"))

    # Agrupar por día
    events_by_day = {}
    for e in upcoming:
        start_dt = datetime.strptime(e["start"], "%Y-%m-%d %H:%M")
        day_str = start_dt.strftime("%A, %d %B %Y")  # Ej. Lunes, 15 Septiembre 2025
        if day_str not in events_by_day:
            events_by_day[day_str] = []
        events_by_day[day_str].append(e)

    # Crear embed principal
    embed = discord.Embed(
        title="📅 Próximos eventos",
        description="Eventos próximos organizados por día 🌟",
        color=discord.Color.green()
    )

    for day_index, (day, day_events) in enumerate(events_by_day.items()):
        value_text = ""
        for e in day_events:
            start_dt = datetime.strptime(e["start"], "%Y-%m-%d %H:%M")
            time_str = start_dt.strftime("%H:%M")
            
            # Emojis según proximidad
            delta = start_dt - now
            if delta.total_seconds() < 3600:  # Menos de 1h
                emoji = "🔥"
            elif delta.total_seconds() < 86400:  # Menos de 24h
                emoji = "⏰"
            else:
                emoji = "📌"

            # Añadir detalles del evento
            value_text += f"{emoji} {time_str} - **{e['title']}** en <#{e['channel_id']}>\n"

        # Separador de semanas cada 7 días
        week_emoji = "🗓️" if day_index % 7 == 0 else ""
        embed.add_field(name=f"{week_emoji} {day}", value=value_text, inline=False)

    await interaction.response.send_message(embed=embed)


# -----------------------------
# KEEP ALIVE PARA KOYEB
# -----------------------------
from keep_alive import keep_alive
keep_alive()

# -----------------------------
# INICIAR BOT
# -----------------------------
bot.run(TOKEN)
