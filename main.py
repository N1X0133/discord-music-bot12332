import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
import os
import logging
import re
from datetime import datetime

# Spotify импорт (если установлен)
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    SPOTIFY_AVAILABLE = True
except ImportError:
    SPOTIFY_AVAILABLE = False
    print("⚠️ Spotify не установлен. Установите: pip install spotipy")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Настройки для YouTube/SoundCloud (yt-dlp)
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
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'force-ipv4': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

# Инициализация Spotify (если есть ключи)
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

if SPOTIFY_AVAILABLE and SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        spotify_client = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        ))
        SPOTIFY_ENABLED = True
        print("✅ Spotify подключен!")
    except:
        SPOTIFY_ENABLED = False
        print("❌ Ошибка подключения Spotify")
else:
    SPOTIFY_ENABLED = False
    print("⚠️ Spotify не настроен. Добавьте SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET в переменные окружения")

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
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            
            if data is None:
                return None
                
            if 'entries' in data:
                # Берем первый трек из плейлиста
                data = data['entries'][0]
            
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except Exception as e:
            logging.error(f"Ошибка загрузки: {e}")
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
                    for track in playlist['tracks']['items'][:10]  # Первые 10 треков
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
                    for track in album['tracks']['items'][:10]  # Первые 10 треков
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
# intents.members = True  # Отключено

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
    print(f'🎵 Поддержка: YouTube, SoundCloud', end='')
    if SPOTIFY_ENABLED:
        print(', Spotify (поиск)')
    else:
        print('')
    print(f'{"="*50}\n')
    
    await bot.change_presence(activity=discord.Game(name="/help | /play"))

# ==================== СЛЭШ-КОМАНДЫ ====================

@bot.tree.command(name="play", description="🎵 Воспроизвести музыку (YouTube, SoundCloud, Spotify)")
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
    
    search_query = запрос
    
    # Обработка Spotify ссылок
    if SPOTIFY_ENABLED and ('spotify.com' in запрос):
        spotify_info = extract_spotify_info(запрос)
        
        if spotify_info:
            if spotify_info['type'] == 'track':
                search_query = spotify_info['query']
                embed = discord.Embed(
                    title="🎵 Spotify трек",
                    description=f"Ищем: **{spotify_info['title']}**",
                    color=0x1DB954
                )
                await interaction.followup.send(embed=embed)
            
            elif spotify_info['type'] in ['playlist', 'album']:
                embed = discord.Embed(
                    title=f"📋 Spotify {spotify_info['type']}",
                    description=f"**{spotify_info['name']}**\nДобавляю первые 10 треков в очередь...",
                    color=0x1DB954
                )
                await interaction.followup.send(embed=embed)
                
                for track_query in spotify_info['tracks']:
                    try:
                        player = await YTDLSource.from_url(track_query, loop=bot.loop, stream=True)
                        if player:
                            queue = get_queue(interaction.guild_id)
                            queue.append(player)
                    except:
                        pass
                
                embed = discord.Embed(
                    title="✅ Плейлист добавлен",
                    description=f"Добавлено {len(spotify_info['tracks'])} треков в очередь",
                    color=0x2ecc71
                )
                await interaction.followup.send(embed=embed)
                return
    
    try:
        player = await YTDLSource.from_url(search_query, loop=bot.loop, stream=True)
        
        if player is None:
            # Если не нашли по ссылке, пробуем как поисковый запрос
            if not is_url(search_query):
                player = await YTDLSource.from_url(f"ytsearch:{search_query}", loop=bot.loop, stream=True)
            
            if player is None:
                embed = discord.Embed(
                    title="❌ Ошибка",
                    description="Не удалось найти трек. Попробуйте:\n"
                              "• Ссылку на YouTube\n"
                              "• Ссылку на SoundCloud\n"
                              "• Название трека",
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
                embed.set_footer(text=f"Всего в очереди: {len(queue)} треков • {hours}ч {minutes}мин")
            else:
                embed.set_footer(text=f"Всего в очереди: {len(queue)} треков • {minutes}мин")
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
        description="**Музыкальный бот**",
        color=0x9b59b6,
        timestamp=datetime.now()
    )
    
    platforms = "YouTube, SoundCloud"
    if SPOTIFY_ENABLED:
        platforms += ", Spotify"
    
    embed.add_field(name="🎵 Поддерживаемые платформы", value=platforms, inline=False)
    
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
    """!play [ссылка или запрос] - воспроизвести музыку"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_play(interaction, query)

@bot.command(name='pause')
async def pause_command(ctx):
    """!pause - поставить на паузу"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_pause(interaction)

@bot.command(name='resume')
async def resume_command(ctx):
    """!resume - продолжить воспроизведение"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_resume(interaction)

@bot.command(name='skip')
async def skip_command(ctx):
    """!skip - пропустить текущий трек"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_skip(interaction)

@bot.command(name='stop')
async def stop_command(ctx):
    """!stop - остановить и отключиться"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_stop(interaction)

@bot.command(name='queue', aliases=['q'])
async def queue_command(ctx):
    """!queue - показать очередь"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_queue(interaction)

@bot.command(name='np', aliases=['now'])
async def np_command(ctx):
    """!np - что играет сейчас"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_nowplaying(interaction)

@bot.command(name='volume', aliases=['vol'])
async def volume_command(ctx, volume: int):
    """!volume [0-100] - изменить громкость"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_volume(interaction, volume)

@bot.command(name='clear')
async def clear_command(ctx):
    """!clear - очистить очередь"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_clear(interaction)

@bot.command(name='commands', aliases=['h', 'helpme', 'команды'])
async def commands_list(ctx):
    """!commands - показать список команд"""
    interaction = await commands.Context.to_interface(ctx)
    await slash_help(interaction)

@bot.command(name='ping')
async def ping_command(ctx):
    """!ping - проверить задержку бота"""
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="иди нахуй сука!",
        description=f"Задержка: **{latency}ms**",
        color=0x2ecc71
    )
    await ctx.send(embed=embed)

@bot.command(name='sources')
async def sources_command(ctx):
    """!sources - показать поддерживаемые источники"""
    embed = discord.Embed(
        title="🎵 Поддерживаемые источники",
        color=0x3498db
    )
    
    sources = [
        "✅ **YouTube** (ссылки и поиск)",
        "✅ **SoundCloud** (ссылки и поиск)",
    ]
    
    if SPOTIFY_ENABLED:
        sources.append("✅ **Spotify** (треки, плейлисты, альбомы)")
    else:
        sources.append("❌ **Spotify** (не настроен)")
    
    embed.add_field(name="Музыкальные платформы", value="\n".join(sources), inline=False)
    embed.add_field(name="📝 Форматы", value="• Ссылки на треки\n• Поиск по названию\n• Spotify конвертация", inline=False)
    
    await ctx.send(embed=embed)

# ==================== ЗАПУСК ====================

# Токен берется ТОЛЬКО из переменных окружения
token = os.getenv('TOKEN')

if not token:
    print("\n❌ ОШИБКА: Токен не найден в переменных окружения!")
    print("=" * 50)
    print("📝 Инструкция для BotHost:")
    print("1. Зайдите в панель управления ботом")
    print("2. Найдите раздел 'Environment Variables'")
    print("3. Добавьте переменную:")
    print("   ИМЯ: TOKEN")
    print("   ЗНАЧЕНИЕ: [ваш токен сюда]")
    print("=" * 50)
    print("\n❌ Бот не может запуститься без токена!")
    exit(1)

print("\n✅ Токен найден в переменных окружения!")
print(f"📋 Первые символы токена: {token[:10]}...")
print("🔄 Запуск музыкального бота...\n")

bot.run(token)
