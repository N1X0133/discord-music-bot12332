import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
import json
import os
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Настройки для YouTube
ytdl_format_options = {
    'format': 'bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.uploader = data.get('uploader')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            if 'entries' in data:
                data = data['entries'][0]
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except Exception as e:
            logging.error(f"Ошибка загрузки: {e}")
            return None

# Настройка бота (как в вашем примере)
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
    
    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Слэш-команды синхронизированы")

bot = MusicBot()

# Очередь песен (как база данных)
queues = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

# ==================== СОБЫТИЯ ====================

@bot.event
async def on_ready():
    print(f'\n{"="*50}')
    print(f'✅ Музыкальный бот {bot.user} запущен!')
    print(f'{"="*50}')
    print(f'📋 На серверах: {len(bot.guilds)}')
    print(f'{"="*50}\n')
    
    await bot.change_presence(activity=discord.Game(name="/help | /play"))

# ==================== СЛЭШ-КОМАНДЫ (как в магазине) ====================

@bot.tree.command(name="play", description="🎵 Воспроизвести музыку с YouTube")
async def slash_play(interaction: discord.Interaction, запрос: str):
    """Воспроизвести музыку по ссылке или названию"""
    
    # Проверка на голосовой канал
    if not interaction.user.voice:
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Вы должны находиться в голосовом канале!",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Получаем или создаем голосовой клиент
    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    
    if voice_client and voice_client.is_connected():
        if voice_client.channel != channel:
            await voice_client.move_to(channel)
    else:
        voice_client = await channel.connect()
    
    embed = discord.Embed(
        title="🔍 Поиск...",
        description=f"Ищем: **{запрос}**",
        color=0x3498db
    )
    await interaction.followup.send(embed=embed)
    
    try:
        player = await YTDLSource.from_url(запрос, loop=bot.loop, stream=True)
        
        if player is None:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Не удалось найти трек",
                color=0xe74c3c
            )
            await interaction.followup.send(embed=embed)
            return
        
        if voice_client.is_playing():
            queue = get_queue(interaction.guild_id)
            queue.append(player)
            
            embed = discord.Embed(
                title="✅ Добавлено в очередь",
                description=f"**{player.title}**",
                color=0x2ecc71
            )
            embed.add_field(name="Позиция в очереди", value=f"```{len(queue)}```", inline=True)
            if player.duration:
                minutes = player.duration // 60
                seconds = player.duration % 60
                embed.add_field(name="Длительность", value=f"```{minutes}:{seconds:02d}```", inline=True)
            
            await interaction.followup.send(embed=embed)
        else:
            voice_client.play(player, after=lambda e: after_play(interaction.guild_id))
            
            embed = discord.Embed(
                title="🎵 Сейчас играет",
                description=f"**{player.title}**",
                color=0x9b59b6,
                timestamp=datetime.now()
            )
            
            if player.duration:
                minutes = player.duration // 60
                seconds = player.duration % 60
                embed.add_field(name="Длительность", value=f"```{minutes}:{seconds:02d}```", inline=True)
            
            if player.uploader:
                embed.add_field(name="Автор", value=f"```{player.uploader}```", inline=True)
            
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
            
            embed.set_footer(text=f"Запросил: {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            
            await interaction.followup.send(embed=embed)
            
    except Exception as e:
        embed = discord.Embed(
            title="❌ Ошибка",
            description=f"Произошла ошибка: {str(e)[:100]}",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)

def after_play(guild_id):
    """Что делать после окончания трека"""
    queue = get_queue(guild_id)
    if queue:
        next_player = queue.pop(0)
        for voice_client in bot.voice_clients:
            if voice_client.guild.id == guild_id:
                voice_client.play(next_player, after=lambda e: after_play(guild_id))
                break

@bot.tree.command(name="pause", description="⏸️ Поставить на паузу")
async def slash_pause(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    
    if not voice_client or not voice_client.is_playing():
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Сейчас ничего не играет",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    voice_client.pause()
    
    embed = discord.Embed(
        title="⏸️ Пауза",
        description="Музыка приостановлена",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="resume", description="▶️ Продолжить воспроизведение")
async def slash_resume(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    
    if not voice_client or not voice_client.is_paused():
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Нет трека на паузе",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    voice_client.resume()
    
    embed = discord.Embed(
        title="▶️ Продолжаем",
        description="Воспроизведение возобновлено",
        color=0x2ecc71
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="skip", description="⏭️ Пропустить текущий трек")
async def slash_skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    
    if not voice_client or not voice_client.is_playing():
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Сейчас ничего не играет",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    voice_client.stop()
    
    embed = discord.Embed(
        title="⏭️ Трек пропущен",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stop", description="⏹️ Остановить музыку и отключиться")
async def slash_stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Я не в голосовом канале",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Очищаем очередь
    if interaction.guild_id in queues:
        queues[interaction.guild_id] = []
    
    await voice_client.disconnect()
    
    embed = discord.Embed(
        title="👋 Отключился",
        description="Воспроизведение остановлено",
        color=0xe74c3c
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="queue", description="📋 Показать очередь песен")
async def slash_queue(interaction: discord.Interaction):
    queue = get_queue(interaction.guild_id)
    voice_client = interaction.guild.voice_client
    
    embed = discord.Embed(
        title="📋 Очередь воспроизведения",
        color=0x9b59b6,
        timestamp=datetime.now()
    )
    
    # Текущий трек
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'title'):
        current = voice_client.source
        current_text = f"**{current.title}**"
        if hasattr(current, 'duration') and current.duration:
            minutes = current.duration // 60
            seconds = current.duration % 60
            current_text += f" ({minutes}:{seconds:02d})"
        embed.add_field(name="🎵 Сейчас играет", value=current_text, inline=False)
    else:
        embed.add_field(name="🎵 Сейчас играет", value="```Ничего```", inline=False)
    
    # Очередь
    if queue:
        queue_text = ""
        total_duration = 0
        
        for i, track in enumerate(queue[:10], 1):
            track_text = f"{i}. **{track.title}**"
            if track.duration:
                minutes = track.duration // 60
                seconds = track.duration % 60
                track_text += f" ({minutes}:{seconds:02d})"
                total_duration += track.duration
            queue_text += track_text + "\n"
        
        if len(queue) > 10:
            queue_text += f"... и еще {len(queue) - 10} треков"
        
        embed.add_field(name="📌 В очереди:", value=queue_text, inline=False)
        
        if total_duration > 0:
            hours = total_duration // 3600
            minutes = (total_duration % 3600) // 60
            if hours > 0:
                embed.set_footer(text=f"Всего в очереди: {len(queue)} треков • {hours}ч {minutes}мин")
            else:
                embed.set_footer(text=f"Всего в очереди: {len(queue)} треков • {minutes}мин")
    else:
        embed.add_field(name="📌 В очереди:", value="```Пусто```", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="nowplaying", description="ℹ️ Что играет сейчас")
async def slash_nowplaying(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    
    if not voice_client or not voice_client.is_playing() or not hasattr(voice_client.source, 'title'):
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Сейчас ничего не играет",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    player = voice_client.source
    
    embed = discord.Embed(
        title="🎵 Сейчас играет",
        description=f"**{player.title}**",
        color=0x2ecc71,
        timestamp=datetime.now()
    )
    
    if player.duration:
        minutes = player.duration // 60
        seconds = player.duration % 60
        embed.add_field(name="Длительность", value=f"```{minutes}:{seconds:02d}```", inline=True)
    
    if player.uploader:
        embed.add_field(name="Автор", value=f"```{player.uploader}```", inline=True)
    
    if player.thumbnail:
        embed.set_thumbnail(url=player.thumbnail)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="volume", description="🔊 Изменить громкость (0-100)")
async def slash_volume(interaction: discord.Interaction, громкость: int):
    voice_client = interaction.guild.voice_client
    
    if not voice_client or not voice_client.source:
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Сейчас ничего не играет",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if громкость < 0 or громкость > 100:
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Громкость должна быть от 0 до 100",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    voice_client.source.volume = громкость / 100
    
    embed = discord.Embed(
        title="🔊 Громкость изменена",
        description=f"Текущая громкость: **{громкость}%**",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="🧹 Очистить очередь")
async def slash_clear(interaction: discord.Interaction):
    if interaction.guild_id in queues:
        queues[interaction.guild_id] = []
    
    embed = discord.Embed(
        title="🧹 Очередь очищена",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="📋 Список команд")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 ПОМОЩЬ ПО КОМАНДАМ",
        description="**Музыкальный бот**",
        color=0x9b59b6,
        timestamp=datetime.now()
    )
    
    commands = [
        ("`/play [запрос]`", "🎵 Воспроизвести музыку (ссылка или название)"),
        ("`/pause`", "⏸️ Поставить на паузу"),
        ("`/resume`", "▶️ Продолжить"),
        ("`/skip`", "⏭️ Пропустить трек"),
        ("`/stop`", "⏹️ Остановить и отключиться"),
        ("`/queue`", "📋 Показать очередь"),
        ("`/nowplaying`", "ℹ️ Что играет сейчас"),
        ("`/volume [0-100]`", "🔊 Изменить громкость"),
        ("`/clear`", "🧹 Очистить очередь"),
        ("`/help`", "📋 Это меню")
    ]
    
    for cmd, desc in commands:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    embed.set_footer(text="by Ilya Vetrov")
    
    await interaction.response.send_message(embed=embed)

# ==================== ПРЕФИКСНЫЕ КОМАНДЫ (как в магазине) ====================

@bot.command(name='play')
async def play_command(ctx, *, query):
    """Альтернатива /play через префикс"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_play(interaction, query)

@bot.command(name='pause')
async def pause_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_pause(interaction)

@bot.command(name='resume')
async def resume_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_resume(interaction)

@bot.command(name='skip')
async def skip_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_skip(interaction)

@bot.command(name='stop')
async def stop_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_stop(interaction)

@bot.command(name='queue')
async def queue_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_queue(interaction)

@bot.command(name='np')
async def np_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_nowplaying(interaction)

@bot.command(name='volume')
async def volume_command(ctx, volume: int):
    interaction = await commands.Context.to_interface(ctx)
    await slash_volume(interaction, volume)

@bot.command(name='clear')
async def clear_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_clear(interaction)

@bot.command(name='help')
async def help_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_help(interaction)

@bot.command(name='ping')
async def ping_command(ctx):
    """Проверить задержку бота"""
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="🏓 Понг!",
        description=f"Задержка: **{latency}ms**",
        color=0x2ecc71
    )
    await ctx.send(embed=embed)

@bot.command(name='sync')
async def sync_command(ctx):
    """Синхронизировать слэш-команды"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Только администраторы!")
        return
    
    await bot.tree.sync()
    embed = discord.Embed(
        title="✅ Команды синхронизированы",
        color=0x2ecc71
    )
    await ctx.send(embed=embed)

# ==================== ЗАПУСК (как в магазине) ====================

# Токен берется из переменных окружения (как в вашем магазине)
token = os.getenv('TOKEN')
if not token:
    print("❌ ОШИБКА: Токен не найден в переменных окружения!")
    print("📝 Добавьте TOKEN в Environment Variables на BotHost")
    exit(1)

print("🔄 Запуск музыкального бота...")
bot.run(token)
