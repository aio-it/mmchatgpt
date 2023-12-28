"""ChatGPT plugin for mmpy_bot"""
import asyncio
import requests
import time
import json
from environs import Env
env = Env()

import openai
from openai import AsyncOpenAI

aclient = AsyncOpenAI(api_key=env.str("OPENAI_API_KEY"))
import redis
import aiohttp.client_exceptions as aiohttp_client_exceptions
import tiktoken
import shlex
import base64
from plugins.base import PluginLoader

from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from redis_rate_limit import RateLimit, TooManyRequests
from pprint import pformat

MODEL = "gpt-3.5-turbo-0301"
REDIS_PREPEND = "thread_"

# Custom Exceptions

# exception for missing api key


class MissingApiKey(Exception):
    """Missing API key exception"""


class ChatGPT(PluginLoader):
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
        if openai_api_key is None:
            raise MissingApiKey("No OPENAI API key provided")
        self.openai_api_key = openai_api_key
        if "giphy_api_key" in kwargs:
            self.giphy_api_key = kwargs["giphy_api_key"]
        else:
            self.giphy_api_key = None

    def initialize(
        self,
        driver: Driver,
        plugin_manager: PluginManager,
        settings: Settings,
    ):
        super().initialize(driver, plugin_manager, settings)
        # Apply default model to redis if not set and set self.model
        self.model = self.redis.hget(self.SETTINGS_KEY, "model")
        if self.model is None:
            self.redis.hset(self.SETTINGS_KEY, "model", self.DEFAULT_MODEL)
            self.model = self.DEFAULT_MODEL
        # Apply defaults to redis if not set
        for key, value in self.ChatGPT_DEFAULTS.items():
            if self.redis.hget(self.SETTINGS_KEY, key) is None:
                self.redis.hset(self.SETTINGS_KEY, key, value)
        print(f"Allowed models: {self.ALLOWED_MODELS}")
    def return_last_x_messages(self, messages, max_length_in_tokens):
        """return last x messages from list of messages limited by max_length_in_tokens"""
        #fuck this bs
        return messages
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
                    self.helper.add_reaction(message, "frame_with_picture")
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
                    filename = self.helper.download_file_to_tmp(image_url, "png")
                    # format the image_url as mattermost markdown
                    # image_url_txt = f"![img]({image_url})"
                    # await self.helper.debug(response)
                    # self.driver.reply_to(message, image_url_txt, file_paths=[filename])
                    self.helper.remove_reaction(message, "frame_with_picture")
                    self.driver.reply_to(
                        message,
                        f"prompt: {text}\nrevised: {revised_prompt}",
                        file_paths=[filename],
                    )
                    self.helper.delete_downloaded_file(filename)
                    await self.helper.log(
                        f"{message.sender_name} used .img with {quality} {style} {size}"
                    )
            except TooManyRequests:
                self.helper.remove_reaction(message, "frame_with_picture")
                self.helper.add_reaction(message, "x")
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
            except openai.BadRequestError as error:
                self.helper.remove_reaction(message, "frame_with_picture")
                self.helper.add_reaction(message, "pig")
                self.driver.reply_to(message, f"Error: {error.message}")
                # self.driver.reply_to(message, f"Error: {pformat(error.message)}")
                # self.driver.reply_to(message, f"Error: {pformat(error)}")
            except:  # pylint: disable=bare-except
                self.driver.reply_to(message, "Error: OpenAI API error")



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
                    self.helper.add_reaction(message, "frame_with_picture")
                    # get the gif from giphy api
                    response = requests.get(url, params=params)
                    # get the url from the response
                    gif_url = response.json()["data"][0]["images"]["original"]["url"]
                    # download the gif using the url
                    filename = self.helper.download_file_to_tmp(gif_url, "gif")
                    # format the gif_url as mattermost markdown
                    # gif_url_txt = f"![gif]({gif_url})"
                    gif_url_txt = ""
                    self.helper.remove_reaction(message, "frame_with_picture")
                    self.driver.reply_to(message, gif_url_txt, file_paths=[filename])
                    # delete the gif file
                    self.helper.delete_downloaded_file(filename)
                    await self.helper.log(f"{message.sender_name} used .gif with {text}")
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
                    await self.helper.log(f"{message.sender_name} used .calc with {text}")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")

    @listen_to(r"^\.set chatgpt ([a-zA-Z0-9_-]+) (.*)")
    async def set_chatgpt(self, message: Message, key: str, value: str):
        """set the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"set_chatgpt {key} {value}")
        if self.users.is_admin(message.sender_name):
            self.redis.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.reset chatgpt ([a-zA-Z0-9_-]+)")
    async def reset_chatgpt(self, message: Message, key: str):
        """reset the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        if self.users.is_admin(message.sender_name) and key in self.ChatGPT_DEFAULTS:
            value = self.ChatGPT_DEFAULTS[key]
            await self.helper.debug(f"reset_chatgpt {key} {value}")
            self.redis.hset(settings_key, key, self.ChatGPT_DEFAULTS[key])
            self.redis.hdel(settings_key, key)
            self.driver.reply_to(message, f"Reset {key} to {value}")

    @listen_to(r"^\.get chatgpt ([a-zA-Z0-9_-])")
    async def get_chatgpt(self, message: Message, key: str):
        """get the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"get_chatgpt {key}")
        if self.users.is_admin(message.sender_name):
            value = self.redis.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.get chatgpt")
    async def get_chatgpt_all(self, message: Message):
        """get all the chatgpt keys"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug("get_chatgpt_all")
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

    @listen_to(r"^\.vision (.+)")
    async def parseimage(self, message: Message, msg: str):
        """check if post contains an image upload in the message.body.post.file_ids and parse it"""
        if self.users.is_user(message.sender_name):
            data = message.body["data"]
            post = data["post"]
            # url encode msg
            msg = self.helper.urlencode_text(msg)
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
                self.helper.add_reaction(message, "thought_balloon")
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
                    self.helper.remove_reaction(message, "thought_balloon")

                    await self.helper.log(f"{message.sender_name} used .vision")
    async def download_webpage(self, url):
        """download a webpage and return the content"""
        response = requests.get(url)
        if response.status_code == 200:
            #extract all text from the webpage
            import bs4
            soup = bs4.BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()    # rip it out
            # only get the body
            text = soup.body.get_text()
            # remove all places where there is multiple newlines and replace with single newline
            import re
            text = re.sub(r'[\r\n]{2,}', '\n', text)
            # get the title
            title = soup.title.string
            # get text
            return f"{title}\n{text}"
        return None
    @listen_to(".+", needs_mention=True)
    async def chat(self, message: Message):
        """listen to everything and respond when mentioned"""
        #self.driver.reply_to(message, "Hej")
        # chatgpt "function calling"
        tools =  [{
                "type": "function",
                "function": {
                    "name": "download_webpage",
                    "description": "download a webpage and return the content and a tldr",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "the url for the webpage"
                            }
                        },
                        "required": ["url"]
                    }
                }
            }
        ]
        tool_run = False
        if hasattr(message, 'tool_run') and message.tool_run == True:
            tool_run = True
        if not self.users.is_user(message.sender_name):
            return
        # if message.is_direct_message and not self.is_admin(message.sender_name):
        #    return
        # if we begin with "ollama" skip
        if message.text.lower().startswith("ollama"):
            return
        if message.text[0] == ".":  # ignore commands
            return
        # if message start with ! ignore
        if message.text[0] == "!":
            return
        # set stream using ternary
        stream = True if self.get_chatgpt_setting("stream") == "true" else False
        if tool_run:
            msg = ""
        else:
            msg = message.text
        orig_reply_id = message.reply_id
        # log the message if user is admin
        # if self.is_admin(message.sender_name):
        #    await self.helper.log(f"{message.sender_name}:  {pformat(message.body)}")
        thread_id = message.reply_id
        thread_key = REDIS_PREPEND + thread_id
        # check if thread exists in redis
        messages = []
        if self.redis.exists(thread_key) and not tool_run:
            await self.helper.log(f"thread exists: {thread_id} and not tool_run")
            messages = self.append_chatlog(thread_id, {"role": "user", "content": msg})
        elif self.redis.exists(thread_key) and tool_run:
            await self.helper.log(f"thread exists: {thread_id} and tool_run")
            messages = self.get_chatlog(thread_id)
        else:
            await self.helper.log(f"thread does not exist: {thread_id} and tool_run {tool_run}")
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
        # log if lbr
        if message.sender_name == "lbr":
            await self.helper.log(f"messages from thread: {thread_id}")
            await self.helper.log(pformat(messages))
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
            # self.helper.debug(response)
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
            if not tool_run:
                reply_msg_id = self.driver.reply_to(message, full_message)["id"]
            else:
                reply_msg_id = message.reply_msg_id
            # send async request to openai
            if self.users.is_admin(message.sender_name) and message.sender_name == "lbr":
                await self.helper.log(pformat(self.get_chatlog(thread_id)))

            first_chunk = True
            messages = self.return_last_x_messages(
                        messages, self.MAX_TOKENS_PER_MODEL[self.model]
                    )
            await self.helper.log(f"messages: {pformat(messages)}")
            try:
                response = await aclient.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    stream=stream,
                    tools = tools,
                    tool_choice = "auto" if not tool_run else "none",
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
            # self.helper.debug(response)

            # self.helper.debug(f"reply_msg_id: {reply_msg_id}")
            # get current time and set that as last_update_time
            last_update_time = time.time()
            # get the setting for how often to update the message
            stream_update_delay_ms = float(
                self.get_chatgpt_setting("stream_update_delay_ms")
            )
            try:
                functions_to_call = {}
                async for chunk in response:
                    # await self.helper.debug(
                    #    f"time since last chunk: {(time.time() - last_chunk_time) * 1000}")
                    # last_chunk_time = time.time()
                    # self.helper.debug(f"chunk: {chunk}")
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

                    chunk_message = chunk.choices[0].delta
                    #self.driver.reply_to(message, chunk_message.content)
                    #if the message has content, add it to the full message
                    if chunk_message.content:
                        full_message += chunk_message.content
                        # await self.helper.debug((time.time() - last_update_time) * 1000)
                        if (
                            time.time() - last_update_time
                        ) * 1000 > stream_update_delay_ms:
                            # await self.helper.debug("updating message")
                            # update the message
                            self.driver.posts.patch_post(
                                reply_msg_id,
                                {"message": f"{post_prefix}{full_message}"},
                            )
                            # update last_update_time
                            last_update_time = time.time()
                    if chunk_message.tool_calls and chunk_message.content is None:
                        # we are running tools. this sucks when streaming but lets try
                        for tool_call in chunk_message.tool_calls:
                            function_name = tool_call.function.name
                            if function_name == None:
                                # get the function name from the arguments index
                                function_name = tools[tool_call.index]["function"]["name"]
                            if function_name not in functions_to_call:
                                functions_to_call[function_name] = {
                                    "tool_call_id": "",
                                    "arguments": "",
                                }
                                if tool_call.id:
                                    functions_to_call[function_name]["tool_call_id"] = tool_call.id
                                # append to chatlog so we don't get an error when calling chatgpt with the result content
                                self.append_chatlog(
                                    thread_id, self.custom_serializer(chunk_message)
                                )
                                #log
                                await self.helper.log(f"added to chatlog: {pformat(self.custom_serializer(chunk_message))}")

                            #append the argument to the chunked_arguments dict
                            functions_to_call[function_name]['arguments'] += tool_call.function.arguments
                            #log
                            #await self.helper.log(f"tool_call: {function_name} {tool_call.function.arguments}")
                            #await self.helper.log(pformat(functions_to_call))
                # lets try to run the functions now that we are done streaming
                for function_name, tool_function in functions_to_call.items():
                    # get the function
                    tool_call_id = tool_function["tool_call_id"]
                    function = getattr(self, function_name)
                    # get the arguments
                    arguments = json.loads(tool_function['arguments'])
                    # run the function
                    # TODO: parse the arguments to the function from the tools dict instead of this hardcoded bs but it's literally from the example from openai
                    if function_name == "download_webpage":
                        function_result = await function(arguments.get("url"))
                    else:
                        # we shouldn't get to here. panic and run (return)
                        return
                    # add the result to the full message
                    if (function_result != None):
                        # limit the length to 4000 characters
                        #function_result = function_result[:4000]
                        pass
                    else:
                        function_result = "Error: function returned None"
                    # log
                    # log length
                    #await self.helper.log(f"function_result len: {len(full_message)}")
                    #await self.helper.log(f"function_result: {full_message}")
                    # add to chatlog
                    self.append_chatlog(
                       thread_id, { "tool_call_id": tool_call_id, "role": "tool", "name": function_name, "content": function_result }
                    )
                    # log 
                    #await self.helper.log(f"added to chatlog: {pformat({ 'tool_call_id': tool_call_id, 'role': 'tool', 'name': function_name, 'content': function_result })}")
                    if not tool_run:
                        message.tool_run=True
                        message.reply_msg_id = reply_msg_id
                        self.driver.posts.patch_post(
                            reply_msg_id, {"message": f"{post_prefix} ran {function_name} with {tool_function['arguments']}"}
                        )
                        #await self.helper.log(f"ran: {function_name}, calling self with run_tool = True")
                        #await self.chat(message)
                        # just return becuase we let the other thread handle the rest
                        return

                # update the message a final time to make sure we have the full message
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"{post_prefix}{full_message}"}
                )

                # add response to chatlog if it wasn't a tool run
                if not tool_run and full_message != "":
                    self.append_chatlog(
                        thread_id, {"role": "assistant", "content": full_message}
                    )
                    if self.users.is_admin(message.sender_name) and message.sender_name == "lbr":
                        await self.helper.log(f"appended: 'role': 'assistant', 'content': {full_message}]")
                        await self.helper.log(pformat(self.get_chatlog(thread_id)))
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
            await self.helper.log(
                f"User: {message.sender_name} used {response['usage']['total_tokens']} tokens"
            )
        else:
            await self.helper.log(f"User: {message.sender_name} used {self.model}")


    def serialize_choice_delta(self, choice_delta):
        # This function will create a JSON-serializable representation of ChoiceDelta and its nested objects.
        tool_calls = []
        for tool_call in choice_delta.tool_calls:
            tool_calls.append({
                'index': tool_call.index,
                'id': tool_call.id,
                'function': {
                    'arguments': tool_call.function.arguments,
                    'name': tool_call.function.name
                },
                'type': tool_call.type
            })
        return_object = {}

        if choice_delta.content is not None:
            return_object['content'] = choice_delta.content
        if choice_delta.function_call is not None:
            return_object['function_call'] = choice_delta.function_call
        if choice_delta.role is not None:
            return_object['role'] = choice_delta.role
        if tool_calls:
            return_object['tool_calls'] = tool_calls

        return return_object

    def custom_serializer(self, obj):
        # This function is a custom serializer for objects that are not JSON serializable by default.
        if obj.__class__.__name__ == 'ChoiceDelta':
            return self.serialize_choice_delta(obj)
        raise TypeError(f'Object of type {obj.__class__.__name__} is not JSON serializable')

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
            "**.docker help** - returns a list of docker commands",
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

        self.helper.add_reaction(message, "robot_face")
        txt = "\n".join(commands)
        self.driver.reply_to(message, f"## :robot_face: Help:\n{txt}\n\n")
        if self.users.is_admin(message.sender_name):
            settings_key = self.SETTINGS_KEY
            for key in self.redis.hkeys(settings_key):
                commands_admin.append(f" - {key}")
            txt = "\n".join(commands_admin)
            self.driver.reply_to(message, f"\n\n{txt}\n", direct=True)

    def append_chatlog(self, thread_id, msg):
        """append a message to a chatlog"""
        self.helper.slog(f"append_chatlog {thread_id} {msg}")
        expiry = 60 * 60 * 24 * 7
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.helper.redis_serialize_json(msg))
        self.redis.expire(thread_key, expiry)
        messages = self.helper.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
        return messages
    def get_chatlog(self, thread_id):
        """get a chatlog"""
        thread_key = REDIS_PREPEND + thread_id
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
