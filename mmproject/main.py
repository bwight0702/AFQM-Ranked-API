from discord import message
from openskill.models import PlackettLuce
import asyncio
import discord
from discord.ext import commands
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
            f" Welcome {p1_member.mention} and {p2_member.mention} to your private match channel!\n"
            f"**Current Ratings:**\n"
            f"👤 {player1_name}: `{p1mu:.2f}`\n"
            f"👤 {player2_name}: `{p2mu:.2f}`\n\n"
            f"Use `!report` in this room once your match finishes."
        )
        
        # 6. QUEUE CLEANUP
        # Delete only the 2 matched individuals from the front of the queue
        del server_queue[:2]
        del queue_names[:2]

        
        

        
        

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
            
            update_player_rating(player1_id, new_p1_rating.mu, new_p1_rating.sigma)
            update_player_rating(player2_id, new_p2_rating.mu, new_p2_rating.sigma)

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
            
            update_player_rating(player1_id, new_p1_rating.mu, new_p1_rating.sigma)
            update_player_rating(player2_id, new_p2_rating.mu, new_p2_rating.sigma)

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
