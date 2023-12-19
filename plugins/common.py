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
from environs import Env
env = Env()

class Helper:
    """helper functions"""
    def __init__(self, driver, rediss=None, log_channel=None):
        self.driver = driver
        if rediss is None:
            self.redis = redis.Redis(
                host="localhost", port=6379, db=0, decode_responses=True
            )
        else:
            self.redis = rediss
        self.log_channel = log_channel
        if self.log_channel is None:
            self.log_to_channel = False
        else:
            self.log_to_channel = True
            self.log_channel = self.log_channel
    def get_redis(self):
        """get redis"""
        return self.redis

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
        print(f"{message.sender_name}: {message.text}")

    async def wall(self, message):
        """send message to all admins"""
        for admin_uid in self.redis.smembers("admins"):
            self.driver.direct_message(receiver_id=admin_uid, message=message)

    async def log(self, message: str):
        """send message to log channel"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)
    def slog(self,message: str):
        """sync log"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)
    
    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        print(f"DEBUG: {message}")
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
