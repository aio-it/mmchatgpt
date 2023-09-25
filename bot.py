#!/usr/bin/env python
"""chatgpt mattermost bot"""
from environs import Env
from mmpy_bot import Bot, Settings
from chatgpt import ChatGPT
env = Env()
log_channel = env.str("MM_BOT_LOG_CHANNEL")
openai_api_key = env.str("OPENAI_API_KEY")
giphy_api_key=env.str("GIPHY_API_KEY") or None
bot = Bot(
    settings=Settings(
        MATTERMOST_URL=env.str("MM_URL"),
        MATTERMOST_PORT=env.int("MM_PORT", 443),
        MATTERMOST_API_PATH=env.str("MM_API_PATH", "/api/v4"),
        BOT_TOKEN=env.str("MM_BOT_TOKEN"),
        BOT_TEAM=env.str("MM_BOT_TEAM"),
        SSL_VERIFY=env.bool("MM_SSL_VERIFY", True),
    ),  # Either specify your settings here or as environment variables.
    # Add your own plugins here.
    plugins=[ChatGPT(openai_api_key, log_channel, giphy_api_key=giphy_api_key)],
)
bot.run()
