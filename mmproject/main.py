from discord import message
import aiohttp
from openskill.models import PlackettLuce
import asyncio
import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
import os

API_URL = "https://fastapi-production-6ed6.up.railway.app" 

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


@bot.event 
async def on_ready():
    print(f"{bot.user.name} is online!")

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
    await ctx.send(f"sup {ctx.author.mention}!")

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

        error_msg = await ctx.send(f"{ctx.author.mention} ayo get back in #queue , ya dummy")
        await asyncio.sleep(5)
        await error_msg.delete()
        return

    # 2. Add or remove the user from the temporary local queue lists
    if ctx.author.id not in server_queue:
        queue_names.append(ctx.author.name)
        server_queue.append(ctx.author.id)
        await ctx.send(f"{ctx.author.mention} added to the queue. there are **#{len(server_queue)}** people in the queue.")
    else:
        server_queue.remove(ctx.author.id)
        queue_names.remove(ctx.author.name)
        await ctx.send(f"{ctx.author.mention} removed from the queue. there are **#{len(server_queue)}** people in the queue.")
        
    # 3. Matchmaking trigger (when 2 or more players are waiting)
    if len(server_queue) >= 2:
        await ctx.send(f"**{len(server_queue)}** guys are here. lemme get you a room")
        
        # Pull the first two oldest player IDs out of the queue
        player1_id = server_queue[0]
        player2_id = server_queue[1]
        player1_name = queue_names[0]
        player2_name = queue_names[1]
        
        # --- FASTAPI FETCH LOGIC ---
        # Instead of looking up a local dictionary, we query your FastAPI endpoint
        # If the player is brand new, the API automatically generates their baseline 25.0 rating row
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/players/{str(player1_id)}") as r1, \
                       session.get(f"{API_URL}/players/{str(player2_id)}") as r2:
                
                if r1.status != 200 or r2.status != 200:
                    await ctx.send("❌ Error connecting to the ratings database server. Match canceled.")
                    return
                
                p1_data = await r1.json()
                p2_data = await r2.json()
                
                p1mu = p1_data["mu"]
        p2mu = p2_data["mu"]
        print("[Log] API data fetched successfully. Starting Discord member lookup...")

        # --- FIX 1: ENSURE TYPE SAFETY & ROBUST LOOKUP ---
        guild = ctx.guild
        p1_discord_id = int(player1_id)
        p2_discord_id = int(player2_id)

        # First, try to read from local cache (fastest, never stalls)
        p1_member = guild.get_member(p1_discord_id)
        p2_member = guild.get_member(p2_discord_id)

        # Fallback to fetch only if cache fails, wrapped in a fast try/except block
        try:
            if not p1_member:
                print(f"[Log] Fetching member {p1_discord_id} from Discord API...")
                p1_member = await guild.fetch_member(p1_discord_id)
            if not p2_member:
                print(f"[Log] Fetching member {p2_discord_id} from Discord API...")
                p2_member = await guild.fetch_member(p2_discord_id)
        except Exception as e:
            print(f"[Critical Error] Failed to fetch member from Discord: {e}")
            await ctx.send("❌ Error fetching player profiles from Discord. Matchroom setup aborted.")
            return

        print(f"[Log] Members found: {p1_member.name if p1_member else 'None'} & {p2_member.name if p2_member else 'None'}")

        # --- FIX 2: FALLBACK PERMISSION GENERATION ---
        # If Discord STILL returns None for a member, using them in overwrites crashes the channel creation
        if not p1_member or not p2_member:
            print("[Critical Error] One or both members returned None. Cannot build channel permissions.")
            await ctx.send("❌ Could not verify players in this server. Matchroom setup aborted.")
            return

        print("[Log] Creating channel permission dictionary...")
        staff_role = discord.utils.get(guild.roles, name="Staff") 
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            p1_member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            p2_member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # --- FIX 3: CREATE THE CHANNEL ---
        print("[Log] Sending text channel creation request to Discord...")
        try:
            channel_name = f"match-{player1_name}-vs-{player2_name}"
            match_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
            print(f"[Log] Channel '{channel_name}' created successfully with ID: {match_channel.id}")
        except discord.Forbidden:
            print("[Critical Error] Discord explicitly denied channel creation. Check 'Manage Channels' AND role hierarchy!")
            await ctx.send("❌ Bot lacks permissions to create channels in this category.")
            return
        except Exception as e:
            print(f"[Critical Error] Generic failure creating text channel: {e}")
            await ctx.send("❌ Failed to create match channel due to an internal error.")
            return
        
        # Track the active room
        active_matches[match_channel.id] = (player1_id, player2_id)
        
        await match_channel.send(
            f" welcome {p1_member.mention} and {p2_member.mention} to your personal grudgematch.\n"
            f"**ya numbers right now:**\n"
            f" {player1_name}: `{p1mu:.2f}`\n"
            f" {player2_name}: `{p2mu:.2f}`\n\n"
            f"use !report to get my attention when you two are done dukin it out."
        )
        
        # Queue cleanup
        del server_queue[:2]
        del queue_names[:2]
        print("[Log] Queue cleared. Matchmaking cycle completed successfully.")

@bot.command()
async def commands(ctx):
    await ctx.send("welcome to help!!!/n"
                   "!ping pings you (duh)/n"
                   "!queue adds you to the queue. do it again to leave./n"
                   "!assign gives you the matchmaking role, and !matchmaking pings it./n"
                   "dont spam./n"
                   "when someone else is in queue, youll get a custom channel!/n"
                   "wooh/n"
                   "then, use !report to report the results of the game/n"
                   "use the winning players discord *username*, not display name./n"
                   "discord dosent like giving those out./n"
                   "games are bo3, random stage./n /n"
                   "!leaderboard shows you the top 10 players./n"
                   "if youre not there, too bad./n"
                   "im paying to run the server for this bot, so i def dont/n"
                   "get paid enough to make that rn./n"
                   "to support the dev, and keep the server up, message bwight___ !/n"
                   "my comms are open and tips are appreciated!/n"
                   "also, /n"
                   "balls.")
                   
        
     
@tasks.loop(seconds=5.0)
async def leaderboard_task():
    # Replace with your target channel ID
    channel = bot.get_channel(1520844698007113849) 
    if channel:
        # Purge all existing messages in the channel, then post an updated leaderboard
        try:
            await channel.purge(limit=None)
        except Exception:
            # Fallback: delete messages one-by-one if bulk purge fails
            try:
                async for msg in channel.history(limit=None):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
            except Exception:
                pass

        rankings = []
        for player_id, data in player_ratings.items():
            try:
                member = await bot.fetch_user(int(player_id))
                name = member.display_name
            except (ValueError, discord.HTTPException, discord.NotFound):
                name = f"User {player_id}"

            mu = data.get("mu", DEFAULT_MU)
            rankings.append((mu, name))

        top_players = sorted(rankings, key=lambda x: x[0], reverse=True)[:10]

        # timestamp and send
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        if not top_players:
            await channel.send(f"Leaderboard last updated: {ts}\nNo ranked players yet.")
            return

        lines = [f"Leaderboard last updated: {ts}", "", "**Top 10 Ranked Players**"]
        for index, (mu, name) in enumerate(top_players, start=1):
            lines.append(f"{index}. **{name}** — MU: {mu:.2f}")

        await channel.send("\n".join(lines))

@bot.command()
async def leaderboard(ctx):
    if ctx.guild is None:
        await ctx.send("ya gotta be in a server dummy")
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
        await ctx.send("No ranked players yet.")
        return

    lines = ["**top 10 scroll people**"]
    for index, (mu, name) in enumerate(top_players, start=1):
        lines.append(f"{index}. **{name}** — mu: {mu:.2f}")

    await ctx.send("\n".join(lines))
   
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not leaderboard_task.is_running():
        leaderboard_task.start()

@bot.command()
async def lb_init(ctx):
    if not leaderboard_task.is_running():
        leaderboard_task.start()

@bot.command()
async def leave(ctx):

    if ctx.channel.id in active_matches:
        player1_id, player2_id = active_matches[ctx.channel.id]
        if ctx.author.id not in {player1_id, player2_id}:
            await ctx.send("you aint even a part of this.")
            return

        del active_matches[ctx.channel.id]
        await ctx.send(f"{ctx.author.mention} decided this aint worth their time. now scram, both of you.")
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete()
        except discord.Forbidden:
            pass
        return
    
    if ctx.author.id in server_queue:
        server_queue.remove(ctx.author.id)
        queue_names.remove(ctx.author.name)
        await ctx.send(f"{ctx.author.mention} is outta da scroll")
    else:
        await ctx.send(f"{ctx.author.mention} isnt even in the scroll.")

@bot.command()
async def report(ctx):
    print("reporting")
    global checked
    checked = False

    # 1. SECURITY & ROOM CHECK
    if ctx.channel.id not in active_matches:
        await ctx.send("get in your match room dummy")
        return
    
    # 2. Extract the exact player IDs assigned to this channel
    player1_id, player2_id = active_matches[ctx.channel.id]
        
    # 3. FASTAPI FETCH: Read current user scores from the API
    async with aiohttp.ClientSession() as session:
        # Wrap player1_id and player2_id in str()
        async with session.get(f"{API_URL}/players/{str(player1_id)}") as r1, \
                   session.get(f"{API_URL}/players/{str(player2_id)}") as r2:
            
            if r1.status != 200 or r2.status != 200:
                await ctx.send("❌ Error fetching active player data from the online server.")
                return
            
            p1_data = await r1.json()
            p2_data = await r2.json()

    # 4. Turn the data into local TrueSkill rating structures
    player1_rating = model.rating(mu=p1_data["mu"], sigma=p1_data["sigma"])
    player2_rating = model.rating(mu=p2_data["mu"], sigma=p2_data["sigma"])

    # 5. Fetch their usernames dynamically from Discord
    guild = ctx.guild
    p1_member = guild.get_member(player1_id) or await guild.fetch_member(player1_id)
    p2_member = guild.get_member(player2_id) or await guild.fetch_member(player2_id)
    p1_name = p1_member.name
    p2_name = p2_member.name

    await ctx.send(f"{ctx.author.mention}, say da winner's name so i can write it down")
    
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
            
            await ctx.send(f"**{p1_name}** won the match!")
            
            # Compute TrueSkill changes locally
            team1 = [player1_rating]
            team2 = [player2_rating]
            new_team1, new_team2 = model.rate([team1, team2], ranks=[1, 2])
            new_p1_rating = new_team1[0]
            new_p2_rating = new_team2[0]
            
            # 6. FASTAPI UPDATE: Structure payloads as JSON to match your API models
            p1_payload = {"mu": new_p1_rating.mu, "sigma": new_p1_rating.sigma}
            p2_payload = {"mu": new_p2_rating.mu, "sigma": new_p2_rating.sigma}
            
            async with aiohttp.ClientSession() as session:
                await session.put(f"{API_URL}/players/{str(player1_id)}", json=p1_payload)
                await session.put(f"{API_URL}/players/{str(player2_id)}", json=p2_payload)

            p1_change = new_p1_rating.mu - player1_rating.mu
            p2_change = new_p2_rating.mu - player2_rating.mu
            
            await ctx.send(
                f"**ok i wrote it down heres what i got**\n"
                f" winner: <@{player1_id}> | new rating: {new_p1_rating.mu:.2f} (+{p1_change:.2f})\n"
                f" loser: <@{player2_id}> | new rating: {new_p2_rating.mu:.2f} ({p2_change:.2f})\n\n"
                f"*now shoo*"
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
            
            await ctx.send(f"**{p2_name}** won the match!")
            
            # Compute TrueSkill changes locally
            team1 = [player1_rating]
            team2 = [player2_rating]
            new_team1, new_team2 = model.rate([team1, team2], ranks=[2, 1])
            new_p1_rating = new_team1[0]
            new_p2_rating = new_team2[0]
            
            # FASTAPI UPDATE: Structure payloads as JSON
            p1_payload = {"mu": new_p1_rating.mu, "sigma": new_p1_rating.sigma}
            p2_payload = {"mu": new_p2_rating.mu, "sigma": new_p2_rating.sigma}
            
            async with aiohttp.ClientSession() as session:
                await session.put(f"{API_URL}/players/{str(player1_id)}", json=p1_payload)
                await session.put(f"{API_URL}/players/{str(player2_id)}", json=p2_payload)

            p1_change = new_p1_rating.mu - player1_rating.mu
            p2_change = new_p2_rating.mu - player2_rating.mu
            
            await ctx.send(
                f"**Match Results Updated!**\n"
                f" Winner: <@{player2_id}> | New Rating: {new_p2_rating.mu:.2f} (+{p2_change:.2f})\n"
                f" Loser: <@{player1_id}> | New Rating: {new_p1_rating.mu:.2f} ({p1_change:.2f})\n\n"
                f"*This channel will close in 10 seconds...*"
            )
            
            del active_matches[ctx.channel.id]
            checked = True
            await asyncio.sleep(10)
            await ctx.channel.delete()
            
        else:
            await ctx.send("i have no clue who youre talkin about. speak up.")
            
    except asyncio.TimeoutError:
        await ctx.send("ya takin to long. get my attention again when you're ready")



bot.run(token, log_handler=handler, log_level=logging.DEBUG)

client = discord.Client(intents=intents)
