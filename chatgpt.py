"""ChatGPT plugin for mmpy_bot"""
import os
import asyncio
import requests
import time
import json
import openai
import redis
import aiohttp.client_exceptions as aiohttp_client_exceptions
import tiktoken
import urllib
import uuid
import pyttsx3
import shlex
import datetime
from typing import Tuple, List


# import serialized_redis
from mmpy_bot import Plugin, listen_to
from mmpy_bot import Message
from redis_rate_limit import RateLimit, TooManyRequests

MODEL = "gpt-3.5-turbo-0301"
ADMINS = []  # put admins in here to prepopulate the redis db
USERS = []  # put users in here to prepopulate the redis db
REDIS_PREPEND = "thread_"
PRICE_PER_TOKEN = 0.002 / 1000
DOLLAR_TO_DKK = 6.5

# Custom Exceptions

# exception for missing api key


class MissingApiKey(Exception):
    """Missing API key exception"""


class ChatGPT(Plugin):
    """mmypy chatgpt plugin"""

    # MODEL = "gpt-3.5-turbo-0301"
    DEFAULT_MODEL = "gpt-4"
    ALLOWED_MODELS = [
        "gpt-3.5-turbo-0301",
        "gpt-3.5-turbo",
        "gpt-4",
        "gpt-4-32k",
    ]
    MAX_TOKENS_PER_MODEL = {
        "gpt-3.5-turbo-0301": 3000,
        "gpt-3.5-turbo": 3000,
        "gpt-4": 7000,
        "gpt-4-32k": 7000,
    }
    ChatGPT_DEFAULTS = {
        "temperature": 1.0,
        "system": """Du er en bot på Mattermost og
                     dit formål er at være hjælpsom
                     og du holder dig ikke tilbage""",
        "top_p": 1.0,
        "moderation": "false",
        "stream": "false",
        "stream_update_delay_ms": 200,
    }

    SETTINGS_KEY = "chatgpt_settings"

    def __init__(self, openai_api_key=None, log_channel=None, **kwargs):
        super().__init__()
        self.name = "ChatGPT"
        self.redis = redis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        if self.redis.scard("admins") <= 0 and len(ADMINS) > 0:
            self.redis.sadd("admins", *ADMINS)
        if self.redis.scard("users") <= 0 and len(USERS) > 0:
            self.redis.sadd("users", *USERS)
        if self.redis.scard("admins") > 0 and len(ADMINS) > 0:
            self.redis.sadd("users", *ADMINS)
        if openai_api_key is None:
            raise MissingApiKey("No OPENAI API key provided")
        if log_channel is None:
            self.log_to_channel = False
        else:
            self.log_to_channel = True
            self.log_channel = log_channel
        openai.api_key = openai_api_key
        if "giphy_api_key" in kwargs:
            self.giphy_api_key = kwargs['giphy_api_key']
        else:
            self.giphy_api_key = None
        # Apply default model to redis if not set and set self.model
        self.model = self.redis.hget(self.SETTINGS_KEY, "model")
        if self.model is None:
            self.redis.hset(self.SETTINGS_KEY, "model", self.DEFAULT_MODEL)
            self.model = self.DEFAULT_MODEL
        # Apply defaults to redis if not set
        for key, value in self.ChatGPT_DEFAULTS.items():
            if self.redis.hget(self.SETTINGS_KEY, key) is None:
                self.redis.hset(self.SETTINGS_KEY, key, value)
        print(f"Allowed users: {self.redis.smembers('users')}")
        print(f"Allowed admins: {self.redis.smembers('admins')}")
        print(f"Allowed models: {self.ALLOWED_MODELS}")

    def return_last_x_messages(self, messages, max_length_in_tokens):
        """return last x messages from list of messages limited by max_length_in_tokens"""
        limited_messages = []
        current_length_in_tokens = 0

        for message_obj in reversed(messages):
            if "content" in message_obj:
                content = message_obj["content"]
                message_length_in_tokens = len(
                    self.string_to_tokens(content, model=self.model)
                )

                if (
                    current_length_in_tokens + message_length_in_tokens
                    <= max_length_in_tokens
                ):
                    current_length_in_tokens += message_length_in_tokens
                    limited_messages.append(message_obj)
                else:
                    break

        return list(reversed(limited_messages))
    @listen_to(r"^\.banlist")
    async def banlist(self, message: Message):
        """list banned users"""
        if self.is_admin(message.sender_name):
            # list banned users
            bans = ""
            for key in self.redis.scan_iter("ban:*"):
                # get time left for ban
                user = key.split(":")[1]
                time = self.redis.get(key)
                timeleft = self.redis.ttl(key)
                if timeleft > 0:
                    # convert seconds to timeleft string
                    timeleft = str(datetime.timedelta(seconds=timeleft))
                    bans += f"{user} ban: {time} days.  left: {timeleft}\n"
                else:
                    bans += f"{user} - permanent\n"
            self.driver.reply_to(message, f"Bans:\n{bans}")
    @listen_to(r"^\.ban ([a-zA-Z0-9_-]+) ?([0-9]?)")
    async def ban(self, message: Message, user, days = 0):
        """ban user"""
        days = int(days)
        if self.is_admin(message.sender_name):
            # check if user is admin
            if self.is_admin(user):
                self.driver.reply_to(message, f"Can't ban admin: {user}")
                return
            #ban user
            if days == 0:
                self.driver.reply_to(message, f"Banned {user} forever")
                self.redis.set(f"ban:{user}", 0)
            else:
                self.driver.reply_to(message, f"Banned {user} for {days} days")
                # set a key in redis with the user and the number of days and autoexpire the key
                self.redis.set(f"ban:{user}", days, ex=days*24*60*60)
            await self.log(f"{message.sender_name} banned {user} for {days} days")
    @listen_to(r"^\.unban ([a-zA-Z0-9_-]+)")
    async def unban(self, message: Message, user):
        """unban user"""
        if self.is_admin(message.sender_name):
            #unban user
            self.driver.reply_to(message, f"Unbanned {user}")
            self.redis.delete(f"ban:{user}")
            await self.log(f"{message.sender_name} unbanned {user}")
    @listen_to(r"^\.s2t ([\s\S]*)")
    async def string_to_tokens_bot(self, message, string):
        """convert a string to tokens"""
        tokens = self.string_to_tokens(string, model=self.model)
        # string_from_tokens = self.tokens_to_string(tokens, model=self.model)
        tokens_to_list_of_bytestrings = self.tokens_to_list_of_strings(tokens)
        tokens_to_list_of_strings = [
            bytestring.decode("utf-8") for bytestring in tokens_to_list_of_bytestrings
        ]
        text = [
            f"string length: {len(string)}",
            f"token count: {len(tokens)}",
            f"token strings: {tokens_to_list_of_strings}",
            f"tokens raw: {tokens}",
        ]
        self.driver.reply_to(message, "\n".join(text))

    def tokens_to_list_of_strings(self, tokens):
        """convert a list of tokens to a list of strings"""
        encoding = tiktoken.encoding_for_model(self.model)
        return [encoding.decode_single_token_bytes(token) for token in tokens]

    def string_to_tokens(self, string, model):
        """function that converts a string to tokens using tiktoken module from openai"""
        enc = tiktoken.encoding_for_model(model)
        return enc.encode(string)

    def tokens_to_string(self, tokens, model):
        """function that converts a string to tokens using tiktoken module from openai"""
        dec = tiktoken.encoding_for_model(model)
        return dec.decode(tokens)

    def get_user_by_username(self, username):
        """get user id from username"""
        return self.driver.users.get_user_by_username(username)

    def get_user_by_user_id(self, user_id):
        """get user id from user_id"""
        return self.driver.users.get_user(user_id)

    def on_start(self):
        """send startup message to all admins"""
        self.log("ChatGPT Bot started")
        self.log("model: " + self.model)

    def on_stop(self):
        """send startup message to all admins"""
        self.log("ChatGPT Bot stopped")

    def print_to_console(self, message: Message):
        """print to console"""
        print(f"{message.sender_name}: {message.text}")

    def is_user(self, username):
        """check if user is user"""
        # check if user is banned
        if self.redis.exists(f"ban:{username}"):
            return False
        return True if username in self.redis.smembers("users") else False

    def is_admin(self, username):
        """check if user is admin"""
        return True if username in self.redis.smembers("admins") else False

    async def wall(self, message):
        """send message to all admins"""
        for admin in self.redis.smembers("admins"):
            self.driver.direct_message(
                receiver_id=self.get_user_by_username(admin)["id"], message=message
            )

    async def log(self, message: str):
        """send message to log channel"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)

    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        print(f"DEBUG: {message}")
        if self.log_to_channel and not private:
            await self.log(f"DEBUG: {message}")
        elif private:
            await self.wall(f"DEBUG: {message}")

    @listen_to(r"^\.usage")
    async def usage(self, message: Message):
        """reply with usage"""
        if self.is_admin(message.sender_name):
            users = self.redis.hkeys("usage")
            for user in users:
                if user == message.sender_name:
                    continue
                usage = self.get_usage_for_user(user)
                self.driver.reply_to(
                    message,
                    f"{user} Usage:\n\tCount: {usage['usage']}\n\tTokens: {usage['tokens']}\n\tPrice: {(float(usage['tokens'])*PRICE_PER_TOKEN)*DOLLAR_TO_DKK}kr",
                    direct=True,
                )

        usage = self.get_usage_for_user(message.sender_name)
        self.driver.reply_to(
            message,
            f"{message.sender_name} Usage:\n\tCount: {usage['usage']}\n\tTokens: {usage['tokens']}\n\tPrice: {(float(usage['tokens'])*PRICE_PER_TOKEN)*DOLLAR_TO_DKK}kr",
        )

    @listen_to(r"^\.users remove (.+)")
    async def users_remove(self, message: Message, username: str):
        """remove user"""
        if self.is_admin(message.sender_name):
            self.redis.srem("users", username)
            self.driver.reply_to(message, f"Removed user: {username}")
            await self.log(f"Removed user: {username}")

    @listen_to(r"^\.users add (.+)")
    async def users_add(self, message: Message, username: str):
        """add user"""
        if self.is_admin(message.sender_name):
            self.redis.sadd("users", username)
            self.driver.reply_to(message, f"Added user: {username}")

    @listen_to(r"^\.users list")
    async def users_list(self, message: Message):
        """list the users"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(
                message, f"Allowed users: {self.redis.smembers('users')}"
            )

    @listen_to(r"^\.admins add (.*)")
    async def admins_add(self, message: Message, username: str):
        """add admin"""
        if self.is_admin(message.sender_name):
            self.redis.sadd("admins", username)
            self.driver.reply_to(message, f"Added admin: {username}")

    @listen_to(r"^\.admins remove (.*)")
    async def admins_remove(self, message: Message, username: str):
        """remove admin"""
        if self.is_admin(message.sender_name):
            self.redis.srem("admins", username)
            self.driver.reply_to(message, f"Removed admin: {username}")

    @listen_to(r"^\.admins list")
    async def admins_list(self, message: Message):
        """list the admins"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(
                message, f"Allowed admins: {self.redis.smembers('admins')}"
            )

    @listen_to(r"^\.models list")
    async def model_list(self, message: Message):
        """list the models"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Allowed models: {self.ALLOWED_MODELS}")

    @listen_to(r"^\.model set (.*)")
    async def model_set(self, message: Message, model: str):
        """set the model"""
        if self.is_admin(message.sender_name):
            if model in self.ALLOWED_MODELS:
                # save model to redis in the settings hash
                self.redis.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Model set to: {model}")
            else:
                self.driver.reply_to(message, f"Model not allowed: {model}")

    @listen_to(r"^\.model get", allowed_users=["lbr"])
    async def model_get(self, message: Message):
        """get the model"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {self.model}")

    @listen_to(r"^\.getchatlog")
    async def getchatlog(self, message: Message):
        """get the chatlog"""
        if self.is_admin(message.sender_name):
            thread_id = message.reply_id
            thread_key = REDIS_PREPEND + thread_id
            chatlog = self.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
            if self.get_chatgpt_setting("system") != "":
                chatlog.insert(
                    0, {"role": "system", "content": self.get_chatgpt_setting("system")}
                )
            chatlogmsg = ""
            for msg in chatlog:
                chatlogmsg += f"{msg['role']}: {msg['content']}\n"
            self.driver.reply_to(message, chatlogmsg)

    @listen_to(r"^\.mkimg ([\s\S]*)")
    async def mkimg(self, message: Message, text: str):
        """use the openai module to get and image from text"""
        if self.is_user(message.sender_name):
            try:
                with RateLimit(
                    resource="mkimg",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    self.add_reaction(message, "frame_with_picture")
                    text = text.replace("\n", " ")
                    response = openai.Image.create(prompt=text, n=1, size="1024x1024")
                    image_url = response["data"][0]["url"]
                    # download the image using the url
                    filename = self.download_file_to_tmp(image_url, "png")
                    # format the image_url as mattermost markdown
                    # image_url_txt = f"![img]({image_url})"
                    # await self.debug(response)
                    # self.driver.reply_to(message, image_url_txt, file_paths=[filename])
                    self.remove_reaction(message, "frame_with_picture")
                    self.driver.reply_to(message, "", file_paths=[filename])
                    self.delete_downloaded_file(filename)
                    await self.log(f"{message.sender_name} used .mkimg")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
            except openai.error.InvalidRequestError as error:
                self.driver.reply_to(message, f"Error: {error}")
            except:  # pylint: disable=bare-except
                self.driver.reply_to(message, "Error: OpenAI API error")

    def create_tmp_filename(self, extension: str) -> str:
        """create a tmp filename"""

        return f"/tmp/{uuid.uuid4()}.{extension}"

    def download_file(self, url: str, filename: str) -> str:
        """download file from url using requests and return the filename/location"""

        request = requests.get(url, allow_redirects=True)
        with open(filename, "wb") as file:
            file.write(request.content)
        return filename

    def download_file_to_tmp(self, url: str, extension: str) -> str:
        """download file using requests and return the filename/location"""

        filename = self.create_tmp_filename(extension)
        return self.download_file(url, filename)

    def delete_downloaded_file(self, filename: str):
        """delete the downloaded file"""

        if (
            os.path.exists(filename)
            and os.path.isfile(filename)
            and filename.startswith("/tmp")
        ):
            os.remove(filename)

    def urlencode_text(self, text: str) -> str:
        """urlencode the text"""

        return urllib.parse.quote_plus(text)
    @listen_to(r"^\.gif ([\s\S]*)")
    async def gif(self, message: Message, text: str):
        """fetch gif from giphy api"""
        if self.giphy_api_key is None:
            return
        if self.is_user(message.sender_name):
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
                ):
                    self.add_reaction(message, "frame_with_picture")
                    # get the gif from giphy api
                    response = requests.get(url, params=params)
                    # get the url from the response
                    gif_url = response.json()["data"][0]["images"]["original"]["url"]
                    # download the gif using the url
                    filename = self.download_file_to_tmp(gif_url, "gif")
                    # format the gif_url as mattermost markdown
                    #gif_url_txt = f"![gif]({gif_url})"
                    gif_url_txt = ""
                    self.remove_reaction(message, "frame_with_picture")
                    self.driver.reply_to(message, gif_url_txt, file_paths=[filename])
                    # delete the gif file
                    self.delete_downloaded_file(filename)
                    await self.log(f"{message.sender_name} used .gif with {text}")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
            except:  # pylint: disable=bare-except
                self.driver.reply_to(message, "Error: Giphy API error")

    @listen_to(r"^\.calc$")
    async def calc_help(self, message: Message):
        """calc help"""
        if self.is_user(message.sender_name):
            #print help message
            messagetxt = f".calc <expression> - use mathjs api to calculate expression\n"
            messagetxt += f"example: .calc 2+2\n"
            messagetxt += f"syntax: https://mathjs.org/docs/expressions/syntax.html\n"
            self.driver.reply_to(message, messagetxt)
    @listen_to(r"^\.calc ?([\s\S]+)")
    async def calc(self, message: Message, text: str):
        """use math module to calc"""
        if self.is_user(message.sender_name):
            #convert newline to ;
            text = text.replace("\n", ";")
            try:
                with RateLimit(
                    resource="calc",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    self.add_reaction(message, "abacus")
                    # replace newlines with spaces
                    text = text.replace("\n", " ")
                    # urlencode the text
                    urlencoded_text = self.urlencode_text(text)
                    # get the result from mathjs api https://api.mathjs.org/v4/?expr=<text>
                    response = requests.get(
                        f"https://api.mathjs.org/v4/?expr={urlencoded_text}"
                    )
                    # format the result in mattermost markdown
                    msg_txt = f"query: {text}\n"
                    msg_txt += f"result: {response.text}"
                    self.remove_reaction(message, "abacus")
                    self.driver.reply_to(message, msg_txt)
                    await self.log(f"{message.sender_name} used .calc with {text}")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
    @listen_to(r"^\.redis get ([\s\S]*)")
    async def redis_get(self, message: Message, key: str):
        """get redis key"""
        if self.is_admin(message.sender_name):
            # find the type of the key
            keytype = self.redis.type(key)
            if keytype == "string":
                value = self.redis.get(key)
            elif keytype == "list":
                value = self.redis.lrange(key, 0, -1)
            elif keytype == "set":
                value = self.redis.smembers(key)
            elif keytype == "zset":
                value = self.redis.zrange(key, 0, -1)
            elif keytype == "hash":
                value = self.redis.hgetall(key)
            else:
                value = "Unknown key type"
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")
    @listen_to(r"^\.redis set ([\s\S]*) ([\s\S]*)")
    async def redis_set(self, message: Message, key: str, value: str):
        """set redis key"""
        if self.is_admin(message.sender_name):
            self.redis.set(key, value)
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")
    #redis search
    @listen_to(r"^\.redis search ([\s\S]*)")
    async def redis_search(self, message: Message, key: str):
        """search redis key"""
        if self.is_admin(message.sender_name):
            keys = self.redis.keys(key)
            keystxt = ""
            for key in keys:
                #get the type of the key
                keytype = self.redis.type(key)
                keystxt += f" - {key} ({keytype})\n"
            self.driver.reply_to(message, f"Keys:\n{keystxt}")
    #redis delete
    @listen_to(r"^\.redis delete ([\s\S]*)")
    async def redis_delete(self, message: Message, key: str):
        """delete redis key"""
        if self.is_admin(message.sender_name):
            self.redis.delete(key)
            self.driver.reply_to(message, f"Deleted: {key}")
    @listen_to(r"^\.drtts ([\s\S]*)")
    async def drtts(self, message: Message, text: str):
        """use the dr tts website to get an audio clip from text"""

        if self.is_user(message.sender_name):
            try:
                with RateLimit(
                    resource="drtts",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    # get the audio from dr tts website https://www.dr.dk/tjenester/tts?text=<text> using the requests module urlencode the text
                    self.add_reaction(message, "speaking_head_in_silhouette")
                    # replace newlines with spaces
                    text = text.replace("\n", " ")
                    urlencoded_text = self.urlencode_text(text)
                    audio_url = (
                        f"https://www.dr.dk/tjenester/tts?text={urlencoded_text}"
                    )
                    # download the audio using the url
                    filename = self.download_file_to_tmp(audio_url, "mp3")
                    # format the link in mattermost markdown
                    msg_txt = f"link: [drtts]({audio_url})"
                    self.remove_reaction(message, "speaking_head_in_silhouette")
                    self.driver.reply_to(message, msg_txt, file_paths=[filename])
                    # delete the audio file
                    self.delete_downloaded_file(filename)
                    await self.log(f"{message.sender_name} used .drtts")

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
        if self.is_user(message.sender_name):
            try:
                with RateLimit(
                    resource="drtts",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    self.add_reaction(message, "speaking_head_in_silhouette")
                    text = text.replace("\n", " ")
                    filename = self.create_tmp_filename("mp3")
                    voices, rate, volume = await self.create_tts_audio(text, filename)

                    await self.debug(f"voices: {voices}")
                    await self.debug(f"rate: {rate}")
                    await self.debug(f"volume: {volume}")

                    self.driver.reply_to(message, f"tts: {text}", file_paths=[filename])
                    self.remove_reaction(message, "speaking_head_in_silhouette")
                    await self.log(f"{message.sender_name} used .tts")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")

    @listen_to(r"^\.set chatgpt ([a-zA-Z0-9_-]+) (.*)")
    async def set_chatgpt(self, message: Message, key: str, value: str):
        """set the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.debug(f"set_chatgpt {key} {value}")
        if self.is_admin(message.sender_name):
            self.redis.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.reset chatgpt ([a-zA-Z0-9_-]+)")
    async def reset_chatgpt(self, message: Message, key: str):
        """reset the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        if self.is_admin(message.sender_name) and key in self.ChatGPT_DEFAULTS:
            value = self.ChatGPT_DEFAULTS[key]
            await self.debug(f"reset_chatgpt {key} {value}")
            self.redis.hset(settings_key, key, self.ChatGPT_DEFAULTS[key])
            self.redis.hdel(settings_key, key)
            self.driver.reply_to(message, f"Reset {key} to {value}")

    @listen_to(r"^\.get chatgpt ([a-zA-Z0-9_-])")
    async def get_chatgpt(self, message: Message, key: str):
        """get the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.debug(f"get_chatgpt {key}")
        if self.is_admin(message.sender_name):
            value = self.redis.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.get chatgpt")
    async def get_chatgpt_all(self, message: Message):
        """get all the chatgpt keys"""
        settings_key = self.SETTINGS_KEY
        await self.debug("get_chatgpt_all")
        if self.is_admin(message.sender_name):
            for key in self.redis.hkeys(settings_key):
                if key in self.ChatGPT_DEFAULTS:
                    self.driver.reply_to(
                        message, f"{key}: {self.redis.hget(settings_key, key)}"
                    )
                else:
                    # key not in defaults, delete it. unsupported key
                    self.redis.hdel(settings_key, key)

    def get_chatgpt_setting(self, key: str):
        """get the chatgpt key setting"""
        settings_key = self.SETTINGS_KEY
        value = self.redis.hget(settings_key, key)
        if value is None and key in self.ChatGPT_DEFAULTS:
            value = self.ChatGPT_DEFAULTS[key]
        return value

    def add_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by adding a reaction to the thread"""
        self.driver.react_to(message, reaction)

    def remove_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by removing the reaction from the thread"""
        self.driver.reactions.delete_reaction(self.driver.user_id, message.id, reaction)
    def nohl(self, user):
        """prevent highlighting the user by adding a zero width space to the username after the first letter"""
        return user[0] + "\u200B" + user[1:]
    
    @listen_to(r"^\.pushups$")
    @listen_to(r"^\.pushups help$")
    async def pushups_helps(self, message: Message):
        """pushups scores for all users"""
        if self.is_user(message.sender_name):
            #print help message
            messagetxt = f".pushups <number> - add pushups for own user\n"
            messagetxt += f".pushups add <number> - add pushups for own user\n"
            messagetxt += f".pushups sub <number> - substract pushups for own user for today and total\n"
            messagetxt += f".pushups top5 - top 5 pushups scores\n"
            messagetxt += f".pushups scores - scores for all users\n"
            messagetxt += f".pushups score - score for own user\n"
            messagetxt += f".pushups reset <user> - reset pushups for user (admin-only)\n"
            self.driver.reply_to(message, messagetxt)
    @listen_to(r"^.pushups top5")
    async def pushups_top5(self, message: Message):
        """pushups scores for all users"""
        if self.is_user(message.sender_name):
            #print help message
            messagetxt = f"Top 5 pushups scores :weight_lifter:\n"
            #get top 5
            scores = {}
            for key in self.redis.scan_iter("pushupsdaily:*"):
                user = key.split(":")[1]
                score = int(self.redis.get(key))
                if user in scores:
                    scores[user] += score
                else:
                    scores[user] = score

            top5 = []
            for user, score in scores.items():
                top5.append((user, score))
            top5.sort(key=lambda x: x[1], reverse=True)
            for i in range(5):
                if i < len(top5):
                    messagetxt += f"{self.nohl(top5[i][0])}: {top5[i][1]}\n"
            self.driver.reply_to(message, messagetxt)
    @listen_to(r"^\.pushups reset ([a-zA-Z0-9_-]+)")
    async def pushups_reset(self, message: Message, user):
        """pushups reset for user"""
        if self.is_admin(message.sender_name):
            #reset pushups for user
            for key in self.redis.scan_iter(f"pushupsdaily:{user}:*"):
                self.redis.delete(key)
            for key in self.redis.scan_iter(f"pushupstotal:{user}"):
                self.redis.delete(key)
            messagetxt = f"{user} pushups reset"
            self.driver.reply_to(message, messagetxt)
            await self.log(messagetxt)

    async def pushups_return_score_string(self, user):
        """return score string for user"""
        #get total pushups
        total = 0
        for key in self.redis.scan_iter(f"pushupsdaily:{user}:*"):
            total += int(self.redis.get(key))
        #get today pushups
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_key = f"pushupsdaily:{user}:{today}"
        today_pushups = int(self.redis.get(today_key))
        return f"{user} has {today_pushups} pushups today and {total} pushups total"
    
    @listen_to(r"^\.pushups sub ([0-9]+)") # pushups
    async def pushups_sub(self, message: Message, pushups_sub):
        """pushups substract"""
        if self.is_user(message.sender_name):
            pushups_sub = int(pushups_sub)
            messagetxt = f"{message.sender_name} substracted {pushups_sub} pushups\n"
            await self.log(messagetxt)
            #store pushups in redis per day
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            key = f"pushupsdaily:{message.sender_name}:{today}"
            self.redis.decr(key, pushups_sub)
            pushups_today = self.redis.get(key)
            messagetxt += f"{message.sender_name} has {pushups_today} pushups today\n"
            #store pushups in redis total
            key = f"pushupstotal:{message.sender_name}"
            self.redis.decr(key, pushups_sub)
            pushups_total = self.redis.get(key)
            messagetxt += f"{message.sender_name} has {pushups_total} pushups total\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups ([0-9]+)") # pushups
    @listen_to(r"^\.pushups add ([0-9]+)") # pushups
    async def pushups_add(self, message: Message, pushups_add):
        """pushups"""
        if self.is_user(message.sender_name):
            pushups_add = int(pushups_add)
            messagetxt = f"{message.sender_name} did {pushups_add} pushups\n"
            await self.log(f"{message.sender_name} did {pushups_add} pushups")
            #store pushups in redis per day
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            key = f"pushupsdaily:{message.sender_name}:{today}"
            self.redis.incr(key, pushups_add)
            pushups = self.redis.get(key)
            messagetxt += f"{message.sender_name} has done {pushups} pushups today\n"
            #store pushups in redis per user
            key = f"pushupstotal:{message.sender_name}"
            self.redis.incr(key, pushups_add)
            pushups = self.redis.get(key)
            messagetxt += f"{message.sender_name} has done {pushups} pushups total\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups scores$")
    async def pushups_scores(self, message: Message):
        """pushups scores for all users"""
        if self.is_user(message.sender_name):
            #get pushups in redis per user
            keys = self.redis.keys("pushupstotal:*")
            messagetxt = ""
            for key in keys:
                pushups = self.redis.get(key)
                key = key.split(":")[1]
                messagetxt += f"{key} has done {pushups} pushups total\n"
            self.driver.reply_to(message, messagetxt)
            
    @listen_to(r"^\.pushups score$")
    async def pushups_score(self, message: Message):
        """pushups score"""
        if self.is_user(message.sender_name):
            #get pushups for last 7 days and print them and a sum of those 7 days and a total
            messagetxt = ""
            today = datetime.datetime.now()
            totals_for_last_7_days = 0
            for i in range(7):
                day = today - datetime.timedelta(days=i)
                day = day.strftime("%Y-%m-%d")
                key = f"pushupsdaily:{message.sender_name}:{day}"
                pushups = self.redis.get(key)
                if pushups is None:
                    pushups = 0
                totals_for_last_7_days += int(pushups)
                messagetxt += f"{day}: {pushups}\n"
            # reverse the lines
            messagetxt = messagetxt.split("\n")
            messagetxt = messagetxt[::-1]
            messagetxt = "\n".join(messagetxt)
            messagetxt += f"\nTotal for last 7 days: {totals_for_last_7_days}\n"
            #get total pushups
            total = 0
            for key in self.redis.scan_iter(f"pushupsdaily:{message.sender_name}:*"):
                total += int(self.redis.get(key))
            messagetxt += f":weight_lifter: Alltime Total: {total}\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(".+", needs_mention=True)
    async def chat(self, message: Message):
        """listen to everything and respond when mentioned"""
        if not self.is_user(message.sender_name):
            return
        # if message.is_direct_message and not self.is_admin(message.sender_name):
        #    return
        if message.text[0] == ".":  # ignore commands
            return
        # set stream using ternary
        stream = True if self.get_chatgpt_setting("stream") == "true" else False
        msg = message.text
        thread_id = message.reply_id
        thread_key = REDIS_PREPEND + thread_id
        # check if thread exists in redis
        messages = []
        if self.redis.exists(thread_key):
            messages = self.append_chatlog(thread_id, {"role": "user", "content": msg})
        else:
            # thread does not exist, fetch all posts in thread
            thread = self.driver.get_post_thread(thread_id)
            for thread_index in thread["order"]:
                thread_post = thread["posts"][thread_index]
                # remove mentions of self
                thread_post["message"] = thread_post["message"].replace(
                    "@" + self.driver.client.username + " ", ""
                )
                # if post is from self, set role to assistant
                if self.driver.client.userid == thread_post["user_id"]:
                    role = "assistant"
                else:
                    # post is from user, set role to user
                    role = "user"

                # self.redis.rpush(thread_key, self.redis_serialize_json(
                #    {"role": role, "content": thread_post['message']}))
                messages = self.append_chatlog(
                    thread_id, {"role": role, "content": thread_post["message"]}
                )
        # add system message
        if self.get_chatgpt_setting("system") != "":
            messages.insert(
                0, {"role": "system", "content": self.get_chatgpt_setting("system")}
            )
        # add thought balloon to show assistant is thinking
        self.driver.react_to(message, "thought_balloon")
        temperature = float(self.get_chatgpt_setting("temperature"))
        top_p = float(self.get_chatgpt_setting("top_p"))
        if not stream:
            try:
                # send async request to openai
                response = await openai.ChatCompletion.acreate(
                    model=self.model,
                    messages=self.return_last_x_messages(
                        messages, self.MAX_TOKENS_PER_MODEL[self.model]
                    ),
                    temperature=temperature,
                    top_p=top_p,
                    stream=stream,
                )
                # check for error in the responses and send error message
                if "error" in response:
                    if "message" in response:
                        self.driver.reply_to(message, f"Error: {response['message']}")
                    else:
                        self.driver.reply_to(message, "Error")
                    # remove thought balloon
                    self.driver.reactions.delete_reaction(
                        self.driver.user_id, message.id, "thought_balloon"
                    )
                    # add x reaction to the message that failed to show error
                    self.driver.react_to(message, "x")
                    return
            except openai.error.InvalidRequestError as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return
            except openai.error.RateLimitError as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return
            # self.debug(response)
            # send response to user
            self.driver.reply_to(
                message,
                f"@{message.sender_name}: {response.choices[0].message.content}",
            )
            # add response to chatlog
            self.append_chatlog(thread_id, response.choices[0].message)
        else:
            # we are streaming baby
            full_message = ""
            post_prefix = f"@{message.sender_name}: "
            # post initial message as a reply and save the message id
            reply_msg_id = self.driver.reply_to(message, full_message)["id"]
            # send async request to openai
            try:
                response = await openai.ChatCompletion.acreate(
                    model=self.model,
                    messages=self.return_last_x_messages(
                        messages, self.MAX_TOKENS_PER_MODEL[self.model]
                    ),
                    temperature=temperature,
                    top_p=top_p,
                    stream=stream,
                )
            except (openai.error.RateLimitError, openai.error.APIError) as error:
                # update the message
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"Error: {error}"}
                )
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return
            # self.debug(response)

            # self.debug(f"reply_msg_id: {reply_msg_id}")
            # get current time and set that as last_update_time
            last_update_time = time.time()
            # get the setting for how often to update the message
            stream_update_delay_ms = float(
                self.get_chatgpt_setting("stream_update_delay_ms")
            )
            try:
                async for chunk in response:
                    # await self.debug(
                    #    f"time since last chunk: {(time.time() - last_chunk_time) * 1000}")
                    # last_chunk_time = time.time()
                    # self.debug(f"chunk: {chunk}")
                    # check for error in the responses and send error message
                    if "error" in chunk:
                        if "message" in chunk:
                            self.driver.reply_to(
                                message, f"Error: {response['message']}"
                            )
                        else:
                            self.driver.reply_to(message, "Error")
                        # remove thought balloon
                        self.driver.reactions.delete_reaction(
                            self.driver.user_id, message.id, "thought_balloon"
                        )
                        # add x reaction to the message that failed to show error
                        self.driver.react_to(message, "x")
                        return

                    # extract the message
                    chunk_message = chunk["choices"][0]["delta"]
                    # if the message has content, add it to the full message
                    if "content" in chunk_message:
                        full_message += chunk_message["content"]
                        # await self.debug((time.time() - last_update_time) * 1000)
                        if (
                            time.time() - last_update_time
                        ) * 1000 > stream_update_delay_ms:
                            # await self.debug("updating message")
                            # update the message
                            self.driver.posts.patch_post(
                                reply_msg_id,
                                {"message": f"{post_prefix}{full_message}"},
                            )
                            # update last_update_time
                            last_update_time = time.time()
                # update the message a final time to make sure we have the full message
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"{post_prefix}{full_message}"}
                )

                # add response to chatlog
                self.append_chatlog(
                    thread_id, {"role": "assistant", "content": full_message}
                )
            except aiohttp_client_exceptions.ClientPayloadError as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return

        # remove thought balloon after successful response
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, "thought_balloon"
        )

        if not stream:
            # add usage for user
            # TODO: add per model usage
            self.add_usage_for_user(
                message.sender_name, response["usage"]["total_tokens"]
            )
            # log usage for user
            await self.log(
                f"User: {message.sender_name} used {response['usage']['total_tokens']} tokens"
            )
        else:
            await self.log(f"User: {message.sender_name} used {self.model}")
    @listen_to(r"^.(de|en)code ([a-zA-Z0-9]+) (.*)")
    async def decode(self, message: Message, method: str, encoding: str, text: str):
        """decode text using a model"""
        supported_encodings = ['base64', 'b64', 'url']
        encode = True if method == "en" else False
        decode = True if method == "de" else False
        if self.is_user(message.sender_name):
            if text == "" or encoding == "" or encoding == "help":
                # print help message
                messagetxt = f".encode <encoding> <text> - encode text using an encoding\n"
                messagetxt += f".decode <encoding> <text> - decode text using an encoding\n"
                messagetxt += f"Supported encodings: {' '.join(supported_encodings)}\n"
                self.driver.reply_to(message, messagetxt)
                return
            # check if encoding is supported
            if encoding not in supported_encodings:
                self.driver.reply_to(message, f"Error: {encoding} not supported. only {supported_encodings} is supported")
                return
            if encoding == "base64" or encoding == "b64":
                try:
                    import base64
                    if decode:
                        text = base64.b64decode(text).decode("utf-8")
                    if encode:
                        text = base64.b64encode(text.encode("utf-8")).decode("utf-8")
                except Exception as error:
                    self.driver.reply_to(message, f"Error: {error}")
                    return
            if encoding == "url":
                try:
                    import urllib.parse
                    if decode:
                        text = urllib.parse.unquote(text)
                    if encode:
                        text = urllib.parse.quote(text)
                except Exception as error:
                    self.driver.reply_to(message, f"Error: {error}")
                    return
            self.driver.reply_to(message, f"Result:\n{text}")
    @listen_to(r"^\.dig (.*)")
    async def dig(self, message: Message, url: str):
        """dig a url"""
        if self.is_admin(message.sender_name):
            if url == "" or url == "help":
                # print help message
                messagetxt = f".dig <url> - dig a url\n"
                self.driver.reply_to(message, messagetxt)
                return
            try:
                self.add_reaction(message, "hourglass")
                import subprocess
                import shlex
                cmd = shlex.split(f"dig {url}")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                output, error = process.communicate()
                output = output.decode("utf-8")
                self.remove_reaction(message, "hourglass")
                self.driver.reply_to(message, f"Result:\n```{output}```")
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                return
    @listen_to(r"^\.ping6 (.*)")
    async def ping6(self, message: Message, url: str):
        """ping6 a ip or hostname"""
        if self.is_admin(message.sender_name):
            if url == "" or url == "help":
                # print help message
                messagetxt = f".ping6 <url> - ping6 a ip or hostname\n"
                self.driver.reply_to(message, messagetxt)
                return
            try:
                self.add_reaction(message, "hourglass")
                import subprocess
                import shlex
                cmd = shlex.split(f"ping6 -c 4 {url}")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                output, error = process.communicate()
                output = output.decode("utf-8")
                self.remove_reaction(message, "hourglass")
                self.driver.reply_to(message, f"Result:\n```{output}```")
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                return
    @listen_to(r"^\.head (.*)")
    async def head(self, message: Message, url: str):
        """curl -i a url"""
        if self.is_admin(message.sender_name):
            if url == "" or url == "help":
                # print help message
                messagetxt = f".head <url> - curl -i a url\n"
                self.driver.reply_to(message, messagetxt)
                return
            try:
                self.add_reaction(message, "hourglass")
                import subprocess
                import shlex
                cmd = shlex.split(f"curl -i {url}")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                output, error = process.communicate()
                output = output.decode("utf-8")
                self.remove_reaction(message, "hourglass")
                self.driver.reply_to(message, f"Result:\n```{output}```")
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                return
    @listen_to(r"^\.ping (.*)")
    async def ping(self, message: Message, url: str):
        """ping a ip or hostname"""
        if self.is_admin(message.sender_name):
            if url == "" or url == "help":
                # print help message
                messagetxt = f".ping <url> - ping a ip or hostname\n"
                self.driver.reply_to(message, messagetxt)
                return
            try:
                self.add_reaction(message, "hourglass")
                import subprocess
                import shlex
                cmd = shlex.split(f"ping -4 -c 4 {url}")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                output, error = process.communicate()
                output = output.decode("utf-8")
                self.remove_reaction(message, "hourglass")
                self.driver.reply_to(message, f"Result:\n```{output}```")
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                return
    @listen_to(r"^\.traceroute (.*)")
    async def traceroute(self, message: Message, url: str):
        """traceroute a ip or hostname"""
        if self.is_admin(message.sender_name):
            if url == "" or url == "help":
                # print help message
                messagetxt = f".traceroute <url> - traceroute a ip or hostname\n"
                self.driver.reply_to(message, messagetxt)
                return
            try:
                self.add_reaction(message, "hourglass")
                import subprocess
                import shlex
                cmd = shlex.split(f"traceroute -4 {url}")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                output, error = process.communicate()
                output = output.decode("utf-8")
                self.remove_reaction(message, "hourglass")
                self.driver.reply_to(message, f"Result:\n```{output}```")
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                return
    @listen_to(r"^\.traceroute6 (.*)")
    async def traceroute6(self, message: Message, url: str):
        """traceroute6 a ip or hostname"""
        if self.is_admin(message.sender_name):
            if url == "" or url == "help":
                # print help message
                messagetxt = f".traceroute6 <url> - traceroute6 a ip or hostname\n"
                self.driver.reply_to(message, messagetxt)
                return
            try:
                self.add_reaction(message, "hourglass")
                import subprocess
                import shlex
                cmd = shlex.split(f"traceroute6 {url}")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                output, error = process.communicate()
                output = output.decode("utf-8")
                self.remove_reaction(message, "hourglass")
                self.driver.reply_to(message, f"Result:\n```{output}```")
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                return

    @listen_to(r"^\.help")
    async def help_function(self, message):
        """help function that returns a list of commands"""
        commands = [
            "### Commands:",
            "---",
            "**.help** - returns this list of commands and usage",
            f"**@{self.driver.client.username} <text>** - returns a response from the chatgpt model (reply to a message to use the context of that thread)",
            "**.mkimg <text>** - text to image using DALL-E2; returns an image",
            "**.drtts <text>** - text to speech using DR TTS; returns an audio file",
            "**.tts <text>** - text to speech using pyttsx3; returns an audio file",
            "**.pushups** - pushups help",
            "**.gif <text>** - text to gif using GIPHY; returns a gif",
            "**.calc <expression>** - calculate an expression using mathjs(lol) api returns the result",
        ]

        commands_admin = [
            "### Admin commands",
            "---" "**.get chatgpt <setting>** - get a setting for chatgpt",
            "**.set chatgpt <setting> <value>** - set a setting for chatgpt",
            "**.model get** - get the model to use for chatgpt",
            "**.model set <model>** - set the model to use for chatgpt",
            "**.reset chatgpt <setting>** - reset a setting for chatgpt",
            "**.users list/add/remove [<username>]** - list/add/remove users",
            "**.admins list/add/remove [<username>]** - list/add/remove admins",
            "**.eval <code>** - run arbitrary python code and return the result to the chat",
            "**.exec <code>** - run arbitrary python code and return the result to the chat",
            "**.getchatlog**- get the chatlog for the current thread",
            "**.s2t <text>**: convert text to token - convert a string to a tokens (for debugging)",
            "**.shell <command>**: run a shell command and return the result to the chat",
            "**.redis search <key>**: search redis for a key",
            "**.redis get <key>**: get a key from redis",
            "**.redis set <key> <value>**: set a key in redis",
            "**.redis del <key>**: delete a key from redis",
            "**.ban <username>** - ban a user from using the bot (permanent)",
            "**.ban <username> <days>** - ban a user from using the bot (for x days)"
            "**.unban <username>** - unban a user from using the bot",
            "**.banlist** - list banned users",
            "#### Settings:",
        ]

        self.add_reaction(message, "robot_face")
        txt = "\n".join(commands)
        self.driver.reply_to(message, f"## :robot_face: Help:\n{txt}\n\n")
        if self.is_admin(message.sender_name):
            settings_key = self.SETTINGS_KEY
            for key in self.redis.hkeys(settings_key):
                commands_admin.append(f" - {key}")
            txt = "\n".join(commands_admin)
            self.driver.reply_to(message, f"\n\n{txt}\n", direct=True)

    # eval function that allows admins to run arbitrary python code and return the result to the chat
    @listen_to(r"^\.eval (.*)")
    async def admin_eval_function(self, message, code):
        """eval function that allows admins to run arbitrary python code and return the result to the chat"""
        reply = ""
        if self.is_admin(message.sender_name):
            try:
                resp = eval(code)  # pylint: disable=eval-used
                reply = f"Evaluated: {code} \nResult: {resp}"
            except Exception as error_message:  # pylint: disable=broad-except
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)

    @listen_to(r"^\.exec (.*)")
    async def admin_exec_function(self, message, code):
        """exec function that allows admins to run arbitrary python code and return the result to the chat"""
        reply = ""
        if self.is_admin(message.sender_name):
            try:
                resp = exec(code)  # pylint: disable=exec-used
                reply = f"Executed: {code} \nResult: {resp}"
            except Exception as error_message:  # pylint: disable=broad-except
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)

    @listen_to(r"^\.shell (.*)")
    async def admin_shell_function(self, message, code):
        """shell function that allows admins to run arbitrary shell commands and return the result to the chat"""
        reply = ""
        shellescaped_code = shlex.quote(code)
        shell_part = f"docker run --rm lbr/ubuntu:utils /bin/bash -c "
        shellcode = (
            f'docker run --rm lbr/ubuntu:utils /bin/bash -c "{shellescaped_code}"'
        )
        command = f"{shell_part} {shellcode}"
        command_parts = shlex.split(command)
        c = command_parts[0]
        c_rest = command_parts[1:]
        if self.is_admin(message.sender_name):
            try:
                self.driver.react_to(message, "runner")
                proc = await asyncio.create_subprocess_exec(
                    c,
                    *command_parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                stdout = stdout.decode("utf-8")
                stderr = stderr.decode("utf-8")
                reply = f"Executed: {code}\t\n{shellcode} \nResult: {proc.returncode} \nOutput:\n{stdout}"
                if proc.returncode != 0:
                    reply += f"\nError:\n{stderr}"
                    self.driver.react_to(message, "x")
                else:
                    self.driver.react_to(message, "white_check_mark")
            except asyncio.TimeoutError as error_message:
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)
            # remove thought balloon
            self.driver.reactions.delete_reaction(
                self.driver.user_id, message.id, "runner"
            )

    def get_all_usage(self):
        """get all usage"""
        return {
            "usage": self.redis.hgetall("usage"),
            "tokens": self.redis.hgetall("tokens"),
        }

    def get_usage_for_user(self, username):
        """get usage for user"""
        return {
            "usage": self.redis.hget("usage", username),
            "tokens": self.redis.hget("tokens", username),
        }

    def add_usage_for_user(self, username, usage):
        """add usage for user"""
        self.redis.hincrby("usage", username, 1)
        self.redis.hincrby("tokens", username, usage)

    def append_chatlog(self, thread_id, msg):
        """append a message to a chatlog"""
        expiry = 60 * 60 * 24 * 7
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.redis_serialize_json(msg))
        self.redis.expire(thread_key, expiry)
        messages = self.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
        return messages

    def redis_serialize_json(self, msg):
        """serialize a message to json"""
        return json.dumps(msg)

    def redis_deserialize_json(self, msg):
        """deserialize a message from json"""
        if isinstance(msg, list):
            return [json.loads(m) for m in msg]
        return json.loads(msg)


if __name__ == "__main__":
    ChatGPT()
