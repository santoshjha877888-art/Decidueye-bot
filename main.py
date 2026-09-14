import os
import re
import io
import asyncio
import random
import datetime
import discord
from discord.ext import commands, tasks

print("1. Initializing Decidueye Bot - Standard Default Balance & Admin Eco Commands...")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=["+", "₹"], intents=intents)

active_giveaways = {}
user_message_timestamps = {}
guild_quest_configs = {}
user_quest_data = {}
user_balances = {}

def get_current_utc_date_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

def get_guild_config(guild_id: int):
    if guild_id not in guild_quest_configs:
        guild_quest_configs[guild_id] = {
            "msg_target": 150,
            "msg_reward": 100000,
            "giveaway_reward": 25000,
            "mission_channel_id": None
        }
    return guild_quest_configs[guild_id]

def check_and_reset_daily(uid: int):
    today = get_current_utc_date_str()
    if uid not in user_quest_data:
        user_quest_data[uid] = {
            "messages": 0,
            "giveaways_entered": 0,
            "last_reset": today,
            "claimed_msg": False,
            "claimed_giveaway": False
        }
    else:
        if user_quest_data[uid]["last_reset"] != today:
            user_quest_data[uid]["messages"] = 0
            user_quest_data[uid]["giveaways_entered"] = 0
            user_quest_data[uid]["last_reset"] = today
            user_quest_data[uid]["claimed_msg"] = False
            user_quest_data[uid]["claimed_giveaway"] = False

@tasks.loop(time=[datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc)])
async def midnight_quest_reset():
    print("[Quests] Midnight UTC reached! Resetting daily quest progress...")
    user_quest_data.clear()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
        
    guild = message.guild
    uid = message.author.id
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    
    if guild:
        config = get_guild_config(guild.id)
        mission_cid = config.get("mission_channel_id")
        if not mission_cid or message.channel.id == mission_cid:
            if uid not in user_message_timestamps:
                user_message_timestamps[uid] = []
            user_message_timestamps[uid].append(now)
            user_message_timestamps[uid] = [t for t in user_message_timestamps[uid] if now - t < 86400]
            
            check_and_reset_daily(uid)
            user_quest_data[uid]["messages"] += 1

            # Auto-Claim & DM check for Message Mission
            u_data = user_quest_data[uid]
            if u_data["messages"] >= config["msg_target"] and not u_data["claimed_msg"]:
                u_data["claimed_msg"] = True
                reward = config["msg_reward"]
                user_balances[uid] = user_balances.get(uid, 0) + reward
                
                try:
                    embed = discord.Embed(
                        title="🎉 Daily Quest Completed!",
                        description=f"You completed the **Send {config['msg_target']} Messages** quest in **{guild.name}**!\n\n💰 **+{reward:,} Pokécoins** have been automatically added to your wallet.",
                        color=discord.Color.green()
                    )
                    await message.author.send(embed=embed)
                except discord.Forbidden:
                    pass  # User DMs closed

    for msg_id, g_data in active_giveaways.items():
        if g_data.get("required_messages", 0) > 0 and not g_data.get("ended", False):
            gw_restricted_cid = g_data.get("restricted_channel_id")
            if gw_restricted_cid and message.channel.id != gw_restricted_cid:
                continue
                
            if message.created_at.timestamp() >= g_data["start_timestamp"]:
                user_msg_counts = g_data.setdefault("user_msg_counts", {})
                user_msg_counts[uid] = user_msg_counts.get(uid, 0) + 1

    await bot.process_commands(message)

class TicketControlView(discord.ui.View):
    def __init__(self, log_channel_id: int = None, winners: list = None):
        super().__init__(timeout=None)
        self.claimed_by = None
        self.log_channel_id = log_channel_id
        self.winners = winners or []

    @discord.ui.button(label="🙋‍♂️ Claim Ticket", style=discord.ButtonStyle.green, custom_id="ticket_claim_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.winners:
            await interaction.response.send_message("❌ Winners cannot claim staff ticket management!", ephemeral=True)
            return

        if self.claimed_by is not None:
            await interaction.response.send_message(f"❌ Ticket already claimed by {self.claimed_by.mention}!", ephemeral=True)
            return

        self.claimed_by = interaction.user
        button.label = f"Claimed by {interaction.user.display_name}"
        button.style = discord.ButtonStyle.grey
        button.disabled = True
        
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"🙋‍♂️ **{interaction.user.mention} has claimed this ticket!**")

    @discord.ui.button(label="🔒 Close & Delete", style=discord.ButtonStyle.red, custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 Closing ticket and exporting message transcript...", ephemeral=False)
        
        messages = []
        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            messages.append(f"[{time_str}] {msg.author} ({msg.author.id}): {msg.clean_content}")
            
        transcript_content = "\n".join(messages)
        transcript_file = discord.File(
            fp=io.BytesIO(transcript_content.encode('utf-8')),
            filename=f"transcript-{interaction.channel.name}.txt"
        )
        
        if self.log_channel_id:
            log_chan = interaction.guild.get_channel(self.log_channel_id)
            if log_chan:
                winner_mentions = ", ".join([w.mention for w in self.winners if w]) or "None"
                
                embed = discord.Embed(
                    title="📄 Ticket Closed & Transcript Generated",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                embed.add_field(name="Ticket Channel", value=interaction.channel.name, inline=True)
                embed.add_field(name="Winner(s)", value=winner_mentions, inline=True)
                embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
                if self.claimed_by:
                    embed.add_field(name="Claimed By", value=self.claimed_by.mention, inline=True)
                
                await log_chan.send(embed=embed, file=transcript_file)

        await asyncio.sleep(3)
        await interaction.channel.delete()

class GiveawayButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎯 Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_decidueye_giveaway_persistent")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            msg_id = interaction.message.id
            
            if msg_id not in active_giveaways or active_giveaways[msg_id].get("ended", False):
                await interaction.followup.send("❌ This giveaway is no longer active.", ephemeral=True)
                return
                
            g_data = active_giveaways[msg_id]
            user_id = interaction.user.id
            
            req_msgs = g_data.get("required_messages", 0)
            if req_msgs > 0:
                user_msgs = g_data.get("user_msg_counts", {}).get(user_id, 0)
                if user_msgs < req_msgs:
                    restricted_cid = g_data.get("restricted_channel_id")
                    channel_text = f" in <#{restricted_cid}>" if restricted_cid else ""
                    await interaction.followup.send(f"❌ You need **{req_msgs} messages**{channel_text} after start! (Current: {user_msgs}/{req_msgs})", ephemeral=True)
                    return

            member = interaction.user
            if interaction.guild and isinstance(member, discord.User):
                member = interaction.guild.get_member(user_id) or member

            bonus_weight = 1
            if hasattr(member, "roles"):
                for role_id, extra_entries in g_data.get("bonus_roles", {}).items():
                    if any(r.id == role_id for r in member.roles):
                        bonus_weight += extra_entries

            user_entries = [uid for uid in g_data["entries"] if uid == user_id]
            if user_entries:
                g_data["entries"] = [uid for uid in g_data["entries"] if uid != user_id]
                await interaction.followup.send("❌ Left the Decidueye giveaway!", ephemeral=True)
            else:
                for _ in range(bonus_weight):
                    g_data["entries"].append(user_id)
                
                # Auto-Claim & DM check for Giveaway Mission
                check_and_reset_daily(user_id)
                u_data = user_quest_data[user_id]
                u_data["giveaways_entered"] += 1
                
                config = get_guild_config(interaction.guild.id)
                if not u_data["claimed_giveaway"]:
                    u_data["claimed_giveaway"] = True
                    reward = config["giveaway_reward"]
                    user_balances[user_id] = user_balances.get(user_id, 0) + reward
                    
                    try:
                        embed = discord.Embed(
                            title="🎉 Daily Quest Completed!",
                            description=f"You completed the **Enter a Giveaway** quest in **{interaction.guild.name}**!\n\n💰 **+{reward:,} Pokécoins** have been automatically added to your wallet.",
                            color=discord.Color.green()
                        )
                        await interaction.user.send(embed=embed)
                    except discord.Forbidden:
                        pass  # User DMs closed

                await interaction.followup.send(f"🎯 Joined Decidueye giveaway successfully! (+{bonus_weight} entries)", ephemeral=True)
            
            unique_users = len(set(g_data["entries"]))
            embed = interaction.message.embeds[0]
            for i, field in enumerate(embed.fields):
                if field.name == "Entries":
                    embed.set_field_at(i, name="Entries", value=str(unique_users), inline=True)
                    break
            
            await interaction.message.edit(embed=embed, view=self)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error processing click: {e}", ephemeral=True)

@tasks.loop(seconds=5)
async def check_giveaways():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    ended_ids = [msg_id for msg_id, data in active_giveaways.items() if now >= data["end_time"] and not data.get("ended", False)]
    for msg_id in ended_ids:
        await terminate_giveaway(msg_id)

async def terminate_giveaway(msg_id):
    if msg_id not in active_giveaways:
        return
    active_giveaways[msg_id]["ended"] = True
    data = active_giveaways.pop(msg_id)
    try:
        channel = bot.get_channel(data["channel_id"])
        if not channel:
            return
        message = await channel.fetch_message(msg_id)
        entries = data["entries"]
        prize = data["prize"]
        winners_count = data.get("winners_count", 1)
        ping_role_id = data.get("ping_role_id")
        log_channel_id = data.get("log_channel_id")
        
        guild = channel.guild
        winners = []
        unique_entries = list(set(entries))
        
        if unique_entries:
            selected_ids = random.sample(unique_entries, min(winners_count, len(unique_entries)))
            winners = [guild.get_member(uid) or await guild.fetch_member(uid) for uid in selected_ids if uid]
            winner_mentions = ", ".join([w.mention for w in winners if w])
        else:
            winner_mentions = "No participants"

        if winners and any(winners):
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            role_ping_str = ""
            if ping_role_id:
                ping_role = guild.get_role(ping_role_id)
                if ping_role:
                    overwrites[ping_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    role_ping_str = f" {ping_role.mention}"

            for w in winners:
                if w:
                    overwrites[w] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            category = discord.utils.get(guild.categories, name="Giveaway Tickets")
            ticket_channel = await guild.create_text_channel(
                name=f"giveaway-winner",
                category=category,
                overwrites=overwrites,
                topic=f"Prize claim ticket for winning: {prize}"
            )
            
            ticket_view = TicketControlView(log_channel_id=log_channel_id, winners=winners)
            await ticket_channel.send(
                f"🎉 Congratulations {winner_mentions}! {role_ping_str}\n"
                f"You won **{prize}**! Staff will assist you shortly to claim your prize.",
                view=ticket_view
            )

        embed = message.embeds[0]
        embed.title = "🏹 GIVEAWAY CONCLUDED 🏹"
        embed.add_field(name="Result", value=f"🏆 Winner(s): {winner_mentions}\nPrize: {prize}", inline=False)
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Ended", style=discord.ButtonStyle.grey, disabled=True))
        await message.edit(content=None, embed=embed, view=view)
        await channel.send(f"🏹 **Decidueye has struck!** Congratulations {winner_mentions} for winning **{prize}**!")
    except Exception as e:
        print(f"Error ending giveaway & creating tickets: {e}")

@bot.event
async def on_ready():
    print(f"3. Decidueye online as {bot.user} - Standard Starting Balance & Economy Active...")
    bot.add_view(GiveawayButton())
    try:
        synced = await bot.tree.sync()
        print(f"Successfully synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Sync failed: {e}")
    if not check_giveaways.is_running():
        check_giveaways.start()
    if not midnight_quest_reset.is_running():
        midnight_quest_reset.start()

# --- PREFIX COMMANDS ---

@bot.command(name="m", aliases=["mission"])
async def prefix_mission(ctx):
    uid = ctx.author.id
    check_and_reset_daily(uid)
    config = get_guild_config(ctx.guild.id)
    u_data = user_quest_data[uid]
    
    msg_count = u_data["messages"]
    target_msgs = config["msg_target"]
    progress_ratio = min(msg_count / target_msgs, 1.0)
    bar = "█" * int(progress_ratio * 15) + "—" * (15 - int(progress_ratio * 15))
    
    msg_status = "✅ Claimed" if u_data["claimed_msg"] else f"`{bar}` {msg_count}/{target_msgs}"
    gw_status = "✅ Claimed" if u_data["claimed_giveaway"] else "❌ Not completed"
    
    embed = discord.Embed(title="✨ Your Daily Quests", color=discord.Color.from_rgb(40, 40, 45))
    embed.description = (
        f"💬 **Send {target_msgs} Messages**\n{msg_status}\nReward: **{config['msg_reward']:,} 🪙**\n\n"
        f"🎉 **Enter Giveaway**\n{gw_status}\nReward: **{config['giveaway_reward']:,} 🪙**"
    )
    await ctx.send(embed=embed)

@bot.command(name="b", aliases=["bal", "balance"])
async def prefix_bal(ctx, member: discord.Member = None):
    target_user = member or ctx.author
    balance = user_balances.get(target_user.id, 0)
    embed = discord.Embed(title="💰 Balance", color=discord.Color.from_rgb(255, 215, 0))
    embed.description = f"{target_user.mention}'s balance: **{balance:,}** 🪙 Pokécoins"
    await ctx.send(embed=embed)

@bot.command(name="start", aliases=["gcreate"])
@commands.has_permissions(administrator=True)
async def prefix_start(ctx, duration_minutes: int, winners: int = 1, *, prize: str = "Giveaway"):
    current_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    end_time = current_time + (duration_minutes * 60)
    
    desc = f"Win **{prize}**!\n\nClick the button below to take your shot!\n\n• **Hosted by:** {ctx.author.mention}\n• **Winners:** {winners}"
    embed = discord.Embed(title="🏹 **DECIDUEYE GIVEAWAY** 🏹", description=desc, color=discord.Color.from_rgb(34, 139, 34))
    embed.add_field(name="Entries", value="0", inline=True)
    embed.add_field(name="Ends At", value=f"<t:{end_time}:R>", inline=True)
    
    view = GiveawayButton()
    msg = await ctx.send(embed=embed, view=view)
    
    active_giveaways[msg.id] = {
        "channel_id": ctx.channel.id,
        "prize": prize,
        "winners_count": winners,
        "required_messages": 0,
        "bonus_roles": {},
        "ping_role_id": None,
        "log_channel_id": None,
        "restricted_channel_id": None,
        "start_timestamp": current_time,
        "end_time": end_time,
        "entries": [],
        "host_id": ctx.author.id,
        "user_msg_counts": {},
        "ended": False
    }
    try:
        await ctx.message.delete()
    except Exception:
        pass

@bot.command(name="end", aliases=["gend"])
@commands.has_permissions(administrator=True)
async def prefix_end(ctx, message_id: int):
    if message_id in active_giveaways:
        await terminate_giveaway(message_id)
        await ctx.send("✅ Giveaway terminated!", delete_after=5)
    else:
        await ctx.send("❌ Active giveaway not found.", delete_after=5)

@bot.command(name="reroll", aliases=["greroll"])
@commands.has_permissions(administrator=True)
async def prefix_reroll(ctx, message_id: int):
    if message_id in active_giveaways and active_giveaways[message_id]["entries"]:
        entries = active_giveaways[message_id]["entries"]
        winner = random.choice(entries)
        await ctx.send(f"🏹 **Spirit Shackle Reroll!** New winner: <@{winner}>!")
    else:
        await ctx.send("❌ Giveaway not found or has no entries.", delete_after=5)

@bot.command(name="edit", aliases=["gedit"])
@commands.has_permissions(administrator=True)
async def prefix_edit(ctx, message_id: int, new_winners: int, *, new_prize: str):
    if message_id in active_giveaways:
        active_giveaways[message_id]["prize"] = new_prize
        active_giveaways[message_id]["winners_count"] = new_winners
        try:
            msg = await ctx.channel.fetch_message(message_id)
            embed = msg.embeds[0]
            embed.description = f"Win **{new_prize}**!\n\nClick the button below!\n\n• **Winners:** {new_winners}"
            await msg.edit(embed=embed)
            await ctx.send("✅ Giveaway successfully updated!", delete_after=5)
        except Exception as e:
            await ctx.send(f"❌ Failed to edit message: {e}", delete_after=5)
    else:
        await ctx.send("❌ Active giveaway not found.", delete_after=5)

# --- SLASH COMMANDS ---

@bot.tree.command(name="add-pc", description="Add Pokécoins to a user's wallet (Admin Only)")
@discord.app_commands.default_permissions(administrator=True)
async def add_pc(interaction: discord.Interaction, member: discord.Member, amount: discord.app_commands.Range[int, 1, 100000000]):
    await interaction.response.defer(ephemeral=True)
    user_balances[member.id] = user_balances.get(member.id, 0) + amount
    new_bal = user_balances[member.id]
    await interaction.followup.send(f"✅ Added **{amount:,} Pokécoins** to {member.mention}! (New Balance: **{new_bal:,} PC**)", ephemeral=True)

@bot.tree.command(name="remove-pc", description="Remove Pokécoins from a user's wallet (Admin Only)")
@discord.app_commands.default_permissions(administrator=True)
async def remove_pc(interaction: discord.Interaction, member: discord.Member, amount: discord.app_commands.Range[int, 1, 100000000]):
    await interaction.response.defer(ephemeral=True)
    current_bal = user_balances.get(member.id, 0)
    user_balances[member.id] = max(0, current_bal - amount)
    new_bal = user_balances[member.id]
    await interaction.followup.send(f"✅ Removed **{amount:,} Pokécoins** from {member.mention}! (New Balance: **{new_bal:,} PC**)", ephemeral=True)

@bot.tree.command(name="setmission", description="Customize daily mission targets and rewards")
@discord.app_commands.default_permissions(administrator=True)
async def setmission(
    interaction: discord.Interaction, 
    message_target: discord.app_commands.Range[int, 1, 1000] = 150, 
    message_reward_pc: discord.app_commands.Range[int, 0, 10000000] = 100000, 
    giveaway_reward_pc: discord.app_commands.Range[int, 0, 10000000] = 25000,
    mission_channel: discord.TextChannel = None
):
    await interaction.response.defer(ephemeral=True)
    config = get_guild_config(interaction.guild.id)
    config["msg_target"] = message_target
    config["msg_reward"] = message_reward_pc
    config["giveaway_reward"] = giveaway_reward_pc
    config["mission_channel_id"] = mission_channel.id if mission_channel else None
    
    await interaction.followup.send("✅ **Mission settings updated successfully!**", ephemeral=True)

@bot.tree.command(name="mission", description="View daily quest progress")
async def mission_slash_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    uid = interaction.user.id
    check_and_reset_daily(uid)
    config = get_guild_config(interaction.guild.id)
    u_data = user_quest_data[uid]
    
    msg_count = u_data["messages"]
    target_msgs = config["msg_target"]
    progress_ratio = min(msg_count / target_msgs, 1.0)
    bar = "█" * int(progress_ratio * 15) + "—" * (15 - int(progress_ratio * 15))
    
    msg_status = "✅ Claimed" if u_data["claimed_msg"] else f"`{bar}` {msg_count}/{target_msgs}"
    gw_status = "✅ Claimed" if u_data["claimed_giveaway"] else "❌ Not completed"
    
    embed = discord.Embed(title="✨ Your Daily Quests", color=discord.Color.from_rgb(40, 40, 45))
    embed.description = (
        f"💬 **Send {target_msgs} Messages**\n{msg_status}\nReward: **{config['msg_reward']:,} 🪙**\n\n"
        f"🎉 **Enter Giveaway**\n{gw_status}\nReward: **{config['giveaway_reward']:,} 🪙**"
    )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="start", description="Start a new Decidueye giveaway with optional settings")
@discord.app_commands.default_permissions(administrator=True)
async def start(
    interaction: discord.Interaction, 
    prize: str, 
    duration_minutes: int, 
    winners: discord.app_commands.Range[int, 1, 50] = 1, 
    required_messages: discord.app_commands.Range[int, 0, 1000] = 0,
    bonus_role_1: discord.Role = None,
    bonus_entries_1: discord.app_commands.Range[int, 0, 10] = 0,
    bonus_role_2: discord.Role = None,
    bonus_entries_2: discord.app_commands.Range[int, 0, 10] = 0,
    bonus_role_3: discord.Role = None,
    bonus_entries_3: discord.app_commands.Range[int, 0, 10] = 0,
    ping_role: discord.Role = None,
    log_channel: discord.TextChannel = None,
    restricted_channel: discord.TextChannel = None,
    host: discord.Member = None,
    image: discord.Attachment = None
):
    await interaction.response.defer(ephemeral=True)
    current_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    end_time = current_time + (duration_minutes * 60)
    giveaway_host = host if host else interaction.user
    
    desc = f"Win **{prize}**!\n\nClick the button below to take your shot!\n\n• **Hosted by:** {giveaway_host.mention}\n• **Winners:** {winners}"
    if required_messages > 0:
        channel_qualifier = f" in {restricted_channel.mention}" if restricted_channel else ""
        desc += f"\n• **Required Messages:** {required_messages} (sent after start{channel_qualifier})"
        
    bonus_roles_dict = {}
    bonus_texts = []
    
    if bonus_role_1 and bonus_entries_1 > 0:
        bonus_roles_dict[bonus_role_1.id] = bonus_entries_1
        bonus_texts.append(f"{bonus_role_1.mention} (+{bonus_entries_1})")
    if bonus_role_2 and bonus_entries_2 > 0:
        bonus_roles_dict[bonus_role_2.id] = bonus_entries_2
        bonus_texts.append(f"{bonus_role_2.mention} (+{bonus_entries_2})")
    if bonus_role_3 and bonus_entries_3 > 0:
        bonus_roles_dict[bonus_role_3.id] = bonus_entries_3
        bonus_texts.append(f"{bonus_role_3.mention} (+{bonus_entries_3})")
        
    if bonus_texts:
        desc += f"\n• **Bonus Roles:** {', '.join(bonus_texts)}"
    if ping_role:
        desc += f"\n• **Role Ping:** {ping_role.mention}"
    if log_channel:
        desc += f"\n• **Log Channel:** {log_channel.mention}"
    if restricted_channel:
        desc += f"\n• **Restricted Channel:** {restricted_channel.mention}"

    embed = discord.Embed(title="🏹 **DECIDUEYE GIVEAWAY** 🏹", description=desc, color=discord.Color.from_rgb(34, 139, 34))
    embed.add_field(name="Entries", value="0", inline=True)
    embed.add_field(name="Ends At", value=f"<t:{end_time}:R>", inline=True)
    
    if image:
        embed.set_image(url=image.url)
    
    view = GiveawayButton()
    msg = await interaction.channel.send(embed=embed, view=view)
    
    active_giveaways[msg.id] = {
        "channel_id": interaction.channel.id,
        "prize": prize,
        "winners_count": winners,
        "required_messages": required_messages,
        "bonus_roles": bonus_roles_dict,
        "ping_role_id": ping_role.id if ping_role else None,
        "log_channel_id": log_channel.id if log_channel else None,
        "restricted_channel_id": restricted_channel.id if restricted_channel else None,
        "start_timestamp": current_time,
        "end_time": end_time,
        "entries": [],
        "host_id": giveaway_host.id,
        "user_msg_counts": {},
        "ended": False
    }
    
    await interaction.followup.send("✅ Decidueye launched a giveaway with all options!", ephemeral=True)

@bot.tree.command(name="edit", description="Edit an active giveaway prize or winners")
@discord.app_commands.default_permissions(administrator=True)
async def edit(interaction: discord.Interaction, message_id: str, new_winners: int = None, new_prize: str = None):
    await interaction.response.defer(ephemeral=True)
    try:
        msg_id = int(message_id)
        if msg_id in active_giveaways:
            if new_prize: 
                active_giveaways[msg_id]["prize"] = new_prize
            if new_winners: 
                active_giveaways[msg_id]["winners_count"] = new_winners
            
            msg = await interaction.channel.fetch_message(msg_id)
            embed = msg.embeds[0]
            embed.description = f"Win **{active_giveaways[msg_id]['prize']}**!\n\n• **Winners:** {active_giveaways[msg_id]['winners_count']}"
            await msg.edit(embed=embed)
            await interaction.followup.send("✅ Giveaway updated successfully!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

@bot.tree.command(name="end", description="Force end an active giveaway")
@discord.app_commands.default_permissions(administrator=True)
async def end(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await terminate_giveaway(int(message_id))
        await interaction.followup.send("Giveaway ended!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

@bot.tree.command(name="reroll", description="Reroll a giveaway winner")
@discord.app_commands.default_permissions(administrator=True)
async def reroll(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    try:
        msg_id = int(message_id)
        if msg_id in active_giveaways and active_giveaways[msg_id]["entries"]:
            winner = random.choice(active_giveaways[msg_id]["entries"])
            await interaction.followup.send("🎯 New winner rerolled!", ephemeral=True)
            await interaction.channel.send(f"🏹 **Spirit Shackle Reroll!** New winner: <@{winner}>!")
        else:
            await interaction.followup.send("❌ Giveaway not found or has no entries.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

bot.run("MTU0ODU1MTAzNzgyMzIyMTgyMA.GZkByL.-nUw9NM7oIl3ezhSRtZ9b6HgHi3tca401bB0bw")

