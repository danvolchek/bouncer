# Bouncer
# Written by aquova, 2018-2020
# https://github.com/aquova/bouncer

import discord, asyncio, os, subprocess, sys
from dataclasses import dataclass
import utils
import commands, config, db
from censor import check_censor, censor_message
from config import LogTypes
from timekeep import Timekeeper
from waiting import AnsweringMachineEntry

debugging = False

# Initialize client and helper classes
client = discord.Client()
db.initialize()
tk = Timekeeper()

FUNC_DICT = {
    "$ban":     [commands.logUser,              LogTypes.BAN],
    "$block":   [commands.blockUser,            True],
    "$clear":   [commands.am.clear_entries,     None],
    "$edit":    [commands.removeError,          True],
    "$help":    [commands.send_help_mes,        None],
    "$kick":    [commands.logUser,              LogTypes.KICK],
    "$note":    [commands.logUser,              LogTypes.NOTE],
    "$remove":  [commands.removeError,          False],
    "$reply":   [commands.reply,                None],
    "$search":  [commands.userSearch,           None],
    "$unban":   [commands.logUser,              LogTypes.UNBAN],
    "$unblock": [commands.blockUser,            False],
    "$uptime":  [tk.uptime,                     None],
    "$waiting": [commands.am.gen_waiting_list,  None],
    "$warn":    [commands.logUser,              LogTypes.WARN],
}

"""
On Ready

Occurs when Discord bot is first brought online
"""
@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)

    # Set Bouncer's activity status
    activity_object = discord.Activity(name="for your reports!", type=discord.ActivityType.watching)
    await client.change_presence(activity=activity_object)

"""
On Member Update

Occurs when a user updates an attribute (nickname, roles)
"""
@client.event
async def on_member_update(before, after):
    # If debugging, don't process
    if config.DEBUG_BOT:
        return

    # If nickname has changed
    if before.nick != after.nick:
        # If they don't have an ending nickname, they reset to their actual username
        if after.nick == None:
            mes = "**{}#{}** has reset their username".format(after.name, after.discriminator)
        else:
            new = after.nick
            mes = "**{}#{}** is now known as `{}`".format(after.name, after.discriminator, after.nick)
        chan = client.get_channel(config.SYS_LOG)
        await chan.send(mes)
    # If role quantity has changed
    elif before.roles != after.roles:
        # Determine role difference, post about it
        if len(before.roles) > len(after.roles):
            missing = [r for r in before.roles if r not in after.roles]
            mes = "**{}#{}** had the role `{}` removed.".format(after.name, after.discriminator, missing[0])
        else:
            newRoles = [r for r in after.roles if r not in before.roles]
            mes = "**{}#{}** had the role `{}` added.".format(after.name, after.discriminator, newRoles[0])
        chan = client.get_channel(config.SYS_LOG)
        await chan.send(mes)

"""
On Member Ban

Occurs when a user is banned
"""
@client.event
async def on_member_ban(server, member):
    # If debugging, don't process
    if config.DEBUG_BOT:
        return

    # We can remove banned user from our answering machine now
    commands.am.remove_entry(member.id)

    # Keep a record of their banning, in case the log is made after they're no longer here
    username = "{}#{}".format(member.name, member.discriminator)
    commands.ul.add_ban(member.id, username)
    mes = "**{} ({})** has been banned.".format(username, member.id)
    chan = client.get_channel(config.SYS_LOG)
    await chan.send(mes)

"""
On Member Remove

Occurs when a user leaves the server
"""
@client.event
async def on_member_remove(member):
    # If debugging, don't process
    if config.DEBUG_BOT:
        return

    # We can remove left users from our answering machine
    commands.am.remove_entry(member.id)

    # Remember that the user has left, in case we want to log after they're gone
    username = "{}#{}".format(member.name, member.discriminator)
    commands.ul.add_ban(member.id, username)
    mes = "**{} ({})** has left".format(username, member.id)
    chan = client.get_channel(config.SYS_LOG)
    await chan.send(mes)

"""
On Raw Reaction Add

Occurs when a reaction is applied to a message
Needs to be raw reaction so it can still get reactions after reboot
"""
@client.event
async def on_raw_reaction_add(payload):
    # If debugging, don't process
    if config.DEBUG_BOT:
        return

    if payload.message_id == config.GATE_MES and payload.emoji.name == config.GATE_EMOJI:
        # Raw payload just returns IDs, so need to iterate through connected servers to get server object
        # Since each bouncer instance will only be in one server, it should be quick.
        # If bouncer becomes general purpose (god forbid), may need to rethink this
        try:
            server = [x for x in client.guilds if x.id == payload.guild_id][0]
            new_role = discord.utils.get(server.roles, id=config.GATE_ROLE)
            target_user = discord.utils.get(server.members, id=payload.user_id)
            await target_user.add_roles(new_role)
        except IndexError as e:
            print("Something has seriously gone wrong.")
            print("Error: {}".format(e))

"""
On Reaction Add

Temporary function to give event roles to users
Must be a staff member using a specific role
"""
@client.event
async def on_reaction_add(reaction, user):
    # NOTE: These should be in config.json, but I can't be bothered, and this
    # is currently planned to be a temporary function anyway
    ROLE_IDS = [281902740785856513, 703675309656113252]
    author = reaction.message.author

    # Only give roles if giver is an admin, and correct emoji was used
    if utils.checkRoles(user, config.VALID_ROLES):
        emoji_name = reaction.emoji if type(reaction.emoji) == str else reaction.emoji.name
        if emoji_name == "SDVpufferspring":
            user_roles = author.roles
            for role in ROLE_IDS:
                new_role = discord.utils.get(author.guild.roles, id=role)
                if new_role != None and new_role not in user_roles:
                    user_roles.append(new_role)

            await author.edit(roles=user_roles)

"""
On Message Delete

Occurs when a user's message is deleted
"""
@client.event
async def on_message_delete(message):
    # Ignore those pesky bots
    if config.DEBUG_BOT or message.author.bot:
        return

    mes = "**{}#{}** deleted in <#{}>: `{}`".format(message.author.name, message.author.discriminator, message.channel.id, message.content)
    # Adds URLs for any attachments that were included in deleted message
    # These will likely become invalid, but it's nice to note them anyway
    if message.attachments != []:
        for item in message.attachments:
            # Break into seperate parts if we're going to cross character limit
            if len(mes) + len(item.url) > config.CHAR_LIMIT:
                await chan.send(mes)
                mes = item.url
            else:
                mes += '\n' + item.url
    chan = client.get_channel(config.SYS_LOG)
    await chan.send(mes)

"""
On Message Edit

Occurs when a user edits a message
"""
@client.event
async def on_message_edit(before, after):
    # Ignore those pesky bots
    if config.DEBUG_BOT or before.author.bot:
        return

    # Prevent embedding of content from triggering the log
    if before.content == after.content:
        return
    try:
        chan = client.get_channel(config.SYS_LOG)
        mes = "**{}#{}** modified in <#{}>: `{}`".format(before.author.name, before.author.discriminator, before.channel.id, before.content)

        # Break into seperate parts if we're going to cross character limit
        if len(mes) + len(after.content) > (config.CHAR_LIMIT + 5):
            await chan.send(mes)
            mes = ""

        mes += " to `{}`".format(after.content)
        await chan.send(mes)
    except discord.errors.HTTPException as e:
        print("Unknown error with editing message. This message was unable to post for this reason: {}\n".format(e))

"""
On Member Join

Occurs when a user joins the server
"""
@client.event
async def on_member_join(member):
    # If debugging, don't process
    if config.DEBUG_BOT:
        return

    mes = "**{}#{} ({})** has joined".format(member.name, member.discriminator, member.id)
    chan = client.get_channel(config.SYS_LOG)
    await chan.send(mes)

"""
On Voice State Update

Occurs when a user joins/leaves an audio channel
"""
@client.event
async def on_voice_state_update(member, before, after):
    # Ignore those pesky bots
    if config.DEBUG_BOT or member.bot:
        return

    if after.channel == None:
        mes = "**{}#{}** has left voice channel {}".format(member.name, member.discriminator, before.channel.name)
        chan = client.get_channel(config.SYS_LOG)
        await chan.send(mes)
    elif before.channel == None:
        mes = "**{}#{}** has joined voice channel {}".format(member.name, member.discriminator, after.channel.name)
        chan = client.get_channel(config.SYS_LOG)
        await chan.send(mes)

"""
On Message

Occurs when a user posts a message
More or less the main function
"""
@client.event
async def on_message(message):
    global debugging

    # Bouncer should not react to its own messages
    if message.author.id == client.user.id:
        return

    try:
        # Allows the owner to enable debug mode
        if message.content.startswith("$debug") and message.author.id == config.OWNER:
            if not config.DEBUG_BOT:
                debugging = not debugging
                await message.channel.send("Debugging {}".format("enabled" if debugging else "disabled"))
                return

        # If debugging, the real bot should ignore the owner
        if debugging and message.author.id == config.OWNER:
            return
        # The debug bot should only ever obey the owner
        # Debug bot doesn't care about debug status. If it's running, it assumes it's debugging
        elif config.DEBUG_BOT and message.author.id != config.OWNER:
            return

        # If bouncer detects a private DM sent to it
        if type(message.channel) is discord.channel.DMChannel:
            ts = message.created_at.strftime('%Y-%m-%d %H:%M:%S')

            # Store who the most recent user was, for $reply ^
            commands.am.set_recent_reply(message.author)

            content = utils.combineMessage(message)
            mes = "**{}#{}** (ID: {}): {}".format(message.author.name, message.author.discriminator, message.author.id, content)

            # If not blocked, send message along to specified mod channel
            if not commands.bu.is_in_blocklist(message.author.id):
                chan = client.get_channel(config.VALID_INPUT_CHANS[0])
                logMes = await chan.send(mes)

                # Lets also add/update them in answering machine
                mes_link = utils.get_mes_link(logMes)
                username = "{}#{}".format(message.author.name, message.author.discriminator)

                mes_entry = AnsweringMachineEntry(username, message.created_at, content, mes_link)
                commands.am.update_entry(message.author.id, mes_entry)
            return

        # Run message against censor
        bad_message = check_censor(message)
        if bad_message:
            await censor_message(message)
            return

        # If a user pings bouncer, log into mod channel
        if client.user in message.mentions:
            content = utils.combineMessage(message)
            mes = "**{}#{}** (ID: {}) pinged me in <#{}>: {}".format(message.author.name, message.author.discriminator, message.author.id, message.channel.id, content)
            mes += "\n{}".format(utils.get_mes_link(message))
            chan = client.get_channel(config.VALID_INPUT_CHANS[0])
            await chan.send(mes)

        # Functions in this category are those where we care that the user has the correct roles, but don't care about which channel they're invoked in
        elif utils.checkRoles(message.author, config.VALID_ROLES) and message.channel.id in config.VALID_INPUT_CHANS:
            cmd = utils.get_command(message.content)
            if cmd in FUNC_DICT:
                func = FUNC_DICT[cmd][0]
                arg = FUNC_DICT[cmd][1]
                await func(message, arg)
            elif cmd == "$graph":
                # Generates two plots to visualize moderation activity trends
                import visualize # Import here to avoid debugger crashing from matplotlib issue
                visualize.genUserPlot()
                visualize.genMonthlyPlot()
                with open("../private/user_plot.png", 'rb') as f:
                    await message.channel.send(file=discord.File(f))

                with open("../private/month_plot.png", 'rb') as f:
                    await message.channel.send(file=discord.File(f))

    except discord.errors.HTTPException as e:
        print("HTTPException: {}", e)
        pass

client.run(config.DISCORD_KEY)
