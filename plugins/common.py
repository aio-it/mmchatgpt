"""shared functions and variables for the project"""
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
import json
import redis
import datetime
import urllib
import requests
import logging
import uuid
import os
from environs import Env
env = Env()
import logging
#logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
class Helper:
    """helper functions"""
    REDIS = redis.Redis(
        host="localhost", port=6379, db=0, decode_responses=True
    )
    def __init__(self, driver, rediss=None, log_channel=None):
        self.driver = driver
        self.redis = self.REDIS
        self.log_channel = log_channel
        env_log_channel = env.str("MM_BOT_LOG_CHANNEL",None)
        if self.log_channel is None and env_log_channel is None:
            self.log_to_channel = False
        elif env_log_channel is not None:
            self.log_to_channel = True
            self.log_channel = env_log_channel
        else:
            self.log_to_channel = True
            self.log_channel = self.log_channel

    def redis_serialize_json(self, msg):
        """serialize a message to json"""
        return json.dumps(msg)

    def redis_deserialize_json(self, msg):
        """deserialize a message from json"""
        if isinstance(msg, list):
            return [json.loads(m) for m in msg]
        return json.loads(msg)
    def print_to_console(self, message: Message):
        """print to console"""
        log.info(f"INFO: {message}")

    async def wall(self, message):
        """send message to all admins"""
        for admin_uid in self.redis.smembers("admins"):
            self.driver.direct_message(receiver_id=admin_uid, message=message)

    async def log(self, message: str):
        """send message to log channel"""
        log.info(f"INFO: {message}")
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, f"[INFO] {message}")
    def slog(self,message: str):
        """sync log"""
        log.info(f"INFO: {message}")
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, f"[INFO] {message}")
    
    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        print(f"DEBUG: {message}")
        log.debug(f"{message}")
        if self.log_to_channel and not private:
            await self.log(f"DEBUG: {message}")
        elif private:
            await self.wall(f"DEBUG: {message}")

    def add_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by adding a reaction to the thread"""
        self.driver.react_to(message, reaction)

    def remove_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by removing the reaction from the thread"""
        self.driver.reactions.delete_reaction(self.driver.user_id, message.id, reaction)
    def urlencode_text(self, text: str) -> str:
        """urlencode the text"""

        return urllib.parse.quote_plus(text)
    def create_tmp_filename(self, extension: str) -> str:
        """create a tmp filename"""

        return f"/tmp/{uuid.uuid4()}.{extension}"

    def download_file(self, url: str, filename: str) -> str:
        """download file from url using requests and return the filename/location"""

        request = requests.get(url, allow_redirects=True)
        with open(filename, "wb") as file:
            file.write(request.content)
        return filename

    def download_file_to_tmp(self, url: str, extension: str) -> str:
        """download file using requests and return the filename/location"""

        filename = self.create_tmp_filename(extension)
        return self.download_file(url, filename)

    def delete_downloaded_file(self, filename: str):
        """delete the downloaded file"""

        if (
            os.path.exists(filename)
            and os.path.isfile(filename)
            and filename.startswith("/tmp")
        ):
            os.remove(filename)