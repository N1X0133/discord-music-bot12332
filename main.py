import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
import os
import logging
import re
import ssl
import certifi
import subprocess
import sys
from datetime import datetime

# Принудительное обновление yt-dlp
def update_ytdlp():
    try:
        print("🔄 Проверка обновлений yt-dlp...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        print("✅ yt-dlp обновлен")
    except:
        print("⚠️ Не удалось обновить yt-dlp")

update_ytdlp()

# Исправление SSL ошибок
try:
    ssl._create_default_https_context = ssl._create_unverified_context
    print("✅ SSL проверка отключена")
except:
    pass

# Устанавливаем сертификаты
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# Создаем файл куков для YouTube (помогает обойти блокировки)
def create_cookie_file():
    try:
        with open('cookies.txt', 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write(".youtube.com\tTRUE\t/\tTRUE\t1735689600\tCONSENT\tYES+1\n")
            f.write(".youtube.com\tTRUE\t/\tTRUE\t1735689600\t__Secure-3PSIDCC\tAIKvawXx\n")
            f.write(".youtube.com\tTRUE\t/\tTRUE\t1735689600\t__Secure-3PAPISID\tAIKvawXx\n")
            f.write(".youtube.com\tTRUE\t/\tTRUE\t1735689600\t__Secure-3PSID\tAIKvawXx\n")
        print("✅ Cookie файл создан")
    except:
        print("⚠️ Не удалось создать cookie файл")

create_cookie_file()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Настройки для YouTube/SoundCloud с обходом блокировок
ytdl_format_options = {
    'format': 'bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'force-ipv4': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'cookiefile': 'cookies.txt',
    'geo_bypass': True,
    'geo_bypass_country': 'US',  # Обход гео-блокировок через US
    'geo_bypass_ip_block': None,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web', 'ios', 'tv'],  # Все возможные клиенты
            'skip': ['hls', 'dash'],  # Пропускаем проблемные форматы
            'include_dash_manifest': False,
            'include_hls_manifest': False,
        },
        'soundcloud': {
            'formats': 'bestaudio/best',
        }
    },
    'http_headers': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Sec-Fetch-Mode': 'navigate',
        'Connection': 'keep-alive',
    },
    'youtube_include_dash_manifest': False,
    'extractor_retries': 3,  # Количество попыток
    'fragment_retries': 3,
    'retry_sleep': 3,
    'file_access_retries': 3,
}

# Список прокси (если есть возможность добавить прокси, иначе оставить пустым)
PROXY_LIST = [
    # 'http://proxy1:port',
    # 'http://proxy2:port',
    # 'socks5://proxy3:port',
]

# Добавляем прокси если есть
if PROXY_LIST:
    import random
    ytdl_format_options['proxy'] = random.choice(PROXY_LIST)

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

# Альтернативный метод загрузки через разные домены
def get_alternative_urls(url):
    """Генерирует альтернативные URL для обхода блокировок"""
    alternatives = [url]
    
    if 'youtube.com' in url or 'youtu.be' in url:
        # Пробуем разные домены YouTube
        video_id = None
        if 'youtube.com/watch?v=' in url:
            video_id = url.split('watch?v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
        
        if video_id:
            alternatives.append(f"https://www.youtube-nocookie.com/watch?v={video_id}")
            alternatives.append(f"https://youtube.googleapis.com/watch?v={video_id}")
            alternatives.append(f"https://www.youtube.com/embed/{video_id}")
            alternatives.append(f"ytsearch:{video_id}")
    
    elif 'soundcloud.com' in url:
        # Для SoundCloud пробуем разные подходы
        alternatives.append(url.replace('soundcloud.com', 'm.soundcloud.com'))
    
    return alternatives

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Неизвестно')
        self.url = data.get('url', '')
        self.duration = data.get('duration', 0)
        self.uploader = data.get('uploader', data.get('channel', 'Неизвестно'))
        self.thumbnail = data.get('thumbnail', data.get('thumbnails', [{}])[-1].get('url') if data.get('thumbnails') else None)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        
        # Пробуем разные варианты если это не ссылка
        search_query = url
        if not url.startswith('http'):
            search_query = f"ytsearch:{url}"
        
        # Получаем альтернативные URL для обхода блокировок
        urls_to_try = get_alternative_urls(search_query)
        
        for attempt, try_url in enumerate(urls_to_try, 1):
            try:
                print(f"🔍 Попытка {attempt}: {try_url}")
                
                # Добавляем задержку между попытками
                if attempt > 1:
                    await asyncio.sleep(2)
                
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(try_url, download=not stream))
                
                if data is None:
                    print(f"❌ Попытка {attempt}: yt-dlp вернул None")
                    continue
                    
                if 'entries' in data:
                    # Берем первый трек из плейлиста или поиска
                    if len(data['entries']) > 0:
                        data = data['entries'][0]
                    else:
                        print(f"❌ Попытка {attempt}: Пустой плейлист/поиск")
                        continue
                
                filename = data['url'] if stream else ytdl.prepare_filename(data)
                print(f"✅ Успешно загружено: {data.get('title', 'Неизвестно')}")
                return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
                
            except Exception as e:
                print(f"❌ Попытка {attempt} ошибка: {str(e)[:100]}")
                continue
        
        print("❌ Все попытки загрузки не удались")
        return None

def extract_spotify_info(url):
    """Извлечение информации из Spotify ссылки"""
    if not SPOTIFY_ENABLED:
        return None
    
    try:
        # Определяем тип контента
        if 'track' in url:
            track_id = url.split('track/')[-1].split('?')[0]
            track = spotify_client.track(track_id)
            
            artists = ', '.join([artist['name'] for artist in track['artists']])
            query = f"{artists} - {track['name']}"
            return {
                'type': 'track',
                'query': query,
                'title': f"{artists} - {track['name']}"
            }
            
        elif 'playlist' in url:
            playlist_id = url.split('playlist/')[-1].split('?')[0]
            playlist = spotify_client.playlist(playlist_id)
            return {
                'type': 'playlist',
                'name': playlist['name'],
                'tracks': [
                    f"{track['track']['artists'][0]['name']} - {track['track']['name']}"
                    for track in playlist['tracks']['items'][:10]
                ]
            }
            
        elif 'album' in url:
            album_id = url.split('album/')[-1].split('?')[0]
            album = spotify_client.album(album_id)
            return {
                'type': 'album',
                'name': album['name'],
                'tracks': [
                    f"{album['artists'][0]['name']} - {track['name']}"
                    for track in album['tracks']['items'][:10]
                ]
            }
    except Exception as e:
        logging.error(f"Ошибка Spotify: {e}")
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
        print(f"✅ Слэш-команды синхронизированы")

bot = MusicBot()

# Очередь песен
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
    print(f'🎵 Поддержка: YouTube, SoundCloud (с обходом блокировок)')
    print(f'{"="*50}\n')
    
    await bot.change_presence(activity=discord.Game(name="/help | /play"))

# ==================== СЛЭШ-КОМАНДЫ ====================

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
    
    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    
    # Подключение к голосовому каналу
    try:
        if voice_client:
            if voice_client.channel == channel:
                pass
            else:
                await voice_client.move_to(channel)
        else:
            voice_client = await channel.connect(timeout=20.0, reconnect=True)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Ошибка подключения",
            description=f"Не удалось подключиться: {str(e)[:100]}",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)
        return
    
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

@bot.tree.command(name="np", description="ℹ️ Что играет сейчас (сокращенно)")
async def slash_np(interaction: discord.Interaction):
    await slash_nowplaying(interaction)

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
        description="**Музыкальный бот с обходом блокировок РФ**",
        color=0x9b59b6,
        timestamp=datetime.now()
    )
    
    embed.add_field(name="🎵 Поддерживаемые платформы", value="YouTube, SoundCloud (с обходом блокировок)", inline=False)
    
    commands = [
        ("`/play [запрос]`", "🎵 Воспроизвести (ссылка или название)"),
        ("`/pause`", "⏸️ Пауза"),
        ("`/resume`", "▶️ Продолжить"),
        ("`/skip`", "⏭️ Пропустить"),
        ("`/stop`", "⏹️ Остановить"),
        ("`/queue`", "📋 Очередь"),
        ("`/nowplaying`", "ℹ️ Что играет"),
        ("`/np`", "ℹ️ Что играет (сокращенно)"),
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

@bot.command(name='commands', aliases=['h', 'helpme', 'команды'])
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
async def test_command(ctx, *, url):
    """Тестовая команда для диагностики"""
    await ctx.send(f"🔍 Тестирую: {url}")
    
    try:
        # Проверяем версию
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        await ctx.send(f"✅ yt-dlp версия: {result.stdout}")
    except:
        await ctx.send("❌ yt-dlp не найден")
    
    # Пробуем разные методы
    methods = [
        ("Прямая ссылка", url),
        ("С поиском", f"ytsearch:{url}"),
    ]
    
    if 'youtube' in url:
        video_id = None
        if 'watch?v=' in url:
            video_id = url.split('watch?v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
        
        if video_id:
            methods.append(("YouTube nocookie", f"https://www.youtube-nocookie.com/watch?v={video_id}"))
            methods.append(("YouTube embed", f"https://www.youtube.com/embed/{video_id}"))
    
    for name, test_url in methods:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(test_url, download=False)
            )
            if info:
                if 'entries' in info and len(info['entries']) > 0:
                    await ctx.send(f"✅ {name}: Найден трек: {info['entries'][0].get('title', '?')}")
                elif info.get('title'):
                    await ctx.send(f"✅ {name}: {info.get('title')}")
                else:
                    await ctx.send(f"✅ {name}: Информация получена")
            else:
                await ctx.send(f"❌ {name}: Не удалось получить информацию")
        except Exception as e:
            await ctx.send(f"❌ {name}: Ошибка - {str(e)[:100]}")
            await asyncio.sleep(1)

# ==================== ЗАПУСК ====================

token = os.getenv('TOKEN')

if not token:
    print("\n❌ ОШИБКА: Токен не найден!")
    exit(1)

print("\n✅ Токен найден!")
print("🔄 Запуск музыкального бота с обходом блокировок...\n")

bot.run(token)
