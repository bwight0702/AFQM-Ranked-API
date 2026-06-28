from discord import message
import aiohttp
from openskill.models import PlackettLuce
import asyncio
import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os

API_URL = "fastapi-production-6ed6.up.railway.app" 

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
    await ctx.send(f"hello {ctx.author.mention}!")

@bot.command()
async def assign(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"Matchmaking Role assigned to {ctx.author.mention}")
    else:
        await ctx.send(f"Role not found, Sorry!")

@bot.command()
@commands.has_role(secret_role)
async def matchmaking(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    await ctx.send(f"{role.mention}, {ctx.author.mention} is looking for a game!")

@bot.command()    
async def queue(ctx):
    # 1. Restrict the command strictly to the #queue channel
    if ctx.channel.name != "queue":
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        error_msg = await ctx.send(f"{ctx.author.mention} ❌ You can only use this command in the **#queue** channel!")
        await asyncio.sleep(5)
        await error_msg.delete()
        return

    # 2. Add or remove the user from the temporary local queue lists
    if ctx.author.id not in server_queue:
        queue_names.append(ctx.author.name)
        server_queue.append(ctx.author.id)
        await ctx.send(f"{ctx.author.mention} added to the queue! there are **#{len(server_queue)}** people in the queue.")
    else:
        server_queue.remove(ctx.author.id)
        queue_names.remove(ctx.author.name)
        await ctx.send(f"{ctx.author.mention} removed from the queue! there are **#{len(server_queue)}** people in the queue.")
        
    # 3. Matchmaking trigger (when 2 or more players are waiting)
    if len(server_queue) >= 2:
        await ctx.send(f"**{len(server_queue)}** players are in the queue! Creating your match room...")
        
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
            f" Welcome {p1_member.mention} and {p2_member.mention} to your private match channel!\n"
            f"**Current Ratings:**\n"
            f"👤 {player1_name}: `{p1mu:.2f}`\n"
            f"👤 {player2_name}: `{p2mu:.2f}`\n\n"
            f"Use `!report` in this room once your match finishes."
        )
        
        # Queue cleanup
        del server_queue[:2]
        del queue_names[:2]
        print("[Log] Queue cleared. Matchmaking cycle completed successfully.")

        
        

        
        

@bot.command()
async def leave(ctx):
    if ctx.author.id in server_queue:
        server_queue.remove(ctx.author.id)
        queue_names.remove(ctx.author.name)
        await ctx.send(f"{ctx.author.mention} has left the queue.")
    else:
        await ctx.send(f"{ctx.author.mention}, you are not in the queue.")

@bot.command()
async def report(ctx):
    print("reporting")
    global checked
    checked = False

    # 1. SECURITY & ROOM CHECK
    if ctx.channel.id not in active_matches:
        await ctx.send("❌ This is not a recognized match channel. You can only report match results inside your private match room!")
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

    await ctx.send(f"{ctx.author.mention}, please report the winner of the match by typing their name in the chat.")
    
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
                f"**Match Results Updated!**\n"
                f" Winner: <@{player1_id}> | New Rating: {new_p1_rating.mu:.2f} (+{p1_change:.2f})\n"
                f" Loser: <@{player2_id}> | New Rating: {new_p2_rating.mu:.2f} ({p2_change:.2f})\n\n"
                f"*This channel will close in 10 seconds...*"
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
            await ctx.send("Winner not recognized. Please type one of the player's accurate *usernames*.")
            
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond! Run `!report` again when ready.")



bot.run(token, log_handler=handler, log_level=logging.DEBUG)

client = discord.Client(intents=intents)
