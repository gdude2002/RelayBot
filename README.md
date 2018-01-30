RelayBot is becoming Smithy!
===========================

RelayBot in its current state will no longer be developed. Instead, please head on over to the [Smithy project](https://github.com/gdude2002/Smithy), which will contain all of the features you know and love from RelayBot!

You can sill reach us for support on the [Smithy Discord server](https://discord.gg/ZUVSbah) for individual support, or a chat.

RelayBot
========

RelayBot is a Discord bot designed to relay messages between set channels (including across servers) in as
unobtrusive a way as possible.

For user documentation, please see [the wiki](https://github.com/gdude2002/RelayBot/wiki).

You can also come and chat to us [on Discord](https://discord.gg/w2K2wZT).

---

* Install Python 3.6 or later
* Set up a Virtualenv if you're using this in production
* `python -m pip install -r requirements.txt`
* Copy `config.yml.example` to `config.yml` and fill it out
* `python -m bot`
    * `--debug` for debug-level logging
    * `--no-log-discord` to prevent log messages from being relayed to Discord
        * Note that `DEBUG`-level messages and messages from the `asyncio` logger are never relayed to Discord
