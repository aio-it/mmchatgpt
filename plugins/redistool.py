
from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from plugins.base import PluginLoader

class RedisTool(PluginLoader):
    @listen_to(r"^\.redis get ([\s\S]*)")
    async def redis_get(self, message: Message, key: str):
        """get redis key"""
        if self.users.is_admin(message.sender_name):
            # find the type of the key
            keytype = self.redis.type(key)
            if keytype == "string":
                value = self.redis.get(key)
            elif keytype == "list":
                value = self.redis.lrange(key, 0, -1)
            elif keytype == "set":
                value = self.redis.smembers(key)
            elif keytype == "zset":
                value = self.redis.zrange(key, 0, -1)
            elif keytype == "hash":
                value = self.redis.hgetall(key)
            else:
                value = "Unknown key type"
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")

    @listen_to(r"^\.redis set ([\s\S]*) ([\s\S]*)")
    async def redis_set(self, message: Message, key: str, value: str):
        """set redis key"""
        if self.users.is_admin(message.sender_name):
            self.redis.set(key, value)
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")

    # redis search
    @listen_to(r"^\.redis search ([\s\S]*)")
    async def redis_search(self, message: Message, key: str):
        """search redis key"""
        if self.users.is_admin(message.sender_name):
            keys = self.redis.keys(key)
            keystxt = ""
            for key in keys:
                # get the type of the key
                keytype = self.redis.type(key)
                keystxt += f" - {key} ({keytype})\n"
            self.driver.reply_to(message, f"Keys:\n{keystxt}")

    # redis delete
    @listen_to(r"^\.redis delete ([\s\S]*)")
    async def redis_delete(self, message: Message, key: str):
        """delete redis key"""
        if self.users.is_admin(message.sender_name):
            self.redis.delete(key)
            self.driver.reply_to(message, f"Deleted: {key}")