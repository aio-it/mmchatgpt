
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from plugins.helper import Helper
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
        self.redis = self.helper.redis
        self.redis_pool = self.helper.redis_pool
        # load plugins into helper should be moved to a better place
        self.helper.plugins = {}
        for plugin in self.plugin_manager.plugins:
            pname = type(plugin).__name__
            self.helper.plugins[pname.lower()] = plugin
        if 'users' in self.helper.plugins.keys():
            self.users = self.helper.plugins['users']
        else:
            self.users = Users()
            self.users.initialize(self.driver, self.plugin_manager, self.settings)
            self.helper.plugins['users'] = self.users
        # self.helper.slog(f"Plugins loaded: {', '.join(self.helper.plugins.keys())}")
        self.helper.slog(f"initialized.")
