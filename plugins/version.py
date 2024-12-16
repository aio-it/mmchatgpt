from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader

# load env
from environs import Env
import os


class Version(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(
        self, driver: Driver, plugin_manager: PluginManager, settings: Settings
    ):
        super().initialize(driver, plugin_manager, settings)
        self.version = self.get_version_from_file()
        self.source = "https://github.com/aio-it/mmchatgpt"
        self.helper.slog(f"Started. Version {self.version} Source: {self.source}")

    def get_version_from_file(self):
        """get the version of the bot"""
        # check if .git exists if it does return the git version using git describe --tags
        if os.path.exists(".git"):
            import subprocess
            version = subprocess.check_output(["git", "describe", "--tags"]).strip()
            return version.decode("utf-8")
        # open version file
        with open("version") as f:
            version = f.read().strip()
        return version

    @listen_to("^.gpt version$")
    def get_version(self, message: Message):
        """get the version of the bot"""
        return self.driver.reply_to(message,f"Source: {self.source} Version: {self.version}")