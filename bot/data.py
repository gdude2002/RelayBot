# coding=utf-8
import logging
import os
import re

from discord import Channel
from ruamel import yaml
from typing import Dict, Any

__author__ = "Gareth Coles"

DATA_REGEX = re.compile(r"[\d]+[\\/]?")

DEFAULT_CONFIG = {
    "control_chars": ";"
}

log = logging.getLogger("Data")


class DataManager:
    # data = {
    #     server_id: {
    #         config: {}
    #     }
    # }

    data = {}

    channels = {}  # {channel_id: [channel_id]}
    groups = {}  # {"group": [channel_id]}
    relays = {}  # {channel_id: [channel_id]}

    def __init__(self):
        if not os.path.exists("data"):
            os.mkdir("data")

    def load(self):
        self.data = {}

        if not os.path.exists("data/channels.yml"):
            self.channels = {}
        else:
            with open("data/channels.yml", "r") as fh:
                self.channels = yaml.safe_load(fh)

        if not os.path.exists("data/groups.yml"):
            self.groups = {}
        else:
            with open("data/groups.yml", "r") as fh:
                self.groups = yaml.safe_load(fh)

        if not os.path.exists("data/relays.yml"):
            self.relays = {}
        else:
            with open("data/relays.yml", "r") as fh:
                self.relays = yaml.safe_load(fh)

        for fn in os.listdir("data/"):
            if os.path.isdir("data/{}".format(fn)):
                if DATA_REGEX.match(fn):
                    if fn[-1] in "\\/":
                        fn = fn[:-1]

                    try:
                        self.load_server(fn)
                    except Exception:
                        log.exception("Failed to load server: {}".format(fn))

    def save(self):
        with open("data/channels.yml", "w") as fh:
            yaml.safe_dump(self.channels, fh)

        with open("data/groups.yml", "w") as fh:
            yaml.safe_dump(self.groups, fh)

        with open("data/relays.yml", "w") as fh:
            yaml.safe_dump(self.relays, fh)

        for server_id, data in self.data.items():
            self.save_server(server_id, data)

    def save_server(self, server_id, data=None):
        if not data:
            data = self.data[server_id]

        try:
            if not os.path.exists("data/{}".format(server_id)):
                self.add_server(server_id)

            with open("data/{}/config.yml".format(server_id), "w") as config_fh:
                yaml.safe_dump(data["config"], config_fh)
        except Exception:
            log.exception("Error saving server '{}'".format(server_id))

    def load_server(self, server_id) -> bool:
        if not os.path.exists("data/{}".format(server_id)):
            return False

        log.debug("Loading server: {}".format(server_id))

        with open("data/{}/config.yml".format(server_id), "r") as fh:
            config = yaml.safe_load(fh)

        self.data[server_id] = {
            "config": config
        }

        return True

    def add_server(self, server_id) -> bool:
        if os.path.exists("data/{}".format(server_id)):
            return False

        os.mkdir("data/{}".format(server_id))

        with open("data/{}/config.yml".format(server_id), "w") as config_fh:
            yaml.safe_dump(DEFAULT_CONFIG, config_fh)

        self.data[server_id] = {
            "config": DEFAULT_CONFIG.copy()
        }

        log.info("Added server: {}".format(server_id))

        return True

    # Convenience functions

    def get_config(self, server) -> Dict[str, Any]:
        return self.data[server.id]["config"]

    def set_config(self, server, key, value):
        self.data[server.id]["config"][key] = value

    def get_server_command_chars(self, server) -> str:
        return self.data[server.id]["config"]["control_chars"]

    def get_all_targets(self, origin):
        if isinstance(origin, Channel):
            origin = origin.id

        linked_channels = set()

        for channel in self.get_targets(origin):
            linked_channels.add(channel)

        for channel in self.get_relays(origin):
            linked_channels.add(channel)

        for channel in self.find_grouped_channels(origin):
            linked_channels.add(channel)

        return linked_channels

    def unlink_all(self, origin):
        if isinstance(origin, Channel):
            origin = origin.id

        self.remove_targets(origin)
        self.remove_relays(origin)
        self.ungroup_channel_entirely(origin)

    # Channel management functions

    def add_target(self, origin, target):
        if isinstance(origin, Channel):
            origin = origin.id
        if isinstance(target, Channel):
            target = target.id

        if origin not in self.channels:
            self.channels[origin] = []

        if target not in self.channels[origin]:
            self.channels[origin].append(target)

        if target not in self.channels:
            self.channels[target] = []

        if origin not in self.channels[target]:
            self.channels[target].append(origin)

        log.info("Channels linked: {} <-> {}".format(origin, target))

    def has_target(self, origin, target):
        if isinstance(origin, Channel):
            origin = origin.id
        if isinstance(target, Channel):
            target = target.id

        if origin not in self.channels:
            return False

        return target in self.channels[origin]

    def get_targets(self, origin):
        if isinstance(origin, Channel):
            origin = origin.id

        if origin not in self.channels:
            return []

        return self.channels[origin]

    def remove_target(self, origin, target):
        if isinstance(origin, Channel):
            origin = origin.id
        if isinstance(target, Channel):
            target = target.id

        if origin in self.channels and target in self.channels[origin]:
            self.channels[origin].remove(target)

            if not self.channels[origin]:
                del self.channels[origin]

        if target in self.channels and origin in self.channels[target]:
            self.channels[target].remove(origin)

            if not self.channels[target]:
                del self.channels[target]

    def remove_targets(self, origin):
        if isinstance(origin, Channel):
            origin = origin.id

        if origin in self.channels:
            del self.channels[origin]

        for channel, targets in list(self.channels.items()):
            if origin in targets:
                self.channels[channel].remove(origin)

                if not self.channels[channel]:
                    del self.channels[channel]

    # Relay management functions

    def add_relay(self, origin, target):
        if isinstance(origin, Channel):
            origin = origin.id
        if isinstance(target, Channel):
            target = target.id

        if origin not in self.relays:
            self.relays[origin] = [target]
        else:
            self.relays[origin].append(target)

        log.info("Channel relayed: {} -> {}".format(origin, target))

    def has_relay(self, origin, target):
        if isinstance(origin, Channel):
            origin = origin.id
        if isinstance(target, Channel):
            target = target.id

        if origin not in self.relays:
            return False
        return target in self.relays[origin]

    def get_relays(self, origin):
        if isinstance(origin, Channel):
            origin = origin.id

        if origin in self.relays:
            return self.relays[origin]

        return []

    def remove_relay(self, origin, target):
        if isinstance(origin, Channel):
            origin = origin.id
        if isinstance(target, Channel):
            target = target.id

        if origin not in self.relays:
            return

        if target not in self.relays[origin]:
            return

        self.relays[origin].remove(target)

    def remove_relays(self, origin):
        if isinstance(origin, Channel):
            origin = origin.id

        if origin in self.relays:
            del self.relays[origin]

    # Group management functions

    def group_channel(self, group, channel):
        if isinstance(channel, Channel):
            channel = channel.id

        if group not in self.groups:
            self.groups[group] = [channel]
        else:
            self.groups[group].append(channel)

        log.info("Channel grouped: {} -> {}".format(group, channel))

    def ungroup_channel(self, group, channel):
        if isinstance(channel, Channel):
            channel = channel.id

        if group not in self.groups:
            return

        if channel not in self.groups[group]:
            return

        self.groups[group].remove(channel)

    def is_grouped_channel(self, group, channel):
        if isinstance(channel, Channel):
            channel = channel.id

        if group not in self.groups:
            return False

        return channel in self.groups[group]

    def find_groups(self, channel):
        if isinstance(channel, Channel):
            channel = channel.id

        groups = set()

        for group, channels in self.groups.items():
            if channel in channels:
                groups.add(group)

        return groups

    def find_grouped_channels(self, channel):
        if isinstance(channel, Channel):
            channel = channel.id

        linked_channels = set()

        for group, channels in self.groups.items():
            if channel in channels:
                [linked_channels.add(x) for x in channels]

        return linked_channels

    def get_channels_for_group(self, group):
        return self.groups.get(group, [])

    def ungroup_channel_entirely(self, channel):
        if isinstance(channel, Channel):
            channel = channel.id

        for group, channels in self.groups.items():
            if channel in channels:
                channels.remove(channel)
