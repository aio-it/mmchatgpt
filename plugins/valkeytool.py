
from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from plugins.base import PluginLoader


class ValkeyTool(PluginLoader):
    @listen_to(r"^\.valkey get ([\s\S]*)")
    async def valkey_get(self, message: Message, key: str):
        """get valkey key"""
        if self.users.is_admin(message.sender_name):
            # find the type of the key
            keytype = self.valkey.type(key)
            if keytype == "string":
                value = self.valkey.get(key)
            elif keytype == "list":
                value = self.valkey.lrange(key, 0, -1)
            elif keytype == "set":
                value = self.valkey.smembers(key)
            elif keytype == "zset":
                value = self.valkey.zrange(key, 0, -1)
            elif keytype == "hash":
                value = self.valkey.hgetall(key)
            else:
                value = "Unknown key type"
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")

    @listen_to(r"^\.valkey set ([\s\S]*) ([\s\S]*)")
    async def valkey_set(self, message: Message, key: str, value: str):
        """set valkey key"""
        if self.users.is_admin(message.sender_name):
            self.valkey.set(key, value)
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")

    # valkey search
    @listen_to(r"^\.valkey search ([\s\S]*)")
    async def valkey_search(self, message: Message, key: str):
        """search valkey key"""
        if self.users.is_admin(message.sender_name):
            keys = self.valkey.keys(key)
            keystxt = ""
            for key in keys:
                # get the type of the key
                keytype = self.valkey.type(key)
                keystxt += f" - {key} ({keytype})\n"
            self.driver.reply_to(message, f"Keys:\n{keystxt}")

    # valkey delete
    @listen_to(r"^\.valkey delete ([\s\S]*)")
    async def valkey_delete(self, message: Message, key: str):
        """delete valkey key"""
        if self.users.is_admin(message.sender_name):
            self.valkey.delete(key)
            self.driver.reply_to(message, f"Deleted: {key}")
