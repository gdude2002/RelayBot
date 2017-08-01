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
    "control_chars": ":"
}

log = logging.getLogger("Data")


class DataManager:
    # data = {
    #     server_id: {
    #         config: {}
    #     }
    # }

    data = {}

    # channels = {channel_id: [channel_id]}
    channels = {}

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

