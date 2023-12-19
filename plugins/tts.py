from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from plugins.common import Helper
from plugins.users import Users
from environs import Env
from typing import Tuple, List
import pyttsx3
import asyncio
from redis_rate_limit import RateLimit, TooManyRequests


class TTS(Plugin):
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

    @listen_to(r"^\.drtts ([\s\S]*)")
    async def drtts(self, message: Message, text: str):
        """use the dr tts website to get an audio clip from text"""
        if self.users.is_user(message.sender_name):
            try:
                with RateLimit(
                    resource="drtts",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    # get the audio from dr tts website https://www.dr.dk/tjenester/tts?text=<text> using the requests module urlencode the text
                    self.helper.add_reaction(message, "speaking_head_in_silhouette")
                    # replace newlines with spaces
                    text = text.replace("\n", " ")
                    urlencoded_text = self.helper.urlencode_text(text)
                    audio_url = (
                        f"https://www.dr.dk/tjenester/tts?text={urlencoded_text}"
                    )
                    # download the audio using the url
                    filename = self.helper.download_file_to_tmp(audio_url, "mp3")
                    # format the link in mattermost markdown
                    msg_txt = f"link: [drtts]({audio_url})"
                    self.helper.remove_reaction(message, "speaking_head_in_silhouette")
                    self.driver.reply_to(message, msg_txt, file_paths=[filename])
                    # delete the audio file
                    self.helper.delete_downloaded_file(filename)
                    await self.helper.log(f"{message.sender_name} used .drtts")

            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")

    async def create_tts_audio(
        self, text: str, filename: str
    ) -> Tuple[List, int, float]:
        loop = asyncio.get_event_loop()
        engine = pyttsx3.init()
        await loop.run_in_executor(None, engine.save_to_file, text, filename)
        await loop.run_in_executor(None, engine.runAndWait)
        voices = engine.getProperty("voices")
        rate = engine.getProperty("rate")
        volume = engine.getProperty("volume")
        return voices, rate, volume

    @listen_to(r"^\.tts ([\s\S]*)")
    async def tts(self, message: Message, text: str):
        if self.users.is_user(message.sender_name):
            try:
                with RateLimit(
                    resource="drtts",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    self.helper.add_reaction(message, "speaking_head_in_silhouette")
                    text = text.replace("\n", " ")
                    filename = self.create_tmp_filename("mp3")
                    voices, rate, volume = await self.create_tts_audio(text, filename)

                    await self.helper.debug(f"voices: {voices}")
                    await self.helper.debug(f"rate: {rate}")
                    await self.helper.debug(f"volume: {volume}")

                    self.driver.reply_to(message, f"tts: {text}", file_paths=[filename])
                    self.helper.remove_reaction(message, "speaking_head_in_silhouette")
                    await self.helper.log(f"{message.sender_name} used .tts")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
