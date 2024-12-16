#!/usr/bin/env python
"""chatgpt mattermost bot"""
from environs import Env
from mmpy_bot import Bot, Settings
from plugins.chatgpt import ChatGPT
from plugins.docker import Docker
from plugins.pushups import Pushups
from plugins.users import Users
from plugins.tts import TTS
from plugins.shellcmds import ShellCmds
from plugins.redistool import RedisTool
from plugins.ollama import Ollama
from plugins.anthropic import Anthropic
from plugins.hibp import HIPB
from plugins.calc import Calc
from plugins.giphy import Giphy
from plugins.ntp import Ntp
from plugins.jira import Jira
from plugins.version import Version
import logging

env = Env()
log_channel = env.str("MM_BOT_LOG_CHANNEL")
debug = env.bool("DEBUG", False)
if debug:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

# read the version file and set the version
with open("version") as f:
    version = f.read().strip()

bot = Bot(
    settings=Settings(
        MATTERMOST_URL=env.str("MM_URL"),
        MATTERMOST_PORT=env.int("MM_PORT", 443),
        MATTERMOST_API_PATH=env.str("MM_API_PATH", "/api/v4"),
        BOT_TOKEN=env.str("MM_BOT_TOKEN"),
        BOT_TEAM=env.str("MM_BOT_TEAM"),
        SSL_VERIFY=env.bool("MM_SSL_VERIFY", True),
        DEBUG=debug,
    ),  # Either specify your settings here or as environment variables.
    # Add your own plugins here.
    plugins=[
        Users(),
        ChatGPT(),
        #        Docker(),
        Anthropic(),
        Pushups(),
        TTS(),
        ShellCmds(),
        RedisTool(),
        # Ollama(),
        HIPB(),
        Calc(),
        Giphy(),
        Ntp(),
        Jira(),
        Version(),
    ],
    enable_logging=True,
)
bot.run()