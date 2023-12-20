
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from plugins.common import Helper
from plugins.users import Users
from environs import Env
class PluginLoader(Plugin):
    def __init__(self):
        pass
    def initialize(self,
          driver: Driver,
          plugin_manager: PluginManager,
          settings: Settings
          ):
        self.driver = driver
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.helper = Helper(self.driver)
        self.users = Users(self.driver, self.plugin_manager, self.settings)
        self.helper.slog(f"Plugin initialized {self.__class__.__name__}")
        self.redis = self.helper.redis
