from discord import message
from openskill.models import PlackettLuce
import asyncio
import discord
from discord.ext import commands, tasks
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import os

model = PlackettLuce()
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
global checked
bot = commands.Bot(command_prefix='!', intents=intents)

secret_role = "Matchmaking"

server_queue = []
active_matches = {}
queue_names = []

RATINGS_FILE = Path("ratings.json")
DEFAULT_MU = 25.0
DEFAULT_SIGMA = 8.333
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "1520844698007113849"))
LEADERBOARD_REFRESH_SECONDS = int(os.getenv("LEADERBOARD_REFRESH_SECONDS", "15"))
LEADERBOARD_LIMIT = int(os.getenv("LEADERBOARD_LIMIT", "10"))
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")


def load_player_ratings():
    if RATINGS_FILE.exists():
        try:
            with RATINGS_FILE.open("r", encoding="utf-8") as handle:
                return {str(k): value for k, value in json.load(handle).items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return {}


def save_player_ratings():
    with RATINGS_FILE.open("w", encoding="utf-8") as handle:
        json.dump({str(k): value for k, value in player_ratings.items()}, handle, indent=2)


def get_player_rating(player_id):
    player_id = str(player_id)
    if player_id not in player_ratings:
        player_ratings[player_id] = {"mu": DEFAULT_MU, "sigma": DEFAULT_SIGMA}
        save_player_ratings()
    return player_ratings[player_id]


def update_player_rating(player_id, mu, sigma):
    player_id = str(player_id)
    player_ratings[player_id] = {"mu": mu, "sigma": sigma}
    save_player_ratings()


player_ratings = load_player_ratings()

def build_leaderboard_content():
    rankings = []
    for player_id, data in player_ratings.items():
        try:
            member = bot.get_user(int(player_id))
            name = member.display_name if member else f"User {player_id}"
        except (ValueError, discord.HTTPException, discord.NotFound):
            name = f"User {player_id}"

        mu = data.get("mu", DEFAULT_MU)
        rankings.append((mu, name))

    top_players = sorted(rankings, key=lambda x: x[0], reverse=True)[:LEADERBOARD_LIMIT]
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    if not top_players:
        return f"Leaderboard last updated: {ts}\nNo ranked players yet."

    lines = [f"Leaderboard last updated: {ts}", "", "**Top 10 Ranked Players**"]
    for index, (mu, name) in enumerate(top_players, start=1):
        lines.append(f"{index}. **{name}** — MU: {mu:.2f}")

    return "\n".join(lines)

async def update_leaderboard_message():
    channel = None
    try:
        channel = await bot.fetch_channel(LEADERBOARD_CHANNEL_ID)
    except Exception:
        channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)

    if channel is None:
        for guild in bot.guilds:
            for text_channel in guild.text_channels:
                if text_channel.name.lower() in {"leaderboard", "ranked-leaderboard", "bot-spam"}:
                    channel = text_channel
                    break
            if channel is not None:
                break

    if channel is None:
        print(f"Leaderboard channel {LEADERBOARD_CHANNEL_ID} not found or inaccessible.")
        return False

    try:
        await channel.purge(limit=20)
    except Exception:
        pass

    await channel.send(build_leaderboard_content())
    return True


@bot.event
async def on_ready():
    print(f"{bot.user.name} is online!")
    if not leaderboard_task.is_running():
        leaderboard_task.start()
    await update_leaderboard_message()


@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the AFQM Ranked Lounge, {member.name}!")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "balls" in message.content.lower():
        await message.channel.send(f'what the??? sex penis???')

    await bot.process_commands(message)

@bot.command()
async def ping(ctx):
    await ctx.send(f"hello {ctx.author.mention}!")

@bot.command()
async def assign(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"ill write ya down, {ctx.author.mention}")
    else:
        await ctx.send(f"Role not found, Sorry!")

@bot.command()
@commands.has_role(secret_role)
async def matchmaking(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    await ctx.send(f"{role.mention}, {ctx.author.mention} is looking for a match.")

@bot.command()    
async def queue(ctx):
    # 1. Restrict the command strictly to the #queue channel
    if ctx.channel.name != "queue":
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        error_msg = await ctx.send(f"{ctx.author.mention} ❌ get back in **#queue**, ya dummy ")
        await asyncio.sleep(5)
        await error_msg.delete()
        return

    # 2. Add or remove the user from the temporary local queue lists
    if ctx.author.id not in server_queue:
        queue_names.append(ctx.author.name)
        server_queue.append(ctx.author.id)
        await ctx.send(f"{ctx.author.mention} added to da list. there are **#{len(server_queue)}** people on da list.")
    else:
        server_queue.remove(ctx.author.id)
        queue_names.remove(ctx.author.name)
        await ctx.send(f"{ctx.author.mention} removed from da list. there are **#{len(server_queue)}** people in da list.")
        
    # 3. Matchmaking trigger (when 2 or more players are waiting)
    if len(server_queue) >= 2:
        await ctx.send(f"**{len(server_queue)}** players are on da list. gonna put some of ya in a match.")
        
        # Pull the first two oldest player IDs out of the queue
        player1_id = server_queue[0]
        player2_id = server_queue[1]
        player1_name = queue_names[0]
        player2_name = queue_names[1]
        
        p1_data = get_player_rating(player1_id)
        p2_data = get_player_rating(player2_id)
        
        p1mu = p1_data["mu"]
        p2mu = p2_data["mu"]

        # 4. Gather the member objects from Discord for permission assignment
        guild = ctx.guild
        p1_member = guild.get_member(player1_id) or await guild.fetch_member(player1_id)
        p2_member = guild.get_member(player2_id) or await guild.fetch_member(player2_id)
        
        # Setup private channel text visibility overwrites
        staff_role = discord.utils.get(guild.roles, name="Staff") 
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False), # Hide from everyone
            p1_member: discord.PermissionOverwrite(read_messages=True, send_messages=True), # Allow player 1
            p2_member: discord.PermissionOverwrite(read_messages=True, send_messages=True), # Allow player 2
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # 5. Spin up the private text room
        channel_name = f"match-{player1_name}-vs-{player2_name}"
        match_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
        
        # Track that this live room belongs to these two specific player IDs
        active_matches[match_channel.id] = (player1_id, player2_id)
        
        # Send details directly into the newly generated room
        await match_channel.send(
            f" welcome {p1_member.mention} and {p2_member.mention} to your private grudge match\n"
            f"**here's what ive got for ya in my scroll:**\n"
            f"{player1_name}: `{p1mu:.2f}`\n"
            f"{player2_name}: `{p2mu:.2f}`\n\n"
            f"use `!report` to get my attention when you guys are done."
        )
        
        # 6. QUEUE CLEANUP
        # Delete only the 2 matched individuals from the front of the queue
        del server_queue[:2]
        del queue_names[:2]

@tasks.loop(seconds=LEADERBOARD_REFRESH_SECONDS)
async def leaderboard_task():
    await update_leaderboard_message()

        
@bot.command()
async def leaderboard(ctx):
    if ctx.guild is None:
        await ctx.send("ya gotta be in a server, dummy.")
        return

    rankings = []
    for player_id, data in player_ratings.items():
        try:
            member = ctx.guild.get_member(int(player_id)) or await ctx.guild.fetch_member(int(player_id))
            name = member.display_name
        except (ValueError, discord.HTTPException, discord.NotFound):
            name = f"User {player_id}"

        mu = data.get("mu", DEFAULT_MU)
        rankings.append((mu, name))

    top_players = sorted(rankings, key=lambda x: x[0], reverse=True)[:10]

    if not top_players:
        await ctx.send("sorry, scrolls empty.")
        return

    lines = ["**heres the best of you bozos*"]
    for index, (mu, name) in enumerate(top_players, start=1):
        lines.append(f"{index}. **{name}** — MU: {mu:.2f}")

    await ctx.send("\n".join(lines))

@bot.command()
async def lb_init(ctx):
    if not leaderboard_task.is_running():
        leaderboard_task.start()
    await update_leaderboard_message()
    await ctx.send("Leaderboard refreshed.")

@bot.command()
async def commands(ctx):
    await ctx.send("whassup. \n"
                   "heres my little encyclopedia\n\n"
                   "!commands takes you here. welcome.\n\n"
                   "!ping pings ya. hello.\n\n"
                   "!assign gives ya the matchmaking role, and !matchmaking pings it. its necromancy for your grudge matches. dont overuse it.\n\n"
                   "!leaderboard shows you the top 10 whoosits and whatsits.\n\n"
                   "!queue adds you to queue, and doing it again takes ya out. groundbreaking. like a shovel.\n\n"
                   "once theres enough of ya rarin to go, ill start matchin ya up, and youll get your own private area to throw down.\n\n"
                   "once ya there, use !report to gimme the winner, and ill handle the math from there.\n"
                   "*dev note, ping staff if theres abuse going on. i can fix it and i will.*\n\n"
                   "you cant see your own placement unless you're top ten, and matchmaking isnt skill based\n"
                   "just first come, first serve.\n"
                   "i dont get paid enough to deal with that.\n"
                   "*dev note, this bot takes jash to keep up, and developing silly things like this is hard, so if you wanna keep server up and have new features, \n\n"
                   "message me, bwight___. my comms are open, and tips are appreciated! thanks!")
        

@bot.command()
async def leave(ctx):
    if ctx.channel.id in active_matches:
        player1_id, player2_id = active_matches[ctx.channel.id]
        if ctx.author.id not in {player1_id, player2_id}:
            await ctx.send("You are not a participant in this match.")
            return

        del active_matches[ctx.channel.id]
        await ctx.send(f"{ctx.author.mention} decided this wasnt worth their time. now go be loud somewhere else, i have math to do.")
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete()
        except discord.Forbidden:
            pass
        return

    if ctx.author.id in server_queue:
        server_queue.remove(ctx.author.id)
        queue_names.remove(ctx.author.name)
        await ctx.send(f"{ctx.author.mention} is off da scroll")
    else:
        await ctx.send(f"{ctx.author.mention}, you arent even on the scroll.")
@bot.command()
async def report(ctx):
    print("reporting")
    global checked
    checked = False

    # 1. SECURITY & ROOM CHECK
    if ctx.channel.id not in active_matches:
        await ctx.send("ayo, get back in da match channel! shoo, shoo!")
        return
    
    # 2. Extract the exact player IDs assigned to this channel
    player1_id, player2_id = active_matches[ctx.channel.id]
        
    p1_data = get_player_rating(player1_id)
    p2_data = get_player_rating(player2_id)

    # 4. Turn the data into local TrueSkill rating structures
    player1_rating = model.rating(mu=p1_data["mu"], sigma=p1_data["sigma"])
    player2_rating = model.rating(mu=p2_data["mu"], sigma=p2_data["sigma"])

    # 5. Fetch their usernames dynamically from Discord
    guild = ctx.guild
    p1_member = guild.get_member(player1_id) or await guild.fetch_member(player1_id)
    p2_member = guild.get_member(player2_id) or await guild.fetch_member(player2_id)
    p1_name = p1_member.name
    p2_name = p2_member.name

    await ctx.send(f"{ctx.author.mention}, who won? gimme da deets.")
    
    try:
        next_message = await bot.wait_for('message', timeout=15.0)
        if checked:
            return

        if next_message.author == bot.user:
            checked = False
            return

        # Case A: Player 1 Won
        if p1_name.lower() in next_message.content.lower():
            print("p1 won")
            try: await next_message.delete()
            except discord.Forbidden: pass
            
            await ctx.send(f"**{p1_name}** won? alright, its goin in da scroll")
            
            # Compute TrueSkill changes locally
            team1 = [player1_rating]
            team2 = [player2_rating]
            new_team1, new_team2 = model.rate([team1, team2], ranks=[1, 2])
            new_p1_rating = new_team1[0]
            new_p2_rating = new_team2[0]
            
            update_player_rating(player1_id, new_p1_rating.mu, new_p1_rating.sigma)
            update_player_rating(player2_id, new_p2_rating.mu, new_p2_rating.sigma)

            p1_change = new_p1_rating.mu - player1_rating.mu
            p2_change = new_p2_rating.mu - player2_rating.mu
            
            await ctx.send(
                f"**here's what im readin.**\n"
                f" winnin: <@{player1_id}> | ya new ratin: {new_p1_rating.mu:.2f} (+{p1_change:.2f})\n"
                f" losin: <@{player2_id}> | ya new ratin: {new_p2_rating.mu:.2f} ({p2_change:.2f})\n\n"
                f"*now get outta here. shoo, shoo!*"
            )
            
            del active_matches[ctx.channel.id]
            checked = True
            await asyncio.sleep(10)
            await ctx.channel.delete()

        # Case B: Player 2 Won
        elif p2_name.lower() in next_message.content.lower():
            print("p2 won")
            try: await next_message.delete()
            except discord.Forbidden: pass
            
            await ctx.send(f"**{p2_name}** won? alright, its goin in the scroll")
            
            # Compute TrueSkill changes locally
            team1 = [player1_rating]
            team2 = [player2_rating]
            new_team1, new_team2 = model.rate([team1, team2], ranks=[2, 1])
            new_p1_rating = new_team1[0]
            new_p2_rating = new_team2[0]
            
            update_player_rating(player1_id, new_p1_rating.mu, new_p1_rating.sigma)
            update_player_rating(player2_id, new_p2_rating.mu, new_p2_rating.sigma)

            p1_change = new_p1_rating.mu - player1_rating.mu
            p2_change = new_p2_rating.mu - player2_rating.mu
            
            await ctx.send(
                f"**alrighty, here's what ive got**\n"
                f" winnin: <@{player2_id}> | ya new number: {new_p2_rating.mu:.2f} (+{p2_change:.2f})\n"
                f" losin: <@{player1_id}> | ya new number: {new_p1_rating.mu:.2f} ({p1_change:.2f})\n\n"
                f"*now get outta here. shoo, shoo!*"
            )
            
            del active_matches[ctx.channel.id]
            checked = True
            await asyncio.sleep(10)
            await ctx.channel.delete()
            
        else:
            await ctx.send("huh? i dont got a clue what youre talkin about. speak up.")
            
    except asyncio.TimeoutError:
        await ctx.send("ya took too long. use !report to get my attention again when you're ready.")



bot.run(token, log_handler=handler, log_level=logging.DEBUG)

client = discord.Client(intents=intents)
