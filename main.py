import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import logging
import subprocess
import sys
from datetime import datetime

# Отключаем SSL
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# Обновляем yt-dlp до стабильной версии
def setup_ytdlp():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp==2024.12.23"])
        print("✅ yt-dlp 2024.12.23 установлен")
    except:
        print("⚠️ Не удалось установить yt-dlp")

setup_ytdlp()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Настройки для YouTube и SoundCloud
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'geo_bypass': True,
    'geo_bypass_country': 'US',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
    }
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Неизвестно')
        self.url = data.get('webpage_url', data.get('url', ''))
        self.duration = data.get('duration', 0)
        self.uploader = data.get('uploader', data.get('channel', 'Неизвестно'))
        self.thumbnail = data.get('thumbnail', '')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        
        try:
            # Определяем тип запроса
            search_query = url
            if not url.startswith('http'):
                search_query = f"ytsearch:{url}"
            
            print(f"🔍 Ищу: {search_query[:50]}...")
            
            # Извлекаем информацию
            with yt_dlp.YoutubeDL(ytdl_format_options) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
            
            if not data:
                print("❌ Данные не получены")
                return None
            
            # Обрабатываем результаты поиска
            if 'entries' in data and data['entries']:
                data = data['entries'][0]
            
            if not data or 'url' not in data:
                print("❌ Нет ссылки на аудио")
                return None
            
            print(f"✅ Найдено: {data.get('title', 'Неизвестно')}")
            return cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data)
            
        except Exception as e:
            print(f"❌ Ошибка: {str(e)[:200]}")
            return None

# Настройка бота
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None)
    
    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Слэш-команды синхронизированы")

bot = MusicBot()

# Очередь песен
queues = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

@bot.event
async def on_ready():
    print(f'\n{"="*50}')
    print(f'✅ Музыкальный бот {bot.user} запущен!')
    print(f'📋 На серверах: {len(bot.guilds)}')
    print(f'🎵 Поддержка: YouTube, SoundCloud')
    print(f'{"="*50}\n')
    await bot.change_presence(activity=discord.Game(name="/help | /play"))

# ==================== ОСНОВНАЯ КОМАНДА PLAY ====================

@bot.tree.command(name="play", description="🎵 Воспроизвести музыку")
async def slash_play(interaction: discord.Interaction, запрос: str):
    # Проверка голосового канала
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Вы должны быть в голосовом канале!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Подключение к голосовому каналу
    try:
        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client
        
        if voice_client:
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
        else:
            voice_client = await channel.connect(timeout=30.0)
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка подключения: {str(e)[:100]}")
        return
    
    # Поиск и воспроизведение
    try:
        await interaction.followup.send(f"🔍 Ищу: **{запрос}**...")
        
        player = await YTDLSource.from_url(запрос, loop=bot.loop)
        
        if not player:
            await interaction.followup.send("❌ Не удалось найти трек. Попробуйте другую ссылку или название.")
            return
        
        if voice_client.is_playing():
            queue = get_queue(interaction.guild_id)
            queue.append(player)
            await interaction.followup.send(f"✅ Добавлено в очередь: **{player.title}** (позиция {len(queue)})")
        else:
            voice_client.play(player, after=lambda e: after_play(interaction.guild_id))
            
            embed = discord.Embed(
                title="🎵 Сейчас играет",
                description=f"**{player.title}**",
                color=0x2ecc71
            )
            if player.duration:
                minutes = player.duration // 60
                seconds = player.duration % 60
                embed.add_field(name="Длительность", value=f"{minutes}:{seconds:02d}")
            if player.uploader:
                embed.add_field(name="Автор", value=player.uploader)
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
            
            await interaction.followup.send(embed=embed)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)[:200]}")

def after_play(guild_id):
    queue = get_queue(guild_id)
    if queue:
        next_player = queue.pop(0)
        for vc in bot.voice_clients:
            if vc.guild.id == guild_id:
                vc.play(next_player, after=lambda e: after_play(guild_id))
                break

# ==================== ОСТАЛЬНЫЕ КОМАНДЫ ====================

@bot.tree.command(name="pause", description="⏸️ Пауза")
async def slash_pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Пауза")
    else:
        await interaction.response.send_message("❌ Ничего не играет", ephemeral=True)

@bot.tree.command(name="resume", description="▶️ Продолжить")
async def slash_resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Продолжаем")
    else:
        await interaction.response.send_message("❌ Нет на паузе", ephemeral=True)

@bot.tree.command(name="skip", description="⏭️ Пропустить")
async def slash_skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ Пропущено")
    else:
        await interaction.response.send_message("❌ Ничего не играет", ephemeral=True)

@bot.tree.command(name="stop", description="⏹️ Остановить")
async def slash_stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        if interaction.guild_id in queues:
            queues[interaction.guild_id] = []
        await vc.disconnect()
        await interaction.response.send_message("👋 Отключился")
    else:
        await interaction.response.send_message("❌ Я не в канале", ephemeral=True)

@bot.tree.command(name="queue", description="📋 Очередь")
async def slash_queue(interaction: discord.Interaction):
    queue = get_queue(interaction.guild_id)
    embed = discord.Embed(title="📋 Очередь", color=0x3498db)
    
    if queue:
        text = "\n".join([f"{i}. {t.title}" for i, t in enumerate(queue[:10], 1)])
        if len(queue) > 10:
            text += f"\n... и еще {len(queue)-10}"
        embed.add_field(name="В очереди:", value=text[:1024], inline=False)
    else:
        embed.add_field(name="В очереди:", value="Пусто", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="nowplaying", description="ℹ️ Сейчас играет")
async def slash_nowplaying(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing() and hasattr(vc.source, 'title'):
        player = vc.source
        embed = discord.Embed(title="🎵 Сейчас играет", description=f"**{player.title}**", color=0x2ecc71)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("❌ Ничего не играет", ephemeral=True)

@bot.tree.command(name="np", description="ℹ️ Сейчас играет (сокращенно)")
async def slash_np(interaction: discord.Interaction):
    await slash_nowplaying(interaction)

@bot.tree.command(name="volume", description="🔊 Громкость (0-100)")
async def slash_volume(interaction: discord.Interaction, громкость: int):
    vc = interaction.guild.voice_client
    if vc and vc.source:
        if 0 <= громкость <= 100:
            vc.source.volume = громкость / 100
            await interaction.response.send_message(f"🔊 Громкость: {громкость}%")
        else:
            await interaction.response.send_message("❌ Громкость от 0 до 100", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Ничего не играет", ephemeral=True)

@bot.tree.command(name="clear", description="🧹 Очистить очередь")
async def slash_clear(interaction: discord.Interaction):
    if interaction.guild_id in queues:
        queues[interaction.guild_id] = []
    await interaction.response.send_message("🧹 Очередь очищена")

@bot.tree.command(name="help", description="📋 Помощь")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 ПОМОЩЬ",
        description="**Музыкальный бот**\nПоддержка: YouTube, SoundCloud",
        color=0x9b59b6
    )
    commands = [
        ("`/play [запрос]`", "🎵 Воспроизвести"),
        ("`/pause`", "⏸️ Пауза"),
        ("`/resume`", "▶️ Продолжить"),
        ("`/skip`", "⏭️ Пропустить"),
        ("`/stop`", "⏹️ Остановить"),
        ("`/queue`", "📋 Очередь"),
        ("`/nowplaying`", "ℹ️ Что играет"),
        ("`/volume [0-100]`", "🔊 Громкость"),
        ("`/clear`", "🧹 Очистить"),
        ("`/help`", "📋 Помощь")
    ]
    for cmd, desc in commands:
        embed.add_field(name=cmd, value=desc, inline=False)
    await interaction.response.send_message(embed=embed)

# ==================== ПРЕФИКСНЫЕ КОМАНДЫ ====================

@bot.command(name='play')
async def play_command(ctx, *, query):
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

@bot.command(name='queue', aliases=['q'])
async def queue_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_queue(interaction)

@bot.command(name='np', aliases=['now'])
async def np_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_nowplaying(interaction)

@bot.command(name='volume', aliases=['vol'])
async def volume_command(ctx, volume: int):
    interaction = await commands.Context.to_interface(ctx)
    await slash_volume(interaction, volume)

@bot.command(name='clear')
async def clear_command(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_clear(interaction)

@bot.command(name='commands', aliases=['h', 'help'])
async def commands_list(ctx):
    interaction = await commands.Context.to_interface(ctx)
    await slash_help(interaction)

@bot.command(name='ping')
async def ping_command(ctx):
    await ctx.send(f"🏓 Понг! {round(bot.latency * 1000)}ms")

@bot.command(name='test')
async def test_command(ctx, *, query):
    """Тестовая команда"""
    await ctx.send(f"🔍 Тестирую: {query}")
    
    try:
        # Проверяем версию
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        await ctx.send(f"✅ yt-dlp версия: {result.stdout}")
    except:
        await ctx.send("❌ yt-dlp не найден")
    
    # Простой тест
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            if query.startswith('http'):
                info = ydl.extract_info(query, download=False)
                if info:
                    await ctx.send(f"✅ Найдено: {info.get('title', '?')}")
            else:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                if info and info.get('entries'):
                    await ctx.send(f"✅ Найдено: {info['entries'][0].get('title', '?')}")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {str(e)[:200]}")

@bot.command(name='source')
async def source_command(ctx):
    """Информация о поддержке"""
    embed = discord.Embed(
        title="🎵 Поддерживаемые источники",
        description="YouTube\nSoundCloud",
        color=0x3498db
    )
    await ctx.send(embed=embed)

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    token = os.getenv('TOKEN')
    
    if not token:
        print("\n❌ ОШИБКА: Токен не найден!")
        print("Добавьте TOKEN в переменные окружения на BotHost")
        exit(1)
    
    print("\n✅ Токен найден!")
    print("🔄 Запуск музыкального бота...\n")
    
    bot.run(token)
