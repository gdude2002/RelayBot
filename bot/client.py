# coding=utf-8
import datetime
import io
import logging
import re
import shlex
import traceback

import asyncio
from typing import Dict, List

import discord

from aiohttp import ServerDisconnectedError, ClientSession
from discord import Embed, Colour, Channel, Server
from discord.http import Route
from ruamel import yaml

from bot.data import DataManager
from bot.utils import line_splitter

log = logging.getLogger("bot")

__author__ = 'Gareth Coles'

LOG_COLOURS = {
    logging.INFO: Colour.blue(),
    logging.WARNING: Colour.gold(),
    logging.ERROR: Colour.red(),
    logging.CRITICAL: Colour.dark_red()
}

CONFIG_KEY_DESCRIPTIONS = {
    "control_chars": "Characters that all commands must be prefixed with. You can always mention me as well instead.",
}

WELCOME_MESSAGE = [
    """
Hello! I was invited to this server to relay messages between channels.

Please use `;link <channel ID> [channel ID]` to specify which channels to relay, or `;help` \
for more information on how I work. 

Note: Management commands require the **Manage Server** permission. Issues can be reported to \
<https://github.com/gdude2002/RelayBot>.

You may relay between servers, but note that you must be present and have **Manage Server** on both.
    """
]

HELP_MESSAGE = """
RelayBot is written and maintained by `gdude2002#5318`. If you've got a problem, please report it to the issue \
tracker at <https://github.com/gdude2002/RelayBot>, or you can join the RelayBot server here: https://discord.gg/w2K2wZT

To read up on how to use me, you should really take a look at our documentation on the wiki. You can find that here: \
<https://github.com/gdude2002/RelayBot/wiki>
"""


class Client(discord.client.Client):
    normal_mention = None
    nick_mention = None

    def __init__(self, *, loop=None, **options):
        super().__init__(loop=loop, **options)

        self.banned_ids = []
        self.webhooks = {}  # {channel_id: webhook_url}

        with open("config.yml", "r") as fh:
            self.config = yaml.safe_load(fh)

        self.data_manager = DataManager()

    def get_token(self):
        return self.config["token"]

    def get_channel_info(self, channel):
        return "`#{}` on `{}`".format(channel.name, channel.server.name)

    def log_to_channel(self, record: logging.LogRecord):
        if not self.config.get("log_channel"):
            return

        channel = self.get_channel(self.config["log_channel"])

        if not channel:
            return

        dt = datetime.datetime.fromtimestamp(
            record.created
        )

        description = record.msg

        if record.exc_info:
            description += "\n\n```{}```".format("\n".join(traceback.format_exception(*record.exc_info)))

        embed = Embed(
            title="{} / {}".format(record.name, record.levelname),
            description=description
        )

        if record.levelno in LOG_COLOURS:
            embed.colour = LOG_COLOURS[record.levelno]

        embed.set_footer(text=dt.strftime("%B %d %Y, %H:%M:%S"))

        async def inner():
            await self.send_message(channel, embed=embed)

        self.loop.call_soon_threadsafe(asyncio.async, inner())

    async def close(self):
        log.info("Shutting down...")
        self.data_manager.save()
        await discord.client.Client.close(self)

    def channels_updated(self, server):
        self.data_manager.save_server(server.id)

    async def on_ready(self):
        log.info("Setting up...")
        self.data_manager.load()

        self.normal_mention = "<@{}>".format(self.user.id)
        self.nick_mention = "<@!{}>".format(self.user.id)

        for server in self.servers:
            self.data_manager.add_server(server.id)

        log.debug("Getting webhooks...")
        for channel_id, targets in list(self.data_manager.channels.items()):
            hooks = 0

            if channel_id not in self.webhooks:
                try:
                    h = await self.ensure_relay_hook(channel_id)
                except Exception:
                    log.exception("Unable to get webhook for channel: `{}`".format(channel_id))
                    self.data_manager.remove_targets(channel_id)
                    self.data_manager.save()
                    continue

                if h is None:  # Doesn't exist
                    log.debug("Channel {} no longer exists.".format(channel_id))
                    self.data_manager.remove_targets(channel_id)
                    self.data_manager.save()
                    continue
                elif h is False:  # No permission
                    await self.send_message(
                        self.get_channel(channel_id),
                        "**Error**: I do not have permission to manage webhooks on this channel.\n\n"
                        "As I require this permission to function, I have entirely unlinked this channel. Please link "
                        "it again when this is fixed."
                    )
                    self.data_manager.remove_targets(channel_id)
                    self.data_manager.save()
                    continue
                else:
                    self.webhooks[channel_id] = h
                    hooks += 1

            log.debug("Got {} webhooks for channel `{}`".format(hooks, channel_id))

        log.info("Ready!")

    async def on_server_join(self, server):
        self.data_manager.add_server(server.id)

        for message in WELCOME_MESSAGE:
            await self.send_message(server.default_channel, content=message)

    async def on_message(self, message):
        if message.server is None:
            return  # DM

        if message.author.id == self.user.id:
            return

        if str(message.author.discriminator) == "0000":
            return

        logger = logging.getLogger(message.server.name)

        user = "{}#{}".format(
            message.author.name, message.author.discriminator
        )

        for line in message.content.split("\n"):
            logger.debug("#{} / {} {}".format(
                message.channel.name,
                user, line
            ))

        chars = self.data_manager.get_server_command_chars(message.server)
        text = None

        if message.content.startswith(chars):  # It's a command
            text = message.content[len(chars):].strip()
        elif message.content.startswith(self.normal_mention):
            text = message.content[len(self.normal_mention):].strip()
        elif message.content.startswith(self.nick_mention):
            text = message.content[len(self.nick_mention):].strip()

        if text:
            if " " in text:
                command, args = text.split(" ", 1)
            else:
                command = text
                args = ""

            args_string = args
            args = shlex.split(args)

            if len(args) > 0:
                data = args[0:]
            else:
                data = []

            log.debug("Command: {}".format(repr(command)))
            log.debug("Args: {}".format(repr(args)))
            log.debug("Args string: {}".format(repr(args_string)))
            log.debug("Data: {}".format(repr(data)))

            if hasattr(self, "command_{}".format(command.replace("-", "_"))):
                await getattr(self, "command_{}".format(command.replace("-", "_")))(data, args_string, message)
        else:  # We should relay this
            await self.do_relay(message)

    def has_permission(self, user):
        if user.server_permissions.manage_server:
            return True
        if int(user.id) == int(self.config["owner_id"]):
            return True

        return False

    async def do_relay(self, message):
        targets = self.data_manager.get_targets(message.channel)
        avatar = message.author.avatar_url

        for channel_id in targets:
            hook = self.webhooks.get(channel_id, None)

            if hook is None:
                await self.send_message(
                    message.channel, "Webhook for channel `{}` is missing - unlinking channel".format(channel_id)
                )
                self.data_manager.remove_targets(channel_id)
                self.data_manager.save()
            else:
                try:
                    if message.content:
                        await self.execute_webhook(
                            hook["id"], hook["token"], wait=True,
                            content=message.content, username=message.author.name,
                            avatar_url=avatar if avatar else None,
                            embeds=message.embeds
                        )
                    elif message.embeds:
                        await self.execute_webhook(
                            hook["id"], hook["token"], wait=True,
                            username=message.author.name,
                            avatar_url=avatar if avatar else None,
                            embeds=message.embeds
                        )

                    if message.attachments:
                        lines = ["__**Attachments**__\n"]

                        for attachment in message.attachments:
                            lines.append("**{}**: {}".format(attachment["filename"], attachment["url"]))

                        for split_line in line_splitter(lines, 2000):
                            await self.execute_webhook(
                                hook["id"], hook["token"], wait=True,
                                content=split_line, username=message.author.name,
                                avatar_url=avatar if avatar else None
                            )
                except Exception as e:
                    await self.send_message(
                        message.channel,
                        "Error executing webhook for channel `{}` - unlinking channel\n\n```{}```".format(channel_id, e)
                    )
                    self.data_manager.remove_targets(channel_id)
                    self.data_manager.save()
                    raise

    # region Commands

    async def command_config(self, data, data_string, message):
        if not self.has_permission(message.author):
            return log.debug("Permission denied")  # No perms

        if len(data) < 1:
            config = self.data_manager.get_config(message.server)

            md = "__**Current configuration**__\n\n"

            for key, value in config.items():
                md += "**{}**: `{}`\n".format(key, value)

            await self.send_message(
                message.channel, "{}\n\n{}".format(message.author.mention, md)
            )

        elif len(data) < 2:
            config = self.data_manager.get_config(message.server)
            key = data[0].lower()

            if key not in config:
                return await self.send_message(
                    message.channel, "{} Unknown key: `{}`".format(message.author.mention, key)
                )

            await self.send_message(
                message.channel, "{} **{}** is set to `{}`\n\n**Info**: {}".format(
                    message.author.mention, key, config[key], CONFIG_KEY_DESCRIPTIONS[key]
                )
            )
        else:
            config = self.data_manager.get_config(message.server)
            key, value = data[0].lower(), data[1]

            if key not in config:
                return await self.send_message(
                    message.channel, "{} Unknown key: `{}`".format(message.author.mention, key)
                )

            self.data_manager.set_config(message.server, key, value)
            self.data_manager.save_server(message.server.id)

            await self.send_message(
                message.channel, "{} **{}** is now set to `{}`".format(
                    message.author.mention, key, value
                )
            )

    async def command_help(self, data, data_string, message):
        await self.send_message(message.channel, "{} {}".format(message.author.mention, HELP_MESSAGE))

    async def command_link(self, data, data_string, message):
        if not self.has_permission(message.author):
            return log.debug("Permission denied")  # No perms

        if len(data) < 1:
            return await self.send_message(message.channel, "Usage: `link <channel ID> [channel ID]`")

        await self.send_typing(message.channel)

        if len(data) < 2:
            left = message.channel
            right = data[0]
        else:
            left, right = data[0], data[1]

            try:
                int(left)
                left = self.get_channel(left)
            except Exception:
                return await self.send_message(
                    message.channel, "Invalid channel ID: `{}`".format(left)
                )

        try:
            int(right)
            right = self.get_channel(right)
        except Exception:
            return await self.send_message(
                message.channel, "Invalid channel ID: `{}`".format(right)
            )

        left_member = left.server.get_member(message.author.id)
        right_member = right.server.get_member(message.author.id)

        if left_member is None:
            return await self.send_message(
                message.channel, "Invalid channel ID: `{}`".format(left.id)
            )
        elif right_member is None:
            return await self.send_message(
                message.channel, "Invalid channel ID: `{}`".format(right.id)
            )

        if left.id == right.id:
            return await self.send_message(message.channel, "You may not link a channel to itself!")

        if self.data_manager.has_target(left, right):
            return await self.send_message(message.channel, "These channels are already linked!")

        if left_member.server_permissions.manage_server and right_member.server_permissions.manage_server:
            try:
                h = await self.ensure_relay_hook(left)

                if not h:
                    await self.send_message(
                        message.channel,
                        "Unable to set up webhook for {}: I don't have the Manage Webhooks "
                        "permission.".format(self.get_channel_info(left))
                    )
                self.webhooks[left.id] = h
            except Exception as e:
                await self.send_message(
                    message.channel,
                    "Unable to set up webhook for channel {}: `{}`".format(self.get_channel_info(left), e)
                )

                raise

            try:
                h = await self.ensure_relay_hook(right)

                if not h:
                    return await self.send_message(
                        message.channel,
                        "Unable to set up webhook for {}: I don't have the Manage Webhooks "
                        "permission.".format(self.get_channel_info(right))
                    )

                self.webhooks[right.id] = h
            except Exception as e:
                return await self.send_message(
                    message.channel,
                    "Unable to set up webhook for {}: `{}`".format(self.get_channel_info(right), e)
                )
            self.data_manager.add_target(left, right)
            self.data_manager.save()

            await self.send_message(
                message.channel,
                "Channels linked successfully."
            )

            if left.id != message.channel.id:
                await self.send_message(
                    left, "This channel has been linked to {} by {}.".format(
                        self.get_channel_info(right), message.author.mention
                    )
                )

            if right.id != message.channel.id:
                await self.send_message(
                    right, "This channel has been linked to {} by {}.".format(
                        self.get_channel_info(left), message.author.mention
                    )
                )
        else:
            return await self.send_message(
                message.channel,
                "Permission denied - you must have `Manage Server` on the server belonging to both channels"
            )

    async def command_relay(self, data, data_string, message):
        if not self.has_permission(message.author):
            return log.debug("Permission denied")  # No perms

        if len(data) < 1:
            return await self.send_message(message.channel, "Usage: `relay <channel ID> [channel ID]`")

        await self.send_typing(message.channel)

        if len(data) < 2:
            left = message.channel
            right = data[0]
        else:
            left, right = data[0], data[1]

            try:
                int(left)
                left = self.get_channel(left)
            except Exception:
                return await self.send_message(
                    message.channel, "Invalid channel ID: `{}`".format(left)
                )

        try:
            int(right)
            right = self.get_channel(right)
        except Exception:
            return await self.send_message(
                message.channel, "Invalid channel ID: `{}`".format(right)
            )

        left_member = left.server.get_member(message.author.id)
        right_member = right.server.get_member(message.author.id)

        if left_member is None:
            return await self.send_message(
                message.channel, "Invalid channel ID: `{}`".format(left.id)
            )
        elif right_member is None:
            return await self.send_message(
                message.channel, "Invalid channel ID: `{}`".format(right.id)
            )

        if left.id == right.id:
            return await self.send_message(message.channel, "You may not relay a channel to itself!")

        if self.data_manager.has_relay(left, right):
            return await self.send_message(message.channel, "These channels are already relayed in that direction!")

        if left_member.server_permissions.manage_server and right_member.server_permissions.manage_server:
            try:
                h = await self.ensure_relay_hook(right)

                if not h:
                    return await self.send_message(
                        message.channel,
                        "Unable to set up webhook for {}: I don't have the Manage Webhooks "
                        "permission.".format(self.get_channel_info(right))
                    )

                self.webhooks[right.id] = h
            except Exception as e:
                return await self.send_message(
                    message.channel,
                    "Unable to set up webhook for {}: `{}`".format(self.get_channel_info(right), e)
                )
            self.data_manager.add_relay(left, right)
            self.data_manager.save()

            await self.send_message(
                message.channel,
                "Channels set to relay successfully."
            )

            if left.id != message.channel.id:
                await self.send_message(
                    left, "This channel has been set to relay to {} by {}.".format(
                        self.get_channel_info(right), message.author.mention
                    )
                )

            if right.id != message.channel.id:
                await self.send_message(
                    right, "This channel has been set to relay to {} by {}.".format(
                        self.get_channel_info(left), message.author.mention
                    )
                )
        else:
            return await self.send_message(
                message.channel,
                "Permission denied - you must have `Manage Server` on the server belonging to both channels"
            )

    async def command_links(self, data, data_string, message):
        if not self.has_permission(message.author):
            return log.debug("Permission denied")  # No perms

        targets = self.data_manager.get_targets(message.channel)

        if not targets:
            return await self.send_message(message.channel, "This channel is not linked to any others.")

        got_lines = []
        unknown_lines = []

        for target in targets:
            channel = self.get_channel(target)

            if not channel:
                unknown_lines.append("• {}".format(target))
            else:
                got_lines.append("• {}".format(self.get_channel_info(channel)))

        if got_lines:
            lines = ["__**Linked channels**__"] + got_lines

            for line in line_splitter(lines, 2000):
                await self.send_message(message.channel, line)
        if unknown_lines:
            lines = ["__**Missing linked channels**__"] + unknown_lines

            for line in line_splitter(lines, 2000):
                await self.send_message(message.channel, line)

    async def command_unlink(self, data, data_string, message):
        if not self.has_permission(message.author):
            return log.debug("Permission denied")  # No perms

        if len(data) < 1:
            return await self.send_message(message.channel, "Usage: `unlink <channel ID> [channel ID]`")

        await self.send_typing(message.channel)

        if len(data) < 2:
            left = message.channel
            right = data[0]
        else:
            left, right = data[0], data[1]

            try:
                int(left)
                left = self.get_channel(left)
            except Exception:
                return await self.send_message(
                    "Invalid channel ID: `{}`".format(left)
                )

        try:
            int(right)
            right = self.get_channel(right)
        except Exception:
            return await self.send_message(
                "Invalid channel ID: `{}`".format(right)
            )

        left_member = left.server.get_member(message.author.id)
        right_member = right.server.get_member(message.author.id)

        if left_member is None:
            return await self.send_message(
                "Invalid channel ID: `{}`".format(left.id)
            )
        elif right_member is None:
            return await self.send_message(
                "Invalid channel ID: `{}`".format(right.id)
            )

        if left_member.server_permissions.manage_server or right_member.server_permissions.manage_server:
            if self.data_manager.has_target(left, right):
                self.data_manager.remove_target(left, right)
                self.data_manager.save()

                await self.send_message(
                    message.channel, "Channels unlinked successfully."
                )

                if left.id != message.channel.id:
                    await self.send_message(
                        left,
                        "This channel has been unlinked from {} by {}.".format(
                            self.get_channel_info(right), message.author.mention
                        )
                    )

                if right.id != message.channel.id:
                    await self.send_message(
                        right,
                        "This channel has been unlinked from {} by {}.".format(
                            self.get_channel_info(left), message.author.mention
                        )
                    )
            else:
                return await self.send_message(
                    message.channel, "These channels are not linked."
                )
        else:
            return await self.send_message(
                message.channel,
                "Permission denied - you must have `Manage Server` on the server belonging to at least one of those "
                "channels."
            )

    async def command_unlink_all(self, data, data_string, message):
        if not self.has_permission(message.author):
            return log.debug("Permission denied")  # No perms

        if len(data) < 1:
            return await self.send_message("Usage: `unlink-all <channel ID>`")

        await self.send_typing(message.channel)

        channel = data[0]

        try:
            int(data[0])
            channel = self.get_channel(data[0])
        except Exception:
            return await self.send_message("Invalid channel ID: {}".format(channel))

        if not channel.server.get_member(message.author.id).server_permissions.manage_server:
            return await self.send_message(
                "Permission denied - you must have `Manage Server` on the server belonging to that channel."
            )

        targets = self.data_manager.get_targets(channel).copy()

        if not targets:
            return await self.send_message("This channel is not linked to any others.")

        self.data_manager.remove_targets(channel)
        self.data_manager.save()

        await self.send_message("Notifying linked channels of removal...")
        await self.send_typing(message.channel)

        for target in targets:
            other = self.get_channel(target)

            if not other:
                continue

            await self.send_message(
                other,
                "This channel has been unlinked from {} by {} (`{}#{}`).".format(
                    self.get_channel_info(channel), message.author.mention,
                    message.author.name, message.author.discriminator
                )
            )

        await self.send_message("Channels unlinked successfully.")

    # endregion

    # region: Webhook management methods

    async def ensure_relay_hook(self, channel):
        if isinstance(channel, str):
            channel = self.get_channel(channel)

        if not channel:
            return None

        ourselves = channel.server.get_member(self.user.id)

        if not channel.permissions_for(ourselves).manage_webhooks:
            if not ourselves.server_permissions.manage_webhooks:
                return False

        hooks = await self.get_channel_webhooks(channel)

        for h in hooks:
            if h["name"] == "_relay":
                return h

        return await self.create_webhook(channel, name="_relay", avatar=None)  # TODO: Avatar

    # endregion

    # region: Webhook HTTP methods

    async def create_webhook(self, channel, name=None, avatar=None) -> Dict:
        if isinstance(channel, Channel):
            channel = channel.id

        r = Route("POST", "/channels/{channel_id}/webhooks".format(channel_id=channel))

        payload = {}

        if name:
            payload["name"] = name

        if avatar:
            payload["avatar"] = avatar

        if not payload:
            raise KeyError("Must include either `name`, `avatar`, or both")

        data = await self.http.request(r, json=payload)
        log.debug("Create Webhook [{}, {}, {}] -> {}".format(channel, name, avatar, data))
        return data

    async def get_channel_webhooks(self, channel) -> List[Dict]:
        if isinstance(channel, Channel):
            channel = channel.id

        r = Route("GET", "/channels/{channel_id}/webhooks".format(channel_id=channel))
        return await self.http.request(r)

    async def get_guild_webhooks(self, guild) -> List[Dict]:
        if isinstance(guild, Server):
            guild = guild.id

        r = Route("GET", "/guilds/{guild_id}/webhooks".format(guild_id=guild))
        return await self.http.request(r)

    async def get_webhook(self, webhook_id, webhook_token) -> Dict:
        if not webhook_token:
            r = Route("GET", "/webhooks/{webhook_id}".format(webhook_id=webhook_id))
        else:
            r = Route("GET", "/webhooks/{webhook_id}/{webhook_token}".format(
                webhook_id=webhook_id, webhook_token=webhook_token
            ))

        return await self.http.request(r)

    async def modify_webhook(self, webhook_id, webhook_token=None, name=None, avatar=None) -> Dict:
        if not webhook_token:
            r = Route("PATCH", "/webhooks/{webhook_id}".format(webhook_id=webhook_id))
        else:
            r = Route("PATCH", "/webhooks/{webhook_id}/{webhook_token}".format(
                webhook_id=webhook_id, webhook_token=webhook_token
            ))

        payload = {}

        if name:
            payload["name"] = name

        if avatar:
            payload["avatar"] = avatar

        if not payload:
            raise KeyError("Must include either `name`, `avatar`, or both")

        return await self.http.request(r, json=payload)

    async def delete_webhook(self, webhook_id, webhook_token=None) -> None:
        if not webhook_token:
            r = Route("DELETE", "/webhooks/{webhook_id}".format(webhook_id=webhook_id))
        else:
            r = Route("DELETE", "/webhooks/{webhook_id}/{webhook_token}".format(
                webhook_id=webhook_id, webhook_token=webhook_token
            ))

        await self.http.request(r)

    async def execute_webhook(self, webhook_id, webhook_token, *, wait=False, content=None, username=None,
                              avatar_url=None, tts=False, file=None, embeds=None) -> None:
        r = Route("POST", "/webhooks/{webhook_id}/{webhook_token}".format(
            webhook_id=webhook_id, webhook_token=webhook_token
        ))

        payload = {
            "content": content,
            "username": username,
            "avatar_url": avatar_url,
            "tts": tts,
            "file": file,
            "embeds": embeds
        }

        for key, value in payload.copy().items():
            if value is None:
                del payload[key]

        found = False

        for key in ["content", "file", "embeds"]:
            if key in payload:
                found = True

        if not found:
            raise KeyError("Must include at least one of `content`, `embeds` or `file`")

        await self.http.request(r, json=payload, params={"wait": str(wait).lower()})

    # endregion

    pass
