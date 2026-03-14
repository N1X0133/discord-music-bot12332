import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import json
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка конфига
with open('config.json', 'r') as f:
    config = json.load(f)

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

# Настройка бота
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=config['prefix'],
    intents=intents,
    help_command=None
)

# Очередь песен
queues = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    await bot.change_presence(
        activity=discord.Game(name=config['activity']),
        status=discord.Status.online
    )

@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("❌ Вы должны быть в голосовом канале!")
        return
    
    channel = ctx.author.voice.channel
    voice_client = ctx.voice_client
    
    if voice_client and voice_client.is_connected():
        if voice_client.channel != channel:
            await voice_client.move_to(channel)
    else:
        voice_client = await channel.connect()
    
    loading_msg = await ctx.send("🔍 Ищу трек...")
    
    try:
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        
        if player is None:
            await loading_msg.edit(content="❌ Не удалось найти трек")
            return
        
        if voice_client.is_playing():
            queue = get_queue(ctx.guild.id)
            queue.append(player)
            await loading_msg.edit(content=f"✅ Добавлено в очередь: **{player.title}**")
        else:
            voice_client.play(player, after=lambda e: after_play(ctx.guild.id))
            
            embed = discord.Embed(
                title="🎵 Сейчас играет",
                description=f"**{player.title}**",
                color=discord.Color.green()
            )
            
            if player.duration:
                minutes = player.duration // 60
                seconds = player.duration % 60
                embed.add_field(name="Длительность", value=f"{minutes}:{seconds:02d}")
            
            if player.uploader:
                embed.add_field(name="Автор", value=player.uploader)
            
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
            
            embed.set_footer(text=f"Запросил: {ctx.author.display_name}")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)
            
    except Exception as e:
        await loading_msg.edit(content=f"❌ Ошибка: {str(e)[:100]}")

def after_play(guild_id):
    queue = get_queue(guild_id)
    if queue:
        next_player = queue.pop(0)
        for voice_client in bot.voice_clients:
            if voice_client.guild.id == guild_id:
                voice_client.play(next_player, after=lambda e: after_play(guild_id))
                break

@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        await ctx.send("❌ Сейчас ничего не играет")
        return
    voice_client.stop()
    await ctx.send("⏭️ Трек пропущен")

@bot.command(name='pause')
async def pause(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        await ctx.send("❌ Сейчас ничего не играет")
        return
    voice_client.pause()
    await ctx.send("⏸️ Пауза")

@bot.command(name='resume')
async def resume(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_paused():
        await ctx.send("❌ Нет трека на паузе")
        return
    voice_client.resume()
    await ctx.send("▶️ Продолжаем")

@bot.command(name='stop', aliases=['leave'])
async def stop(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_connected():
        if ctx.guild.id in queues:
            queues[ctx.guild.id] = []
        await voice_client.disconnect()
        await ctx.send("👋 Отключился")
    else:
        await ctx.send("❌ Я не в голосовом канале")

@bot.command(name='queue', aliases=['q'])
async def show_queue(ctx):
    queue = get_queue(ctx.guild.id)
    voice_client = ctx.voice_client
    
    embed = discord.Embed(title="📋 Очередь", color=discord.Color.blue())
    
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'title'):
        embed.add_field(name="🎵 Сейчас играет", value=f"**{voice_client.source.title}**", inline=False)
    
    if queue:
        queue_text = ""
        for i, track in enumerate(queue[:10], 1):
            queue_text += f"{i}. **{track.title}**\n"
        if len(queue) > 10:
            queue_text += f"... и еще {len(queue) - 10}"
        embed.add_field(name="В очереди:", value=queue_text, inline=False)
    else:
        embed.add_field(name="В очереди:", value="Пусто", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='nowplaying', aliases=['np'])
async def now_playing(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing() or not hasattr(voice_client.source, 'title'):
        await ctx.send("❌ Сейчас ничего не играет")
        return
    
    embed = discord.Embed(
        title="🎵 Сейчас играет",
        description=f"**{voice_client.source.title}**",
        color=discord.Color.green()
    )
    
    if hasattr(voice_client.source, 'duration'):
        minutes = voice_client.source.duration // 60
        seconds = voice_client.source.duration % 60
        embed.add_field(name="Длительность", value=f"{minutes}:{seconds:02d}")
    
    await ctx.send(embed=embed)

@bot.command(name='volume', aliases=['vol'])
async def volume(ctx, volume: int = None):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.source:
        await ctx.send("❌ Сейчас ничего не играет")
        return
    
    if volume is None:
        current_vol = int(voice_client.source.volume * 100)
        await ctx.send(f"🔊 Громкость: **{current_vol}%**")
        return
    
    if volume < 0 or volume > 100:
        await ctx.send("❌ Громкость от 0 до 100")
        return
    
    voice_client.source.volume = volume / 100
    await ctx.send(f"🔊 Громкость: **{volume}%**")

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(
        title="🎵 Помощь",
        description=f"Префикс: **{config['prefix']}**",
        color=discord.Color.purple()
    )
    
    commands = [
        ("play <ссылка>", "Играть музыку"),
        ("pause", "Пауза"),
        ("resume", "Продолжить"),
        ("skip", "Пропустить"),
        ("stop", "Отключиться"),
        ("queue", "Очередь"),
        ("nowplaying", "Что играет"),
        ("volume [0-100]", "Громкость"),
        ("help", "Помощь")
    ]
    
    for cmd, desc in commands:
        embed.add_field(name=f"`{config['prefix']}{cmd}`", value=desc, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send(f"🏓 Понг! Задержка: **{round(bot.latency * 1000)}ms**")

if __name__ == "__main__":
    bot.run(config['token'])
