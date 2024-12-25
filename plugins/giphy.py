from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
from redis_rate_limit import RateLimit, TooManyRequests
import requests
from environs import Env

env = Env()


class Giphy(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(
        self, driver: Driver, plugin_manager: PluginManager, settings: Settings
    ):
        super().initialize(driver, plugin_manager, settings)
        self.giphy_api_key = env.str("GIPHY_API_KEY") or None

    @listen_to(r"^\.gif ([\s\S]*)")
    async def gif(self, message: Message, text: str):
        """fetch gif from giphy api"""
        if self.giphy_api_key is None:
            return
        if self.users.is_user(message.sender_name):
            url = "https://api.giphy.com/v1/gifs/search"
            params = {
                "api_key": self.giphy_api_key,
                "q": text,
                "limit": 1,
                "offset": 0,
                "rating": "g",
                "lang": "en",
            }
            try:
                with RateLimit(
                    resource="gif",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                    valkey_pool=self.valkey_pool,
                ):
                    self.helper.add_reaction(message, "frame_with_picture")
                    # get the gif from giphy api
                    response = requests.get(url, params=params)
                    # get the url from the response
                    gif_url = response.json(
                    )["data"][0]["images"]["original"]["url"]
                    # download the gif using the url
                    filename = self.helper.download_file_to_tmp(gif_url, "gif")
                    # format the gif_url as mattermost markdown
                    # gif_url_txt = f"![gif]({gif_url})"
                    gif_url_txt = ""
                    self.helper.remove_reaction(message, "frame_with_picture")
                    self.driver.reply_to(
                        message, gif_url_txt, file_paths=[filename])
                    # delete the gif file
                    self.helper.delete_downloaded_file(filename)
                    await self.helper.log(
                        f"{message.sender_name} used .gif with {text}"
                    )
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
            except:  # pylint: disable=bare-except
                self.driver.reply_to(message, "Error: Giphy API error")
