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

# Обновляем yt-dlp
def update_ytdlp():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        print("✅ yt-dlp обновлен")
    except:
        print("⚠️ Не удалось обновить yt-dlp")

update_ytdlp()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Оптимальные настройки для YouTube
ytdl_format_options = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch5',  # Ищем 5 результатов для выбора
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
        self.url = data.get('webpage_url', '')
        self.duration = data.get('duration', 0)
        self.uploader = data.get('uploader', 'Неизвестно')
        self.thumbnail = data.get('thumbnail', '')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        
        try:
            # Создаем новый экземпляр для каждого запроса
            ydl = yt_dlp.YoutubeDL(ytdl_format_options)
            
            # Извлекаем информацию
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            
            if not data:
                return None
            
            # Обрабатываем результаты поиска
            if 'entries' in data:
                if not data['entries']:
                    return None
                
                # Берем первый результат
                data = data['entries'][0]
                
                # Проверяем, что результат действительно соответствует запросу
                # (можно добавить дополнительную фильтрацию здесь)
            
            if not data or 'url' not in data:
                return None
            
            # Получаем прямую ссылку на аудио
            audio_url = data['url']
            if 'formats' in data:
                # Ищем лучший аудиоформат
                audio_formats = [f for f in data['formats'] if f.get('vcodec') == 'none']
                if audio_formats:
                    audio_formats.sort(key=lambda f: f.get('tbr', 0), reverse=True)
                    audio_url = audio_formats[0]['url']
            
            print(f"✅ Найдено: {data.get('title')}")
            return cls(discord.FFmpegPCMAudio(audio_url, **ffmpeg_options), data=data)
            
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
    print(f'✅ Бот {bot.user} запущен!')
    print(f'📋 На серверах: {len(bot.guilds)}')
    print(f'{"="*50}\n')
    await bot.change_presence(activity=discord.Game(name="/play | !play"))

# Основная команда play
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
            await interaction.followup.send("❌ Не удалось найти трек. Попробуйте другое название или ссылку.")
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

# Остальные команды
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

@bot.tree.command(name="help", description="📋 Помощь")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Команды",
        description="**Музыкальный бот**",
        color=0x9b59b6
    )
    commands = [
        ("`/play [запрос]`", "🎵 Играть музыку"),
        ("`/pause`", "⏸️ Пауза"),
        ("`/resume`", "▶️ Продолжить"),
        ("`/skip`", "⏭️ Пропустить"),
        ("`/stop`", "⏹️ Остановить"),
        ("`/queue`", "📋 Очередь"),
        ("`/nowplaying`", "ℹ️ Что играет"),
        ("`/volume [0-100]`", "🔊 Громкость"),
        ("`/help`", "📋 Помощь")
    ]
    for cmd, desc in commands:
        embed.add_field(name=cmd, value=desc, inline=False)
    await interaction.response.send_message(embed=embed)

# Префиксные команды
@bot.command(name='play')
async def play_command(ctx, *, query):
    interaction = await commands.Context.to_interface(ctx)
    await slash_play(interaction, query)

@bot.command(name='test')
async def test_command(ctx, *, query):
    """Тест поиска"""
    await ctx.send(f"🔍 Тестирую: {query}")
    
    try:
        ydl = yt_dlp.YoutubeDL({'format': 'best', 'quiet': True})
        result = ydl.extract_info(f"ytsearch5:{query}", download=False)
        
        if result and 'entries' in result:
            await ctx.send(f"✅ Найдено результатов: {len(result['entries'])}")
            for i, entry in enumerate(result['entries'][:3], 1):
                await ctx.send(f"{i}. {entry.get('title')} - {entry.get('uploader')}")
        else:
            await ctx.send("❌ Ничего не найдено")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {str(e)[:200]}")

@bot.command(name='ping')
async def ping_command(ctx):
    await ctx.send(f"иди нахуй сука! {round(bot.latency * 1000)}ms")

# Запуск
if __name__ == "__main__":
    token = os.getenv('TOKEN')
    if not token:
        print("❌ Токен не найден!")
        exit(1)
    
    print("🚀 Запуск бота...")
    bot.run(token)
