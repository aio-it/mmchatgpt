"""ChatGPT plugin for mmpy_bot"""
import os
import asyncio
import requests
import time
import json
from pprint import pformat
from environs import Env

env = Env()
import openai
from openai import AsyncOpenAI

aclient = AsyncOpenAI(api_key=env.str("OPENAI_API_KEY"))
import redis
import aiohttp.client_exceptions as aiohttp_client_exceptions
import tiktoken
import urllib
import uuid
import pyttsx3
import shlex
import datetime
import base64
from typing import Tuple, List
from plugins.common import Helper , Users


# import serialized_redis
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from redis_rate_limit import RateLimit, TooManyRequests

MODEL = "gpt-3.5-turbo-0301"
ADMINS = []  # put admins in here to prepopulate the redis db
USERS = []  # put users in here to prepopulate the redis db
REDIS_PREPEND = "thread_"
SHELL_COMMANDS = {
            "ping": {
                "validators": ["ipv4", "domain"],
                "command": "ping",
                "args": "-c 4 -W 1"
            },
            "ping6": {
                "validators": ["ipv6", "domain"],
                "command": "ping6",
                "args": "-c 4 -W 1"
            },
            "dig": {
                "validators": ["ip", "domain"],
                "command": "dig",
                "args": "+short"
            },
            "traceroute": {
                "validators": ["ipv4", "domain"],
                "command": "traceroute",
                "args": "-w 1"
            },
            "traceroute6": {
                "validators": ["ipv6", "domain"],
                "command": "traceroute6",
                "args": "-w 1"
            },
            "whois": {
                "validators": ["ip", "domain","asn"],
                "command": "whois",
                "args": ""
            },
            "head": {
                "validators": ["url","domain"],
                "command": "curl",
                "args": "-I -L",
                "allowed_args": ["-I","-L","-k"]
            },
            "get": {
                "validators": ["url","domain"],
                "command": "curl",
                "args": "-L",
                "allowed_args": ["-k"]
            },
            "date": {
                "validators": [],
                "command": "date",
                "args": ""
            },
            "uptime": {
                "validators": [],
                "command": "uptime",
                "args": ""
            },
            "ptr": {
                "validators": ["ip"],
                "command": "dig",
                "args": "+short -x"
            },
            "aaaa": {
                "validators": ["domain"],
                "command": "dig",
                "args": "+short -t AAAA"
            },
            "cname": {
                "validators": ["domain"],
                "command": "dig",
                "args": "+short -t CNAME"
            },
            "mx": {
                "validators": ["domain"],
                "command": "dig",
                "args": "+short -t MX"
            },
            "ns": {
                "validators": ["domain"],
                "command": "dig",
                "args": "+short -t NS"
            },
            "soa": {
                "validators": ["domain"],
                "command": "dig",
                "args": "+short -t SOA"
            },
            "txt": {
                "validators": ["domain"],
                "command": "dig",
                "args": "+short -t TXT"
            },
            "nmap": {
                "validators": ["ip", "domain"],
                "command": "nmap",
                "args": "-Pn",
                "allowed_args": ["-Pn","-sC","-O","-T4","-p-"]
            },
            "tcpportcheck": {
                "validators": ["ip", "domain", "port"],
                "command": "nc",
                "args": "-vz",
                "allowed_args": ["-vz"]
            },
        }

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
        "gpt-4-1106-preview",
        "gpt-4-vision-preview",
    ]
    MAX_TOKENS_PER_MODEL = {
        "gpt-3.5-turbo-0301": 3000,
        "gpt-3.5-turbo": 3000,
        "gpt-4": 7000,
        "gpt-4-32k": 7000,
        "gpt-4-1106-preview": 7000,
        "gpt-4-vision-preview": 7000,
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
        self.openai_api_key = openai_api_key

        if "giphy_api_key" in kwargs:
            self.giphy_api_key = kwargs["giphy_api_key"]
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
    def initialize(self,
            driver: Driver,
            plugin_manager: PluginManager,
            settings: Settings
            ):
        self.driver = driver
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.helper = Helper(self.driver, self.redis)
        self.users = Users(self.log_channel)
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

    @listen_to(r"^\.model set ([a-zA-Z0-9_-]+)")
    async def model_set(self, message: Message, model: str):
        """set the model"""
        if self.users.is_admin(message.sender_name):
            if model in self.ALLOWED_MODELS:
                self.redis.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Set model to {model}")
            else:
                self.driver.reply_to(
                    message, f"Model not allowed. Allowed models: {self.ALLOWED_MODELS}"
                )

    @listen_to(r"^\.model get")
    async def model_get(self, message: Message):
        """get the model"""
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {self.model}")

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

    @listen_to(r"\.uid ([a-zA-Z0-9_-]+)")
    async def uid(self, message: Message, username: str):
        """get user id from username"""
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, self.get_uid(username))

    def get_uid(self, username, force=False):
        """get uid from username"""
        # check if uid is cached in redis
        if not force and self.redis.exists(f"uid:{username}"):
            return self.redis.get(f"uid:{username}")
        try:
            uid = self.get_user_by_username(username)["id"]
        except:
            # uid not found
            uid = None
            # throw exception if user is not found
            raise Exception(f"User not found: {username}")
        # cache the uid in redis for 1 hour
        if uid != None:
            self.redis.set(f"uid:{username}", uid, ex=60 * 60)
        return uid

    def u2id(self, username):
        """convert username to uid"""
        return self.get_uid(username)

    def id2u(self, user_id):
        """convert uid to username"""
        return self.get_user_by_user_id(user_id)["username"]

    def check_if_username_or_id(self, username_or_id):
        """check if username or id"""
        try:
            user = self.get_user_by_username(username_or_id)["username"]
        except:
            user = None
        try:
            uid = self.get_user_by_user_id(username_or_id)["id"]
        except:
            uid = None

        if user is None and uid is None:
            return "not found"
        if user is not None:
            return "user"
        if uid is not None:
            return "uid"
    def user_exists(self, username):
        """check if user exists"""
        if self.check_if_username_or_id(username) == "not found":
            return False
        return True
    def get_user_by_username(self, username):
        """get user from username"""
        # check if user is cached in redis
        if self.redis.exists(f"user:{username}"):
            return self.helper.redis_deserialize_json(self.redis.get(f"user:{username}"))
        users = self.driver.users.get_users_by_usernames([username])
        if len(users) == 1:
            # cache the user in redis for 1 hour
            self.redis.set(
                f"user:{username}", self.helper.redis_serialize_json(users[0]), ex=60 * 60
            )
            return users[0]
        if len(users) > 1:
            # throw exception if more than one user is found
            raise Exception(
                f"More than one user found: {users} this is undefined behavior"
            )
        return None

    def get_user_by_user_id(self, user_id):
        """get user id from user_id"""
        # check if user is cached in redis
        if self.redis.exists(f"user:{user_id}"):
            return self.helper.redis_deserialize_json(self.redis.get(f"user:{user_id}"))
        try:
            user = self.driver.users.get_user(user_id)
            # cache the user in redis for 1 hour
            self.redis.set(
                f"user:{user_id}", self.helper.redis_serialize_json(user), ex=60 * 60
            )
            return user
        except:
            return None

    def on_start(self):
        """send startup message to all admins"""
        # self.log("ChatGPT Bot started")
        # self.log("model: " + self.model)
        # convert all admins usernames to user ids and save to redis
        for admin in self.redis.smembers("admins"):
            # check if it is already a uid
            if self.check_if_username_or_id(admin) == "uid":
                continue
            # replace current admin username with uid in redis
            self.redis.srem("admins", admin)
            self.redis.sadd("admins", self.get_uid(admin))
        # convert all users usernames to user ids and save to redis
        for user in self.redis.smembers("users"):
            # check if it is already a uid
            if self.check_if_username_or_id(user) == "uid":
                continue
            # replace current user username with uid in redis
            self.redis.srem("users", user)
            self.redis.sadd("users", self.get_uid(user))
        # convert all bans usernames to user ids and save to redis
        for key in self.redis.scan_iter("ban:*"):
            user = key.split(":")[1]
            # check if it is already a uid
            if self.check_if_username_or_id(user) == "uid":
                continue
            # get expire time
            expire = self.redis.ttl(key)
            # replace current ban username with uid in redis
            self.redis.delete(key)
            self.redis.set(f"ban:{self.get_uid(user)}", expire)

    def on_stop(self):
        """send startup message to all admins"""
        self.log("ChatGPT Bot stopped")

    def print_to_console(self, message: Message):
        """print to console"""
        print(f"{message.sender_name}: {message.text}")

    def is_user(self, username):
        """check if user is user"""
        # check if user is banned
        if self.redis.exists(f"ban:{self.u2id(username)}"):
            return False
        return True if self.u2id(username) in self.redis.smembers("users") else False

    def is_admin(self, username):
        """check if user is admin"""
        # convert username to uid
        return True if self.u2id(username) in self.redis.smembers("admins") else False

    async def wall(self, message):
        """send message to all admins"""
        for admin_uid in self.redis.smembers("admins"):
            self.driver.direct_message(receiver_id=admin_uid, message=message)

    async def log(self, message: str):
        """send message to log channel"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)
    def slog(self,message: str):
        """sync log"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)
    
    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        print(f"DEBUG: {message}")
        if self.log_to_channel and not private:
            await self.log(f"DEBUG: {message}")
        elif private:
            await self.wall(f"DEBUG: {message}")

    @listen_to(r"^\.users remove (.+)")
    async def users_remove(self, message: Message, username: str):
        """remove user"""
        if self.users.is_admin(message.sender_name):
            # convert username to uid
            uid = self.u2id(username)
            self.redis.srem("users", uid)
            self.driver.reply_to(message, f"Removed user: {username} ({uid})")
            await self.log(f"Removed user: {username} ({uid})")

    @listen_to(r"^\.users add (.+)")
    async def users_add(self, message: Message, username: str):
        """add user"""
        if self.users.is_admin(message.sender_name):
            # check if user exists
            if self.get_user_by_username(username) is None:
                self.driver.reply_to(message, f"User not found: {username}")
                return
            self.redis.sadd("users", self.u2id(username))
            self.driver.reply_to(
                message, f"Added user: {username} ({self.u2id(username)})"
            )

    @listen_to(r"^\.users list")
    async def users_list(self, message: Message):
        """list the users"""
        if self.users.is_admin(message.sender_name):
            # loop through all users and get their usernames
            users = ""
            for user in self.redis.smembers("users"):
                users += f"{self.nohl(self.id2u(user))} ({user})\n"
            self.driver.reply_to(message, f"Allowed users:\n{users}")

    @listen_to(r"^\.admins add (.*)")
    async def admins_add(self, message: Message, username: str):
        """add admin"""
        if self.users.is_admin(message.sender_name):
            # check if user exists
            if self.get_user_by_username(username) is None:
                self.driver.reply_to(message, f"User not found: {username}")
                return
            # convert username to uid
            uid = self.u2id(username)
            self.redis.sadd("admins", uid)
            self.driver.reply_to(message, f"Added admin: {username}")

    @listen_to(r"^\.admins remove (.*)")
    async def admins_remove(self, message: Message, username: str):
        """remove admin"""
        if self.users.is_admin(message.sender_name):
            self.redis.srem("admins", self.u2id(username))
            self.driver.reply_to(message, f"Removed admin: {username}")

    @listen_to(r"^\.admins list")
    async def admins_list(self, message: Message):
        """list the admins"""
        if self.users.is_admin(message.sender_name):
            # get a list of all admins and convert their uids to usernames
            admins = ""
            for admin in self.redis.smembers("admins"):
                admins += f"{self.id2u(admin)} ({admin})\n"
            self.driver.reply_to(message, f"Allowed admins:\n{admins}")

    @listen_to(r"^\.(?:mk)?i[mn]g$")
    async def img_help(self, message: Message):
        await self.img(message, "help")

    @listen_to(r"^\.(?:mk)?i[mn]g ([\s\S]*)")
    async def img(self, message: Message, text: str):
        """use the openai module to get and image from text"""
        # check if the text is help
        if text == "help" or text == "-h" or text == "--help":
            options_msg = ".img [options...] <prompt> - use dall-e-3 to generate an image from your prompt"
            options_msg += "\noptions:"
            options_msg += "\n\n*size:*"
            options_msg += "\nportrait - use portrait mode"
            options_msg += "\nlandscape - use landscape mode"
            options_msg += "\nsquare - use square mode (default)"
            options_msg += "\n\n*style:*"
            options_msg += "\nnatural - use natural style"
            options_msg += "\nvivid - use vivid style (default)"
            options_msg += "\n\n*quality:*"
            options_msg += "\nstandard - use standard quality"
            options_msg += "\nhd - use hd quality (default)"
            self.driver.reply_to(message, options_msg)
            return
        if self.users.is_user(message.sender_name):
            # define defaults
            default_size = "1024x1024"
            default_style = "vivid"
            default_quality = "hd"
            # config words
            size_words = ["portrait", "landscape", "square"]
            style_words = ["vivid", "natural"]
            quality_words = ["standard", "hd"]
            quality = default_quality
            style = default_style
            size = default_size

            # loop trough all words in text and remove config words but only if they are in the beginning of the string and next to eachother
            words = text.split(" ")
            i = 0
            while i < len(words):
                w = words[i]
                # check if word is in config words
                if w in size_words or w in style_words or w in quality_words:
                    # parse the config word and set the setting
                    if w == "portrait":
                        size = "1024x1792"
                    elif w == "landscape":
                        size = "1792x1024"
                    elif w == "square":
                        size = "1024x1024"
                    elif w == "natural":
                        style = "natural"
                    elif w == "vivid":
                        style = "vivid"
                    elif w == "standard":
                        quality = "standard"
                    elif w == "hd":
                        quality = "hd"
                    # remove the word at the index i
                    del words[i]
                else:
                    break
            # join the words back together
            text = " ".join(words)

            from openai import AsyncOpenAI  # pylint: disable=import-outside-toplevel

            client = AsyncOpenAI(api_key=self.openai_api_key)
            try:
                with RateLimit(
                    resource="mkimg",
                    client=message.sender_name,
                    max_requests=1,
                    expire=5,
                ):
                    self.add_reaction(message, "frame_with_picture")
                    text = text.replace("\n", " ")
                    response = await client.images.generate(
                        prompt=text,
                        n=1,
                        size=size,
                        model="dall-e-3",
                        style=style,
                        response_format="url",
                        quality=quality,
                    )
                    # response = openai.Image.create(prompt=text, n=1, size="1024x1024")
                    image_url = response.data[0].url
                    revised_prompt = response.data[0].revised_prompt
                    # download the image using the url
                    filename = self.download_file_to_tmp(image_url, "png")
                    # format the image_url as mattermost markdown
                    # image_url_txt = f"![img]({image_url})"
                    # await self.debug(response)
                    # self.driver.reply_to(message, image_url_txt, file_paths=[filename])
                    self.remove_reaction(message, "frame_with_picture")
                    self.driver.reply_to(
                        message,
                        f"prompt: {text}\nrevised: {revised_prompt}",
                        file_paths=[filename],
                    )
                    self.delete_downloaded_file(filename)
                    await self.log(
                        f"{message.sender_name} used .img with {quality} {style} {size}"
                    )
            except TooManyRequests:
                self.remove_reaction(message, "frame_with_picture")
                self.add_reaction(message, "x")
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
            except openai.BadRequestError as error:
                self.remove_reaction(message, "frame_with_picture")
                self.add_reaction(message, "pig")
                self.driver.reply_to(message, f"Error: {error.message}")
                # self.driver.reply_to(message, f"Error: {pformat(error.message)}")
                # self.driver.reply_to(message, f"Error: {pformat(error)}")
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
                ):
                    self.add_reaction(message, "frame_with_picture")
                    # get the gif from giphy api
                    response = requests.get(url, params=params)
                    # get the url from the response
                    gif_url = response.json()["data"][0]["images"]["original"]["url"]
                    # download the gif using the url
                    filename = self.download_file_to_tmp(gif_url, "gif")
                    # format the gif_url as mattermost markdown
                    # gif_url_txt = f"![gif]({gif_url})"
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
        if self.users.is_admin(message.sender_name):
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
        if self.users.is_admin(message.sender_name):
            self.redis.set(key, value)
            self.driver.reply_to(message, f"Key: {key}\nValue: {value}")

    # redis search
    @listen_to(r"^\.redis search ([\s\S]*)")
    async def redis_search(self, message: Message, key: str):
        """search redis key"""
        if self.users.is_admin(message.sender_name):
            keys = self.redis.keys(key)
            keystxt = ""
            for key in keys:
                # get the type of the key
                keytype = self.redis.type(key)
                keystxt += f" - {key} ({keytype})\n"
            self.driver.reply_to(message, f"Keys:\n{keystxt}")

    # redis delete
    @listen_to(r"^\.redis delete ([\s\S]*)")
    async def redis_delete(self, message: Message, key: str):
        """delete redis key"""
        if self.users.is_admin(message.sender_name):
            self.redis.delete(key)
            self.driver.reply_to(message, f"Deleted: {key}")

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
        if self.users.is_user(message.sender_name):
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
        if self.users.is_admin(message.sender_name):
            self.redis.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.reset chatgpt ([a-zA-Z0-9_-]+)")
    async def reset_chatgpt(self, message: Message, key: str):
        """reset the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        if self.users.is_admin(message.sender_name) and key in self.ChatGPT_DEFAULTS:
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
        if self.users.is_admin(message.sender_name):
            value = self.redis.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.get chatgpt")
    async def get_chatgpt_all(self, message: Message):
        """get all the chatgpt keys"""
        settings_key = self.SETTINGS_KEY
        await self.debug("get_chatgpt_all")
        if self.users.is_admin(message.sender_name):
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
        if self.users.is_user(message.sender_name):
            # print help message
            messagetxt = f".pushups <number> - add pushups for own user\n"
            messagetxt += f".pushups add <number> - add pushups for own user\n"
            messagetxt += f".pushups sub <number> - substract pushups for own user for today and total\n"
            messagetxt += f".pushups top5 - top 5 pushups scores\n"
            messagetxt += f".pushups scores - scores for all users\n"
            messagetxt += f".pushups score - score for own user\n"
            messagetxt += f".pushups reset - reset pushups for self\n"
            messagetxt += (
                f".pushups reset <user> - reset pushups for user (admin-only)\n"
            )
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups top([1-9][0-9]*)")
    async def pushups_top(self, message: Message, topcount):
        """pushups scores for all users"""
        # TODO: add streaks
        if self.users.is_user(message.sender_name):
            topcount = int(topcount)
            if topcount > 100:
                topcount = 100
            # print help message
            messagetxt = f"Top {topcount} pushups scores :weight_lifter:\n"
            scores = {}
            averages = {}
            days = {}
            for key in self.redis.scan_iter("pushupsdaily:*"):
                user = key.split(":")[1]
                score = int(self.redis.get(key))
                if user in scores:
                    scores[user] += score
                else:
                    scores[user] = score
            # get averages
            for user in scores:
                # get day count for user
                userdays = self.redis.keys(f"pushupsdaily:{user}:*")
                if len(userdays) > 0:
                    days[user] = len(userdays)
                    import math

                    averages[user] = math.ceil(scores[user] / len(userdays))
                else:
                    days[user] = 0
                    averages[user] = 0
            top = []
            for user, score in scores.items():
                top.append((user, score))
            top.sort(key=lambda x: x[1], reverse=True)
            for i in range(topcount):
                if i < len(top):
                    place = i + 1
                    if place == 1:
                        place = ":first_place_medal: "
                    elif place == 2:
                        place = ":second_place_medal: "
                    elif place == 3:
                        place = ":third_place_medal: "
                    else:
                        place = f"{place}. "
                    messagetxt += f"**{place} {self.nohl(top[i][0])}: {top[i][1]}**\t(avg: {averages[top[i][0]]}. days: {days[top[i][0]]})\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.vision (.+)")
    async def parseimage(self, message: Message, msg: str):
        """check if post contains an image upload in the message.body.post.file_ids and parse it"""
        if self.users.is_user(message.sender_name):
            data = message.body["data"]
            post = data["post"]
            # url encode msg
            msg = self.urlencode_text(msg)
            # check if message contains an image
            if data["image"] == "true":
                file_ids = post["file_ids"]
                files_metadata = post["metadata"]["files"]
                # check the metadata of the image and get the extension
                extension = files_metadata[0]["extension"]
                # skip if wrong extension
                if extension not in ["png", "jpg", "jpeg"]:
                    return
                # get the image url
                get_file_response = self.driver.files.get_file(file_ids[0])
                if get_file_response.status_code == 200:
                    image_content = get_file_response.content
                else:
                    return
                # convert the image to base64
                image_base64 = base64.b64encode(image_content).decode("utf-8")
                # send the image to the openai vision model
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openai_api_key}",
                }

                payload = {
                    "model": "gpt-4-vision-preview",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "{msg}"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_base64}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 300,
                }
                self.add_reaction(message, "thought_balloon")
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if response.status_code == 200:
                    # convert the response.content to json
                    response = response.json()
                    # log the response:
                    gpt_response = response["choices"][0]["message"]["content"]
                    self.driver.reply_to(message, gpt_response)
                    self.remove_reaction(message, "thought_balloon")

                    await self.log(f"{message.sender_name} used .vision")

    @listen_to(".+", needs_mention=True)
    async def chat(self, message: Message):
        """listen to everything and respond when mentioned"""
        if not self.users.is_user(message.sender_name):
            return
        # if message.is_direct_message and not self.is_admin(message.sender_name):
        #    return
        if message.text[0] == ".":  # ignore commands
            return
        # if message start with ! ignore
        if message.text[0] == "!":
            return
        # set stream using ternary
        stream = True if self.get_chatgpt_setting("stream") == "true" else False
        msg = message.text
        # log the message if user is admin
        # if self.is_admin(message.sender_name):
        #    await self.log(f"{message.sender_name}:  {pformat(message.body)}")
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

                # self.redis.rpush(thread_key, self.helper.redis_serialize_json(
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
                response = await aclient.chat.completions.create(
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
            except openai.InvalidRequestError as error:
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
                response = await aclient.chat.completions.create(
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
                    # TODO: might need fixing
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
                    from pprint import pprint

                    chunk_message = chunk.choices[0].delta
                    # self.driver.reply_to(message, chunk_message.content)
                    # if the message has content, add it to the full message
                    if chunk_message.content:
                        full_message += chunk_message.content
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
            # log usage for user
            await self.log(
                f"User: {message.sender_name} used {response['usage']['total_tokens']} tokens"
            )
        else:
            await self.log(f"User: {message.sender_name} used {self.model}")

    @listen_to(r"^.(de|en)code ([a-zA-Z0-9]+) (.*)")
    async def decode(self, message: Message, method: str, encoding: str, text: str):
        """decode text using a model"""
        supported_encodings = ["base64", "b64", "url"]
        encode = True if method == "en" else False
        decode = True if method == "de" else False
        if self.users.is_user(message.sender_name):
            if text == "" or encoding == "" or encoding == "help":
                # print help message
                messagetxt = (
                    f".encode <encoding> <text> - encode text using an encoding\n"
                )
                messagetxt += (
                    f".decode <encoding> <text> - decode text using an encoding\n"
                )
                messagetxt += f"Supported encodings: {' '.join(supported_encodings)}\n"
                self.driver.reply_to(message, messagetxt)
                return
            # check if encoding is supported
            if encoding not in supported_encodings:
                self.driver.reply_to(
                    message,
                    f"Error: {encoding} not supported. only {supported_encodings} is supported",
                )
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

    def validatecommand(self, command):
        """check if commands is in a list of commands allowed"""
        if command in SHELL_COMMANDS:
            return SHELL_COMMANDS[command]
        else:
            return { "error": f"invalid command. supported commands: {' '.join(list(SHELL_COMMANDS.keys()))}" }
    def validateinput(self,input,types=["domain","ip"], allowed_args=[]):
        """function that takes a string and validates that it matches against one or more of the types given in the list"""
        import re
        import validators
        bad_chars = [" ", "\n", "\t", "\r",";","#","!"]
        valid_types = [
            "domain",
            "ip",
            "ipv4",
            "ipv6",
            "url",
            "asn",
            "string",
            "argument",
            "port"
        ]
        if types and type(types) is not list:
            types = [types]
        if len(types) == 0:
            return { "error": "no arguments allowed" }
        # check if any of the bad chars exist in input
        for char in bad_chars:
            if char in input:
                return { "error": f"bad char: {char}" }
        
        for ctype in types:
            if ctype not in valid_types:
                return { "error": f"invalid type: {ctype}" }
        if "domain" in types:
            if validators.domain(input):
                # verify that the ip returned from a dns lookup is not a private ip
                import dns.resolver
                try:
                    answers = dns.resolver.resolve(input, "A")
                except (dns.resolver.NoAnswer):
                    answers = []
                except Exception as error:
                    return { "error": f"error resolving domain: {error}" }
                try:
                    answers6 = dns.resolver.resolve(input, "AAAA")
                except (dns.resolver.NoAnswer):
                    answers6 = []
                except Exception as error:
                    return { "error": f"error resolving domain: {error}" }
                try:
                    answersc = dns.resolver.resolve(input, "CNAME")
                except (dns.resolver.NoAnswer):
                    answersc = []
                except Exception as error:
                    return { "error": f"error resolving domain: {error}" }
                if len(answers) == 0 and len(answers6) == 0 and len(answersc) == 0:
                    return { "error": f"no dns records found for {domain}" }
                # loop over answers6 and answers and check if any of them are private ips
                for a in [answersc,answers6,answers]:
                    for rdata in a:
                        import ipaddress
                        ip = ipaddress.ip_address(rdata.address)
                        if ip.is_private:
                            return { "error": "private ip (resolved from dns)" }
                        if ip.is_reserved:
                            return { "error": "reserved ip (resolved from dns)" }
                        if ip.is_multicast:
                            return { "error": "multicast ip (resolved from dns)" }
                        if ip.is_unspecified:
                            return { "error": "unspecified ip (resolved from dns)" }
                        if ip.is_loopback:
                            return { "error": "loopback ip (resolved from dns)" }
                        if ip.is_link_local:
                            return { "error": "link local ip (resolved from dns)" }
                        # if ipv6
                        if ip.version == 6:
                            if ip.sixtofour is not None:
                                #verify the ipv4 address inside the ipv6 address is not private
                                sixtofour = ipaddress.ip_address(ip.sixtofour)
                                if sixtofour.is_private:
                                    return { "error": "private ip (nice try though)" }
                                if sixtofour.is_reserved:
                                    return { "error": "reserved ip (nice try though)" }
                                if sixtofour.is_multicast:  
                                    return { "error": "multicast ip (nice try though)" }
                                if sixtofour.is_unspecified:
                                    return { "error": "unspecified ip (nice try though)" }
                                if sixtofour.is_loopback:
                                    return { "error": "loopback ip (nice try though)" }
                                if sixtofour.is_link_local:
                                    return { "error": "link local ip (nice try though)" }
                return True
        if "ipv4" in types or "ip" in types:
            if validators.ipv4(input):
                # verify that it is not a private ip
                import ipaddress
                if ipaddress.ip_address(input).is_reserved:
                    return { "error": "reserved ip" }
                if ipaddress.ip_address(input).is_multicast:
                    return { "error": "multicast ip"}
                if ipaddress.ip_address(input).is_unspecified:
                    return { "error": "unspecified ip"}
                if ipaddress.ip_address(input).is_loopback:
                    return { "error": "loopback ip"}
                if ipaddress.ip_address(input).is_private:
                    return { "error": "private ip" }
                return True
        if "ipv6" in types or "ip" in types:
            if validators.ipv6(input):
                # verify that it is not a private ip
                import ipaddress
                if ipaddress.ip_address(input).is_reserved:
                    return { "error": "reserved ip" }
                if ipaddress.ip_address(input).is_multicast:
                    return { "error": "multicast ip" }
                if ipaddress.ip_address(input).is_unspecified:
                    return { "error": "unspecified ip" }
                if ipaddress.ip_address(input).is_loopback:
                    return { "error": "loopback ip" }
                if ipaddress.ip_address(input).is_link_local:
                    return { "error": "link local ip" }
                if ipaddress.ip_address(input).is_private:
                    return { "error": "private ip" }
                if ipaddress.ip_address(input).sixtofour is not None:
                    #verify the ipv4 address inside the ipv6 address is not private
                    if ipaddress.ip_address(ipaddress.ip_address(input).sixtofour).is_private:
                        return { "error": "private ip (nice try though)" }
                return True
        if "url" in types:
            if validators.url(input):
                #get domain from url and validate it as a domain so we can check if it is a private ip
                import urllib.parse
                domain = urllib.parse.urlparse(input).netloc
                if domain == input:
                    # no domain found in url
                    return { "error": "no domain found in url (or localhost)" }
                # call validateinput again with domain
                result = self.validateinput(domain,["domain"])
                # check if dict
                if type(result) is dict:
                    if "error" in result:
                        return { "error": f"domain: {result['error']}" }
                return True
        if "asn" in types:
            if re.match(r"(AS|as)[0-9]+",input):
                return True
        if "string" in types:
            if re.match(r"[a-zA-Z0-9_-]+",input):
                return True
        if "port" in types:
            if re.match(r"[0-9]+",input):
                if int(input) > 65535:
                    return { "error": "port can not be higher than 65535" }
                if int(input) < 1:
                    return { "error": "port can not be lower than 1" }
                return True
        if "argument" in types:
            if input in allowed_args:
                return True
        return { "error": f"invalid input: {input} (no matches) for types {', '.join(types)}" }

    @listen_to(r"^!(.*)")
    async def run_command(self,message: Message, command):
        """ runs a command after validating the command and the input"""
        # check if user is user (lol)
        if not self.users.is_user(message.sender_name):
            self.driver.reply_to(message, f"Error: {message.sender_name} is not a user")
            return
        await self.log(f"{message.sender_name} tried to run command: !{command}")
        # split command into command and input
        command = command.split(" ", 1)
        if len(command) == 1:
            command = command[0]
            input = ""
        else:
            command, input = command
        if command == "help" or command not in SHELL_COMMANDS.keys():
            # send a list of commands from SHELL_COMMANDS
            messagetxt = f"Allowed commands:\n"
            messagetxt += f"!help\n"
            for command in SHELL_COMMANDS.keys():
                argstxt = ""
                valtxt = ""
                if "allowed_args" in SHELL_COMMANDS[command]:
                    argstxt = f"[{' / '.join(SHELL_COMMANDS[command]['allowed_args'])}]"
                if "validators" in SHELL_COMMANDS[command] and len(SHELL_COMMANDS[command]['validators']) > 0:
                    valtxt = f"<{' / '.join(SHELL_COMMANDS[command]['validators'])}>"
                messagetxt += f"!{command} {argstxt} {valtxt}\n"
            self.driver.reply_to(message, messagetxt)
            return
        validators = []
        args = ""
        valid_commands = self.validatecommand(command)
        if "error" in valid_commands:
            self.driver.reply_to(message, f"Error: {valid_commands['error']}")
            await self.log(f"Error: {valid_commands['error']}")
            return
        else:
            validators = valid_commands["validators"]
            command = valid_commands["command"]
            args = valid_commands["args"]
            if "allowed_args" in valid_commands:
                allowed_args = valid_commands["allowed_args"]
                validators.append("argument")
            else:
                allowed_args = []
            # validate input for each word in input
            if input != "":
                inputs = input.split(" ")
                for word in inputs:
                    valid_input = self.validateinput(word,validators,allowed_args)
                    #check if dict
                    if type(valid_input) is dict:
                        if "error" in valid_input:
                            self.driver.reply_to(message, f"Error: {valid_input['error']}")
                            await self.log(f"Error: {valid_input['error']}")
                            return False
                    if valid_input is False:
                        self.driver.reply_to(message, f"Error: {word} is not a valid input to {command}")
                        await self.log(f"Error: {word} is not a valid input to {command}")
                        return False
                    # run command
            self.add_reaction(message, "hourglass")
            await self.log(f"{message.sender_name} is running command: {command} {args} {input}")
            import subprocess
            import shlex
            cmd = shlex.split(f"{command} {args} {input}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            timeout = False
            try:
                output, error = process.communicate(timeout=10)
                output = output.decode("utf-8")
                error = error.decode("utf-8")
            except subprocess.TimeoutExpired:
                process.kill()
                output, error = process.communicate()
                if output:
                    output = output.decode("utf-8")
                if error:
                    error = error.decode("utf-8")
                timeout=True
            self.remove_reaction(message, "hourglass")
            self.driver.reply_to(message, f"{command} {args} {input}\nResult:\n```\n{output}\n```")
            if error:
                self.driver.reply_to(message, f"Error:\n```\n{error}\n```")
            if timeout:
                self.driver.reply_to(message, f"Timed out: 10 seconds")
            await self.log(f"{message.sender_name} ran command: {command} {args} {input}")


    @listen_to(r"^\.help")
    async def help_function(self, message):
        """help function that returns a list of commands"""
        commands = [
            "### Commands:",
            "---",
            "**.help** - returns this list of commands and usage",
            f"**@{self.driver.client.username} <text>** - returns a response from the chatgpt model (reply to a message to use the context of that thread)",
            "**.vision <text>** - Parse an image while providing it with a question or text (attach image to the message)",
            "**.mkimg <text>** - text to image using DALL-E3; returns an hd image",
            "**.mkstdimg <text>** - text to image using DALL-E3; returns an standard image",
            "**.drtts <text>** - text to speech using DR TTS; returns an audio file",
            "**.tts <text>** - text to speech using pyttsx3; returns an audio file",
            "**.pushups** - pushups help",
            "**.gif <text>** - text to gif using GIPHY; returns a gif",
            "**.calc <expression>** - calculate an expression using mathjs(lol) api returns the result",
            "**.decode <encoding> <text>** - decode text using an encoding",
            "**.encode <encoding> <text>** - encode text using an encoding",
            "**.whois <url>** - whois a url",
            "**.dig <url>** - dig a url",
            "**.ping6 <url>** - ping6 a ip or hostname",
            "**.head <url>** - curl -i a url",
            "**.ping <url>** - ping a ip or hostname",
            "**.traceroute <url>** - traceroute a ip or hostname",
            "**.traceroute6 <url>** - traceroute6 a ip or hostname",
        ]

        commands_admin = [
            "### Admin commands",
            "---",
            "**.get chatgpt <setting>** - get a setting for chatgpt",
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
        if self.users.is_admin(message.sender_name):
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
        if self.users.is_admin(message.sender_name):
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
        if self.users.is_admin(message.sender_name):
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
        shell_part = f"docker run lbr/ubuntu:utils /bin/bash -c "
        shellcode = (
            f'docker run lbr/ubuntu:utils /bin/bash -c "{shellescaped_code}"'
        )
        command = f"{shell_part} {shellcode}"
        command_parts = shlex.split(command)
        c = command_parts[0]
        c_rest = command_parts[1:]
        if self.users.is_admin(message.sender_name):
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

    def append_chatlog(self, thread_id, msg):
        """append a message to a chatlog"""
        expiry = 60 * 60 * 24 * 7
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.helper.redis_serialize_json(msg))
        self.redis.expire(thread_key, expiry)
        messages = self.helper.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
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