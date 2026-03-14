import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import logging
import re
import ssl
import subprocess
import sys
from datetime import datetime

# Отключаем SSL
ssl._create_default_https_context = ssl._create_unverified_context

# Функция для установки стабильной версии yt-dlp
def setup_ytdlp():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp==2024.12.23"])
        print("✅ yt-dlp 2024.12.23 установлен")
    except:
        print("⚠️ Не удалось установить yt-dlp")

setup_ytdlp()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Функция для генерации альтернативных URL (обход блокировок)
def get_alternative_urls(url):
    """Генерирует альтернативные URL для обхода блокировок РФ"""
    alternatives = [url]
    
    if 'youtube.com' in url or 'youtu.be' in url:
        video_id = None
        if 'watch?v=' in url:
            video_id = url.split('watch?v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
        
        if video_id:
            alternatives.append(f"https://www.youtube-nocookie.com/watch?v={video_id}")
            alternatives.append(f"https://youtube.googleapis.com/watch?v={video_id}")
            alternatives.append(f"https://www.youtube.com/embed/{video_id}")
            alternatives.append(f"https://inv.nadeko.net/watch?v={video_id}")  # Invidious
            alternatives.append(f"https://yewtu.be/watch?v={video_id}")  # Альтернативный фронтенд
    
    elif 'soundcloud.com' in url:
        alternatives.append(url.replace('soundcloud.com', 'm.soundcloud.com'))
        alternatives.append(url + '/tracks')
    
    return alternatives

# Расширенные настройки для YouTube и SoundCloud
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
    'geo_bypass_ip_block': '0.0.0.0/0',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web', 'ios', 'tv'],
            'skip': ['hls', 'dash'],
            'include_dash_manifest': False,
            'include_hls_manifest': False,
        },
        'soundcloud': {
            'formats': 'bestaudio/best',
            'client_id': 'a3e059563d7fd3372b49b37f00a00bcf',  # Публичный client_id
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    },
    'extractor_retries': 5,
    'fragment_retries': 5,
    'retry_sleep': 3,
    'file_access_retries': 5,
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
        self.description = data.get('description', '')[:200]

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        
        # Подготавливаем варианты для попыток
        attempts = []
        
        if url.startswith('http'):
            attempts = get_alternative_urls(url)
        else:
            # Пробуем разные поисковые запросы
            attempts = [
                f"ytsearch5:{url}",
                f"scsearch5:{url}",
                f"ytsearch:{url} official audio",
                f"ytsearch:{url} lyric video",
                url
            ]
        
        for attempt_num, attempt_url in enumerate(attempts, 1):
            try:
                print(f"🔍 Попытка {attempt_num}: {attempt_url[:60]}...")
                
                # Создаем новый экземпляр для каждой попытки
                with yt_dlp.YoutubeDL(ytdl_format_options) as ydl:
                    data = await loop.run_in_executor(None, lambda: ydl.extract_info(attempt_url, download=False))
                
                if not data:
                    print(f"❌ Попытка {attempt_num}: нет данных")
                    continue
                
                # Обрабатываем результаты поиска
                if 'entries' in data and data['entries']:
                    print(f"📋 Найдено результатов: {len(data['entries'])}")
                    
                    # Если это поиск по названию, показываем первые результаты в лог
                    if not url.startswith('http'):
                        for i, entry in enumerate(data['entries'][:5], 1):
                            print(f"  {i}. {entry.get('title', '?')} - {entry.get('uploader', '?')}")
                    
                    # Берем первый результат
                    data = data['entries'][0]
                
                if not data or 'url' not in data:
                    print(f"❌ Попытка {attempt_num}: нет URL")
                    continue
                
                # Получаем лучшую аудио-ссылку
                audio_url = data['url']
                if 'formats' in data:
                    audio_formats = [f for f in data['formats'] if f.get('vcodec') == 'none']
                    if audio_formats:
                        audio_formats.sort(key=lambda f: f.get('tbr', 0), reverse=True)
                        audio_url = audio_formats[0]['url']
                        print(f"🎵 Выбран формат: {audio_formats[0].get('format_note', '?')}")
                
                print(f"✅ Успешно: {data.get('title', 'Unknown')}")
                return cls(discord.FFmpegPCMAudio(audio_url, **ffmpeg_options), data=data)
                
            except Exception as e:
                print(f"❌ Попытка {attempt_num} ошибка: {str(e)[:150]}")
                await asyncio.sleep(1)
                continue
        
        print("❌ Все попытки не удались")
        return None

def is_url(string):
    """Проверка является ли строка URL"""
    url_pattern = re.compile(r'https?://(?:www\.)?\S+')
    return bool(url_pattern.match(string))

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
    print(f'\n{"="*60}')
    print(f'✅ Музыкальный бот {bot.user} запущен!')
    print(f'📋 На серверах: {len(bot.guilds)}')
    print(f'🎵 Поддержка: YouTube, SoundCloud (с обходом блокировок РФ)')
    print(f'⚡ yt-dlp версия: 2024.12.23')
    print(f'{"="*60}\n')
    
    await bot.change_presence(activity=discord.Game(name="/help | /play"))

# ==================== ОСНОВНАЯ КОМАНДА PLAY ====================

@bot.tree.command(name="play", description="🎵 Воспроизвести музыку (YouTube, SoundCloud)")
async def slash_play(interaction: discord.Interaction, запрос: str):
    """Воспроизвести музыку по ссылке или названию"""
    
    if not interaction.user.voice:
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Вы должны находиться в голосовом канале!",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Подключение к голосовому каналу с повторными попытками
    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    
    for attempt in range(3):
        try:
            if voice_client:
                if voice_client.channel != channel:
                    await voice_client.move_to(channel)
            else:
                voice_client = await channel.connect(timeout=30.0, reconnect=True)
            break
        except Exception as e:
            if attempt == 2:
                embed = discord.Embed(
                    title="❌ Ошибка подключения",
                    description=f"Не удалось подключиться к голосовому каналу",
                    color=0xe74c3c
                )
                await interaction.followup.send(embed=embed)
                return
            await asyncio.sleep(2)
    
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
                description="Не удалось найти трек. Возможные причины:\n"
                          "• Видео заблокировано в РФ\n"
                          "• Проблемы с сетью\n"
                          "• Неверная ссылка\n\n"
                          "Попробуйте другую ссылку или название.",
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
            embed.add_field(name="Позиция", value=f"```{len(queue)}```", inline=True)
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
            
            embed.set_footer(text=f"Запросил: {interaction.user.name}")
            
            await interaction.followup.send(embed=embed)
            
    except Exception as e:
        embed = discord.Embed(
            title="❌ Ошибка",
            description=f"Произошла ошибка: {str(e)[:200]}",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)

def after_play(guild_id):
    queue = get_queue(guild_id)
    if queue:
        next_player = queue.pop(0)
        for voice_client in bot.voice_clients:
            if voice_client.guild.id == guild_id:
                voice_client.play(next_player, after=lambda e: after_play(guild_id))
                break

# ==================== ОСТАЛЬНЫЕ СЛЭШ-КОМАНДЫ ====================

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
                embed.set_footer(text=f"Всего: {len(queue)} треков • {hours}ч {minutes}мин")
            else:
                embed.set_footer(text=f"Всего: {len(queue)} треков • {minutes}мин")
    else:
        embed.add_field(name="📌 В очереди:", value="```Пусто```", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="nowplaying", aliases=["np"], description="ℹ️ Что играет сейчас")
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
        description="**Музыкальный бот с обходом блокировок РФ**\nПоддержка: YouTube, SoundCloud",
        color=0x9b59b6,
        timestamp=datetime.now()
    )
    
    commands = [
        ("`/play [запрос]`", "🎵 Воспроизвести (ссылка или название)"),
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
    
    embed.set_footer(text="by Ilya Vetrov")
    
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
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="иди нахуй сука!",
        description=f"Задержка: **{latency}ms**",
        color=0x2ecc71
    )
    await ctx.send(embed=embed)

@bot.command(name='test')
async def test_command(ctx, *, query):
    """Тестовая команда для диагностики"""
    await ctx.send(f"🔍 Тестирую: {query}")
    
    try:
        # Проверяем версию
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        await ctx.send(f"✅ yt-dlp версия: {result.stdout}")
    except:
        await ctx.send("❌ yt-dlp не найден")
    
    # Пробуем разные методы загрузки
    methods = []
    
    if query.startswith('http'):
        methods = [("Прямая ссылка", query)]
        
        # Добавляем альтернативные URL
        if 'youtube' in query or 'youtu.be' in query:
            video_id = None
            if 'watch?v=' in query:
                video_id = query.split('watch?v=')[1].split('&')[0]
            elif 'youtu.be/' in query:
                video_id = query.split('youtu.be/')[1].split('?')[0]
            
            if video_id:
                methods.append(("YouTube nocookie", f"https://www.youtube-nocookie.com/watch?v={video_id}"))
                methods.append(("YouTube embed", f"https://www.youtube.com/embed/{video_id}"))
                methods.append(("Invidious", f"https://inv.nadeko.net/watch?v={video_id}"))
    else:
        methods = [
            ("Поиск YouTube", f"ytsearch3:{query}"),
            ("Поиск SoundCloud", f"scsearch3:{query}"),
        ]
    
    for method_name, test_url in methods:
        try:
            await asyncio.sleep(1)  # Небольшая задержка между запросами
            
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(test_url, download=False)
                
                if info:
                    if 'entries' in info and info['entries']:
                        first = info['entries'][0]
                        await ctx.send(f"✅ {method_name}: {first.get('title', '?')[:100]}")
                    else:
                        await ctx.send(f"✅ {method_name}: {info.get('title', '?')[:100]}")
                else:
                    await ctx.send(f"❌ {method_name}: Ничего не найдено")
        except Exception as e:
            await ctx.send(f"❌ {method_name}: Ошибка - {str(e)[:100]}")

@bot.command(name='sources')
async def sources_command(ctx):
    """Показать поддерживаемые источники"""
    embed = discord.Embed(
        title="🎵 Поддерживаемые источники",
        description="✅ YouTube (с обходом блокировок РФ)\n✅ SoundCloud\n",
        color=0x3498db
    )
    embed.add_field(name="📝 Форматы", value="• Прямые ссылки\n• Поиск по названию\n• Альтернативные домены для YouTube", inline=False)
    await ctx.send(embed=embed)

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    token = os.getenv('TOKEN')
    
    if not token:
        print("\n❌ ОШИБКА: Токен не найден в переменных окружения!")
        print("=" * 60)
        print("📝 Инструкция для BotHost:")
        print("1. Зайдите в панель управления ботом")
        print("2. Найдите раздел 'Environment Variables'")
        print("3. Добавьте переменную:")
        print("   ИМЯ: TOKEN")
        print("   ЗНАЧЕНИЕ: [ваш токен сюда]")
        print("=" * 60)
        exit(1)
    
    print("\n✅ Токен найден!")
    print("🔄 Запуск музыкального бота с обходом блокировок...\n")
    
    bot.run(token)
