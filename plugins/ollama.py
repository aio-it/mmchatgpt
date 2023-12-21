from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader

class Ollama(PluginLoader):
    REDIS_PREFIX = "ollama_"
    DEFAULT_MODEL = "mistral"
    URL= "http://localhost:11434/api"
    CHAT_ENDPOINT = "/chat"
    def __init__(self):
        super().__init__()
    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
        if self.redis.get(self.REDIS_PREFIX + "model") is None:
            self.redis.set(self.REDIS_PREFIX + "model", "mistral")

  
    @listen_to(r"^\.ollama model set ([\s\S]*)")
    async def ollama_model_set(self, message: Message, model: str):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"model set to: {model}")
    @listen_to(r"^\.ollama model get")
    async def ollama_model_get(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"model: {self.redis.get(self.REDIS_PREFIX + 'model')}")