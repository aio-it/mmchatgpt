from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
from redis_rate_limit import RateLimit, TooManyRequests
import requests


class Calc(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(
        self, driver: Driver, plugin_manager: PluginManager, settings: Settings
    ):
        super().initialize(driver, plugin_manager, settings)

    @listen_to(r"^\.calc$")
    async def calc_help(self, message: Message):
        """calc help"""
        if self.users.is_user(message.sender_name):
            # print help message
            messagetxt = (
                f".calc <expression> - use mathjs api to calculate expression\n"
            )
            messagetxt += f"example: .calc 2+2\n"
            messagetxt += f"syntax: https://mathjs.org/docs/expressions/syntax.html\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.calc ?([\s\S]+)")
    async def calc(self, message: Message, text: str):
        """use math module to calc"""
        if self.users.is_user(message.sender_name):
            # convert newline to ;
            text = text.replace("\n", ";")
            try:
                with RateLimit(
                    resource="calc",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                    redis_pool=self.redis_pool,
                ):
                    self.helper.add_reaction(message, "abacus")
                    # replace newlines with spaces
                    text = text.replace("\n", " ")
                    # urlencode the text
                    urlencoded_text = self.helper.urlencode_text(text)
                    # get the result from mathjs api https://api.mathjs.org/v4/?expr=<text>
                    response = requests.get(
                        f"https://api.mathjs.org/v4/?expr={urlencoded_text}"
                    )
                    # format the result in mattermost markdown
                    msg_txt = f"query: {text}\n"
                    msg_txt += f"result: {response.text}"
                    self.helper.remove_reaction(message, "abacus")
                    self.driver.reply_to(message, msg_txt)
                    await self.helper.log(
                        f"{message.sender_name} used .calc with {text}"
                    )
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
