# main.py
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# -----------------------------
# CARGAR VARIABLES DE ENTORNO
# -----------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))  # asegúrate que en Koyeb está como número

# -----------------------------
# CONFIGURACIÓN DE BOT
# -----------------------------
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
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

# -----------------------------
# COMANDO /ping
# -----------------------------
@bot.tree.command(name="ping", description="Responde con Pong!", guild=discord.Object(id=int(os.getenv("GUILD_ID"))))
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)

# -----------------------------
# COMANDO /eventos
# -----------------------------
@bot.tree.command(name="eventos", description="Crear un evento paso a paso", guild=discord.Object(id=int(os.getenv("GUILD_ID"))))
async def eventos(interaction: discord.Interaction):
    await interaction.response.send_message("📅 Aquí iniciaremos la creación de un evento paso a paso.", ephemeral=True)

# -----------------------------
# KEEP ALIVE (para Koyeb)
# -----------------------------
from keep_alive import keep_alive
keep_alive()

# -----------------------------
# INICIAR BOT
# -----------------------------
bot.run(TOKEN)


