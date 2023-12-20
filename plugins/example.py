from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader

class Example(PluginLoader):
    def __init__(self):
        super().__init__()
    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
    
    @listen_to(r"^\.example ([\s\S]*)")
    async def prototype(self, message: Message, text: str):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"prototype: {text}")