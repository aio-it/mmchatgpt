from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
import hibpwned

# load env
from environs import Env


class HIPB(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(
        self, driver: Driver, plugin_manager: PluginManager, settings: Settings
    ):
        super().initialize(driver, plugin_manager, settings)
        # api key from env HIBP_API_KEY
        self.api_key = Env().str("HIBP_API_KEY")
        self.disabled = False
        if not self.api_key:
            self.helper.slog("HIBP_API_KEY not found in .env")
            self.disabled = True

    @listen_to(r"^\.hibp ([\s\S]*)")
    @listen_to(r"^\.haveibeenpwned ([\s\S]*)")
    async def hibp(self, message: Message, text: str):
        """function: Check if an email or password has been pwned using the Have I Been Pwned API"""
        if self.disabled:
            self.driver.reply_to(
                message, "The HIBP API key is not set. Please set it in the .env file"
            )
            return
        # check if the users is an user
        if self.users.is_user(message.sender_name):
            # load the hibpwned module
            hibp = hibpwned.Pwned(text, "hibpwned", self.api_key)
            # search all breaches
            result = hibp.search_all_breaches()
            # if there are breaches
            if result:
                # send the breaches
                self.driver.reply_to(message, result)
            else:
                # if there are no breaches
                self.driver.reply_to(message, "No breaches found")
