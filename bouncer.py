"""
A Discord moderation bot, originally made for the Stardew Valley server
Written by aquova, 2018
https://github.com/aquova/bouncer
"""

import discord, json, sqlite3, datetime

with open('config.json') as config_file:
    cfg = json.load(config_file)

discordKey = str(cfg['discord'])
validInputChannels = cfg['channels']['listening']
logChannel = str(cfg['channels']['log'])
validRoles = cfg['roles']
if cfg['DM'] == "True":
    sendDMs = True
else:
    sendDMs = False

client = discord.Client()

# Create needed database, if doesn't exist
sqlconn = sqlite3.connect('sdv.db')
sqlconn.execute("CREATE TABLE IF NOT EXISTS badeggs (dbid INT PRIMARY KEY, id INT, username TEXT, num INT, date DATE, message TEXT, staff TEXT);")
sqlconn.commit()
sqlconn.close()

warnThreshold = 3

def removeCommand(m):
    tmp = m.split(" ")[2:]
    return " ".join(tmp)

def formatTime(t):
    # Input t is of the form: YYYY-MM-DD HH:MM:SS.SSSSSS
    date = str(t).split(" ")[0]
    pieces = date.split("-")
    # output is of the form DD/MM/YYYY
    european = "{}/{}/{}".format(pieces[2], pieces[1], pieces[0])
    return european

def checkRoles(user):
    if len(validRoles) == 1 and validRoles[0] == "":
        return True
    for role in user.roles:
        for r in validRoles:
            if role.id == r:
                return True
    return False

async def userSearch(u, m):
    if (len(u) == 1):
        sqlconn = sqlite3.connect('sdv.db')
        searchResults = sqlconn.execute("SELECT username, num, date, message, staff FROM badeggs WHERE id=?", [u[0].id]).fetchall()
        sqlconn.commit()
        sqlconn.close()

        if searchResults == []:
            await client.send_message(m.channel, "That user was not found in the database.")
        else:
            out = "That user was found with the following infractions:\n"
            for item in searchResults:
                if item[1] == 0:
                    out += "[{}] **{}** - Banned by {} - {}\n".format(formatTime(item[2]), item[0], item[4], item[3])
                else:
                    out += "[{}] **{}** - Warning #{} by {} - {}\n".format(formatTime(item[2]), item[0], item[1], item[4], item[3])
                if item[1] == warnThreshold:
                    out += "They have received {} warnings, it is recommended that they be banned.\n".format(warnThreshold)
            await client.send_message(m.channel, out)
    else:
        await client.send_message(m.channel, "Please mention only a single user that you wish to search")

async def logUser(u, m, ban):
    if len(u) == 1:
        sqlconn = sqlite3.connect('sdv.db')
        # TODO: This could potentially be a problem if you try to warn again after banning
        if (ban):
            count = 0
        else:
            count = sqlconn.execute("SELECT COUNT(*) FROM badeggs WHERE id=?", [u[0].id]).fetchone()[0] + 1
        globalcount = sqlconn.execute("SELECT COUNT(*) FROM badeggs").fetchone()[0]
        currentTime = datetime.datetime.utcnow()
        params = [globalcount + 1, u[0].id, "{}#{}".format(u[0].name, u[0].discriminator), count, currentTime, removeCommand(m.content), m.author.name]
        sqlconn.execute("INSERT INTO badeggs (dbid, id, username, num, date, message, staff) VALUES (?, ?, ?, ?, ?, ?, ?)", params)
        sqlconn.commit()
        sqlconn.close()
        if ban:
            logMessage = "[{}] **{}#{}** - Banned by {} - {}\n".format(formatTime(currentTime), u[0].name, u[0].discriminator, m.author.name, removeCommand(m.content))
        else:
            logMessage = "[{}] **{}#{}** - Warning #{} by {} - {}\n".format(formatTime(currentTime), u[0].name, u[0].discriminator, count, m.author.name, removeCommand(m.content))
        try:
            await client.send_message(client.get_channel(logChannel), logMessage)
        except discord.errors.InvalidArgument:
            await client.send_message(m.channel, "The logging channel has not been set up in `config.json`. In order to have a visual record, please specify a channel ID.")

        if (count >= warnThreshold and ban == False):
            logMessage += "This user has received {} warnings or more. It is recommened that they be banned.".format(warnThreshold)
        await client.send_message(m.channel, logMessage)
        if ban and sendDMs:
            mes = removeCommand(m.content)
            if mes != "":
                await client.send_message(u[0], "You have been banned from the Stardew Valley server for the following reason: {}. If you have any questions, feel free to DM one of the staff members.".format(mes))
            else:
                await client.send_message(u[0], "You have been banned from the Stardew Valley server for violating one of our rules. If you have any questions, feel free to DM one of the staff members.")
    else:
        await client.send_message(m.channel, "Only mention the user you wish to log.")

async def removeError(u, m):
    if (len(u) == 1):
        sqlconn = sqlite3.connect('sdv.db')
        searchResults = sqlconn.execute("SELECT dbid, username, num, date, message, staff FROM badeggs WHERE id=?", [u[0].id]).fetchall()
        if searchResults == []:
            await client.send_message(m.channel, "That user was not found in the database.")
        else:
            item = searchResults[-1]
            sqlconn.execute("REPLACE INTO badeggs (dbid, id, username, num, date, message, staff) VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL)", [item[0]])
            out = "The following log was deleted:\n"
            if item[2] == 0:
                out += "[{}] **{}** - Banned by {} - {}\n".format(formatTime(item[3]), item[1], item[5], item[4])
            else:
                out += "[{}] **{}** - Warning #{} by {} - {}\n".format(formatTime(item[3]), item[1], item[2], item[5], item[4])
            await client.send_message(m.channel, out)
        sqlconn.commit()
        sqlconn.close()
    else:
        await client.send_message(m.channel, "Please mention only a single user so that I can remove their last log")

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)

    game_object = discord.Game(name="type !help", type=0)
    await client.change_presence(game=game_object)

@client.event
async def on_message(message):
    if message.author.id != client.user.id:
        try:
            if message.channel.id in validInputChannels:
                if message.content.startswith("!search"):
                    if checkRoles(message.author):
                        user = message.mentions
                        await userSearch(user, message)
                elif message.content.startswith("!warn"):
                    if checkRoles(message.author):
                        user = message.mentions
                        await logUser(user, message, False)
                elif message.content.startswith("!banned"):
                    if checkRoles(message.author):
                        user = message.mentions
                        await logUser(user, message, True)
                elif message.content.startswith("!remove"):
                    if checkRoles(message.author):
                        user = message.mentions
                        await removeError(user, message)
                elif message.content.startswith('!help'):
                    helpMes = "Issue a warning: `!warn @USERNAME message`\nLog a ban: `!ban @USERNAME reason`\nSearch for a user: `!search @USERNAME`\nRemove a user's last log: `!remove @USERNAME`"
                    await client.send_message(message.channel, helpMes)
        except discord.errors.HTTPException:
            pass
        except Exception as e:
            await client.send_message(message.channel, "Something has gone wrong. Blame aquova, and tell him this: {}".format(e))

client.run(discordKey)