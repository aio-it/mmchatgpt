"""ChatGPT plugin for mmpy_bot"""

import requests
import time
import json
from environs import Env
env = Env()

import openai
from openai import AsyncOpenAI
from re import DOTALL as re_DOTALL

aclient = AsyncOpenAI(api_key=env.str("OPENAI_API_KEY"))
import aiohttp.client_exceptions as aiohttp_client_exceptions

import base64
from plugins.base import PluginLoader

from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from redis_rate_limit import RateLimit, TooManyRequests
from pprint import pformat

MODEL = "gpt-4-1106-preview"
REDIS_PREPEND = "thread_"

# Custom Exceptions

# exception for missing api key


class MissingApiKey(Exception):
    """Missing API key exception"""


class ChatGPT(PluginLoader):
    """mmypy chatgpt plugin"""
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    # MODEL = "gpt-3.5-turbo-0301"
    DEFAULT_MODEL = "gpt-4o"
    ALLOWED_MODELS = [
        "gpt-3.5-turbo-0125",
        "gpt-3.5-turbo",
        "gpt-4",
        "gpt-4o",
        "gpt-4-32k",
        "gpt-4-1106-preview",
        "gpt-4-vision-preview",
        "gpt-4-turbo-preview",
        "gpt-4-vision",
        "gpt-4-turbo",
        "gpt-4-0125-preview",
    ]
    MAX_TOKENS_PER_MODEL = {
        "gpt-3.5-turbo-0301": 3000,
        "gpt-3.5-turbo": 3000,
        "gpt-4": 7000,
        "gpt-4o": 7000,
        "gpt-4-32k": 7000,
        "gpt-4-1106-preview": 7000,
        "gpt-4-vision-preview": 7000,
        "gpt-4-turbo-preview": 7000,
        "gpt-4-vision": 7000,
        "gpt-4-turbo": 7000,
        "gpt-4-0125-preview": 7000,
    }
    ChatGPT_DEFAULTS = {
        "temperature": 1.0,
        "system": """You're a helpful assistant.""",
        "top_p": 1.0,
        "moderation": "false",
        "stream": "true",
        "stream_update_delay_ms": 200,
    }
    SETTINGS_KEY = "chatgpt_settings"

    def __init__(self):
        super().__init__()
        self.name = "ChatGPT"
        self.names = ["chatgpt", "@gpt4", "@gpt3", "@gpt"]
        self.openai_api_key = env.str("OPENAI_API_KEY")

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
        self.headers = {
            "User-Agent": self.USER_AGENT,
        }
        print(f"Allowed models: {self.ALLOWED_MODELS}")
        # TODO: add ignore function for specific channels like town-square that is global for all users
        # chatgpt "function calling" so we define the tools here.
        # TODO: add more functions e.g. code_runnner, openai vision, dall-e3, etc
        #       define this elsewhere. we don't want to define this in the chat function
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "download_webpage",
                    "description": "download a webpage to import as context and respond to the users query about the content and snippets from the webpage. Ask for confirmation from the user if they want to run the function before doing so and give them the option to use internal knowledge instead",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "the url for the webpage",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "search the web using duckduckgo needs a search term",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "searchterm": {
                                "type": "string",
                                "description": "search term",
                            }
                        },
                        "required": ["searchterm"],
                    },
                },
            },
        ]

    def return_last_x_messages(self, messages, max_length_in_tokens = 7000):
        """return last x messages from list of messages limited by max_length_in_tokens"""
        # fuck this bs
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

    @listen_to(r"^\.gpt model set ([a-zA-Z0-9_-]+)")
    async def model_set(self, message: Message, model: str):
        """set the model"""
        if self.users.is_admin(message.sender_name):
            # if model begins with gpt-
            if model.startswith("gpt-"):
                self.redis.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Set model to {model}")
            elif model in self.ALLOWED_MODELS:
                self.redis.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Set model to {model}")
            else:
                self.driver.reply_to(
                    message, f"Model not allowed. Allowed models: {self.ALLOWED_MODELS} or any model starting with gpt-"
                )

    @listen_to(r"^\.gpt model get")
    async def model_get(self, message: Message):
        """get the model"""
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {self.model}")

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
                    redis_pool=self.redis_pool,
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
                # self.driver.reply_to(message, f"Error: {error.message}")
                # example response:
                # Error code: 400 - {'error': {'code': 'content_policy_violation', 'message': 'Your request was rejected as a result of our safety system. Your prompt may contain text that is not allowed by our safety system.', 'param': None, 'type': 'invalid_request_error'}}
                # parse the error message and return it to the user
                if "{" in error.message:
                    error_message = error.message[error.message.index("{") :]
                    try:
                        error_message = json.loads(
                            error_message.replace("'", '"').replace("None", "null")
                        )
                        self.driver.reply_to(
                            message, f"Error: {error_message['error']['message']}"
                        )
                    except json.JSONDecodeError:
                        self.driver.reply_to(message, f"Error: {error.message}")
                        return
                else:
                    self.driver.reply_to(message, f"Error: {error.message}")
                # self.driver.reply_to(message, f"Error: {pformat(error.message)}")
                # self.driver.reply_to(message, f"Error: {pformat(error)}")
            # except:  # pylint: disable=bare-except
            #    self.driver.reply_to(message, "Error: OpenAI API error")

    @listen_to(r"^\.gpt set ([a-zA-Z0-9_-]+) (.*)")
    async def set_chatgpt(self, message: Message, key: str, value: str):
        """set the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"set_chatgpt {key} {value}")
        if self.users.is_admin(message.sender_name):
            self.redis.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.gpt reset ([a-zA-Z0-9_-]+)")
    async def reset_chatgpt(self, message: Message, key: str):
        """reset the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        if self.users.is_admin(message.sender_name) and key in self.ChatGPT_DEFAULTS:
            value = self.ChatGPT_DEFAULTS[key]
            await self.helper.debug(f"reset_chatgpt {key} {value}")
            self.redis.hset(settings_key, key, self.ChatGPT_DEFAULTS[key])
            self.redis.hdel(settings_key, key)
            self.driver.reply_to(message, f"Reset {key} to {value}")

    @listen_to(r"^\.gpt get ([a-zA-Z0-9_-])")
    async def get_chatgpt(self, message: Message, key: str):
        """get the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"get_chatgpt {key}")
        if self.users.is_admin(message.sender_name):
            value = self.redis.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.gpt get")
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

    async def web_search(self, searchterm):
        """search the web using duckduckgo"""
        self.exit_after_loop = False
        from duckduckgo_search import AsyncDDGS
        try:
            async with AsyncDDGS(headers=self.headers) as ddgs:
                results = await ddgs.text(searchterm, max_results=5)
                return results
        except Exception as e:
            await self.helper.log(f"Error: {e}")
            return f"Error: {e}"

    async def download_webpage(self, url):
        """download a webpage and return the content"""
        self.exit_after_loop = False
        await self.helper.log(f"downloading webpage: {url}")
        validate_result = self.helper.validate_input(url, "url")
        if validate_result != True:
            await self.helper.log(f"Error: {validate_result}")
            return validate_result

        max_content_size = 10 * 1024 * 1024  # 10 MB
        # follow redirects
        response = requests.get(
            url,
            headers=self.headers,
            timeout=10,
            verify=True,
            allow_redirects=True,
            stream=True,
        )
        # check the content length before downloading
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_content_size:
            await self.helper.log(
                f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"
            )
            return f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"

        # download the content in chunks
        content = b""
        total_bytes_read = 0
        chunk_size = 1024  # adjust the chunk size as needed
        for chunk in response.iter_content(chunk_size=chunk_size):
            content += chunk
            total_bytes_read += len(chunk)
            if total_bytes_read > max_content_size:
                await self.helper.log(
                    f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"
                )
                return f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"
        # decode the content
        response_text = content.decode("utf-8")

        blacklisted_tags = ["script", "style", "head", "title", "noscript"]
        # debug response
        # await self.helper.debug(f"response: {pformat(response.text[:500])}")
        # mattermost limit is 4000 characters
        try:
            if response.status_code == 200:
                # check what type of content we got
                content_type = response.headers.get("content-type")
                # await self.helper.log(f"content_type: {url} {content_type}")
                # html
                if "text/html" in content_type:
                    # extract all text from the webpage
                    import bs4

                    soup = bs4.BeautifulSoup(response_text, "html.parser")
                    # check if the soup could parse anything
                    try:
                        if soup.find():
                            # soup parsed something lets extract the text
                            # remove all blacklisted tags
                            for tag in blacklisted_tags:
                                for match in soup.find_all(tag):
                                    match.decompose()
                            # get all links and links text from the webpage
                            links = []
                            for link in soup.find_all("a"):
                                links.append(f"{link.get('href')} {link.text}")
                            links = " | ".join(links)
                            # check if title exists and set it to a variable
                            title = soup.title.string if soup.title else ""
                            # extract all text from the body
                            text = soup.body.get_text(separator=" | ", strip=True)
                            # trim all newlines to 2 spaces
                            text = text.replace("\n", "  ")

                            # remove all newlines and replace them with spaces
                            # text = text.replace("\n", " ")
                            # remove all double spaces
                            return (
                                f"all links on page {links} - {title} | {text}".strip()
                            )
                    except Exception as e:  # pylint: disable=bare-except
                        await self.helper.log(
                            f"Error: could not parse webpage (Exception) {e}"
                        )
                        return f"Error: could not parse webpage (Exception) {e}"

                elif "xml" in content_type or "json" in content_type:
                    # xml or json
                    return response_text
                else:
                    # unknown content type
                    await self.helper.log(
                        f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text[:500]}"
                    )
                    return f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text}"
            else:
                await self.helper.log(
                    f"Error: could not download webpage (status code {response.status_code})"
                )
                return f"Error: could not download webpage (status code {response.status_code})"
        except requests.exceptions.Timeout:
            await self.helper.log("Error: could not download webpage (Timeout)")
            return "Error: could not download webpage (Timeout)"
        except requests.exceptions.TooManyRedirects:
            await self.helper.log(
                "Error: could not download webpage (TooManyRedirects)"
            )
            return "Error: could not download webpage (TooManyRedirects)"
        except requests.exceptions.RequestException as e:
            await self.helper.log(
                f"Error: could not download webpage (RequestException) {e}"
            )
            return "Error: could not download webpage (RequestException) " + str(e)
        except Exception as e: # pylint: disable=bare-except
            await self.helper.log(f"Error: could not download webpage (Exception) {e}")
            return "Error: could not download webpage (Exception) " + str(e)

    def thread_append(self, thread_id, message) -> None:
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.helper.redis_serialize_json(message))

    def get_thread_messages(self, thread_id: str, force_fetch: bool = False):
        """get the message thread from the thread_id"""
        messages = []
        thread_key = REDIS_PREPEND + thread_id
        if not force_fetch and self.redis.exists(thread_key):
            # the thread exists in redis and we are running a tool.
            messages = self.get_thread_messages_from_redis(thread_id)
        else:
            # thread does not exist, fetch all posts in thread
            thread = self.driver.get_post_thread(thread_id)
            for thread_index in thread["order"]:
                thread_post = thread["posts"][thread_index]
                # turn the thread post into a Message object
                thread_post = Message.create_message(thread_post)

                # remove mentions of self
                thread_post.text = self.helper.strip_self_username(thread_post.text)
                # remove mentions of self from self.names
                for name in self.names:
                    thread_post.text = thread_post.text.replace(f"{name} ", "")
                    thread_post.text = thread_post.text.replace(f"{name}", "")

                # if post is from self, set role to assistant
                if thread_post.is_from_self(self.driver):
                    role = "assistant"
                else:
                    # post is from user, set role to user
                    role = "user"
                # create message object and append it to messages and redis
                message = {"role": role, "content": thread_post.text}
                messages.append(message)
                self.thread_append(thread_id, message)
        return messages

    # function that debugs a chat thread
    @listen_to(r"^\.gpt debugchat")
    async def debug_chat_thread(self, message: Message):
        """debug a chat thread"""
        # set to root_id if set else use reply_id
        thread_id = message.root_id if message.root_id else message.reply_id
        # thread_key = REDIS_PREPEND + thread_id
        messages = self.get_thread_messages_from_redis(thread_id)
        if len(messages) > 0:
            for msg in messages:
                await self.helper.debug(f"message: {pformat(msg)}")
            # send all messages to the user in a single message truncating the message if it's too long
        else:
            await self.helper.debug("no messages in redis thread")
        self.driver.reply_to(message, json.dumps(messages, indent=4)[:4000])

    # soon to be deprecated
    # @listen_to(".+", needs_mention=True)
    # async def chat_moved(self, message: Message):
    #    """listen to everything and respond when mentioned"""
    #    # reply to the message with the new callsign @gpt
    #    self.driver.reply_to(
    #        message, f"#NOTICE\nchanged trigger from @{self.driver.username} to @gpt"
    #    )
    #    await self.chat(message)
    async def chat(self, message: Message, model: str = None):
        """listen to everything and respond when mentioned"""
        # set some variables
        if model is None:
            model = self.model
        stream = True  # disabled the non-streaming mode for simplicity
        # this is to check if the message is from a tool or not
        # TODO this is a hack and needs to be fixed
        tool_run = False
        if hasattr(message, "tool_run") and message.tool_run == True:
            tool_run = True
            msg = ""
        else:
            msg = message.text

        # if message is not from a user, ignore
        if not self.users.is_user(message.sender_name):
            return

        # message text exceptions. bail if message starts with any of these
        skips = [".", "!", "ollama", "@claude", "@opus", "@sonnet"]
        for skip in skips:
            if message.text.lower().startswith(skip):
                return

        # This function checks if the thread exists in redis and if not, fetches all posts in the thread and adds them to redis
        thread_id = message.reply_id
        messages = []
        messages = self.get_thread_messages(thread_id)
        if not tool_run and len(messages) != 1:
            # we don't need to append if length = 1 because then it is already fetched via the mattermost api so we don't need to append it to the thread
            # append message to threads
            m = {"role": "user", "content": message.text}
            # append to messages and redis
            messages.append(m)
            self.thread_append(thread_id, m)

        # add system message
        current_date = time.strftime("%Y-%m-%d %H:%M:%S")
        date_template_string = "<date>"
        if self.get_chatgpt_setting("system") != "":
            system_message = self.get_chatgpt_setting("system")
        else:
            system_message = (
                f"You're a helpful assistant. Current Date: {date_template_string}"
            )
        messages.insert(
            0,
            {
                "role": "system",
                "content": system_message.replace(date_template_string, current_date),
            },
        )
        # add thought balloon to show assistant is thinking
        self.driver.react_to(message, "thought_balloon")
        # set the full message to empty string so we can append to it later
        full_message = ""
        # post_prefix is so we can add the sender name to the message to prevent confusion as to who the reply is to
        post_prefix = f"@{message.sender_name}: "

        # if we are running a tool, we need to reply to the original message and not create a new message.
        # if we are not running a tool, we need to create a new message
        if not tool_run:
            reply_msg_id = self.driver.reply_to(message, full_message)["id"]
        else:
            reply_msg_id = message.reply_msg_id
        # fetch the previous messages in the thread
        messages = self.return_last_x_messages(
            messages
        )
        temperature = float(self.get_chatgpt_setting("temperature"))
        top_p = float(self.get_chatgpt_setting("top_p"))
        # await self.helper.log(f"messages: {pformat(messages)}")
        try:
            response = await aclient.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                stream=stream,
                tools=self.tools,
                tool_choice="auto",
            )
        except (openai.error.RateLimitError, openai.error.APIError) as error:
            # update the message
            self.driver.posts.patch_post(reply_msg_id, {"message": f"Error: {error}"})
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
        i = 0
        try:
            functions_to_call = {}
            async for chunk in response:
                # TODO: might need fixing
                if "error" in chunk:
                    if "message" in chunk:
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

                chunk_message = chunk.choices[0].delta
                await self.helper.debug(chunk)
                # self.driver.reply_to(message, chunk_message.content)
                # if the message has content, add it to the full message
                if chunk_message.content:
                    full_message += chunk_message.content
                    # if full message begins with ``` or any other mattermost markdown append a \
                    # newline to the post_prefix so it renders correctly
                    markdown = [
                        ">",
                        "*",
                        "_",
                        "-",
                        "+",
                        "1",
                        "~",
                        "!",
                        "`",
                        "|",
                        "#",
                        "@",
                        "•",
                    ]
                    if (
                        i == 0
                        and post_prefix[-1] != "\n"
                        and full_message[0] in markdown
                    ):
                        post_prefix += "\n"
                        i += 1
                    # await self.helper.debug((time.time() - last_update_time) * 1000)
                    if (time.time() - last_update_time) * 1000 > stream_update_delay_ms:
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
                    index = 0
                    for tool_call in chunk_message.tool_calls:
                        if tool_call.index is not None:
                            index = tool_call.index
                        if tool_call.function.name is not None:
                            function_name = tool_call.function.name
                        if index not in functions_to_call.keys():
                            functions_to_call[index] = {
                                "tool_call_id": "",
                                "arguments": "",
                            }
                            if function_name is not None:
                                functions_to_call[index][
                                    "function_name"
                                ] = function_name

                            if tool_call.id:
                                functions_to_call[index]["tool_call_id"] = tool_call.id
                            # append to chatlog so we don't get an error when calling chatgpt with the result content
                            chunk_message.role = "assistant"
                            functions_to_call[index]["tool_call_message"] = (
                                self.custom_serializer(chunk_message)
                            )
                            # self.append_chatlog(
                            #    thread_id, self.custom_serializer(chunk_message)
                            # )
                            # log
                            # await self.helper.log(f"added to chatlog: {pformat(self.custom_serializer(chunk_message))}")

                        # append the argument to the chunked_arguments dict
                        functions_to_call[index][
                            "arguments"
                        ] += tool_call.function.arguments
                        # update the functions_to_call dict
                        # functions_to_call[index]["tool_call_message"]["arguments"] = (
                        #    json.dumps(functions_to_call[index]["arguments"])
                        # )
                        # await self.helper.debug(
                        #    f"functions_to_call[index][tool_call_message][arguments]: {pformat(functions_to_call[index]['tool_call_message']['arguments'])}"
                        # )
                        # await self.helper.debug(
                        #    f"functions_to_call[index][arguments]: {pformat(functions_to_call[index]['arguments'])}"
                        # )
                        # log
                        # await self.helper.log(f"tool_call: {function_name} {tool_call.function.arguments}")
                        # await self.helper.log(pformat(functions_to_call))
            # lets try to run the functions now that we are done streaming
            exit_after_loop = False
            status_msg = "running functions...\n"
            call_key = f"{REDIS_PREPEND}_call_{thread_id}"
            for index, tool_function in functions_to_call.items():
                if self.redis.hexists(call_key, tool_function["tool_call_id"]):
                    # tool call has already been run, skip it
                    continue
                exit_after_loop = True
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"{post_prefix} {status_msg}"}
                )
                # check if the tool call has already been run
                # get the function
                function_name = tool_function["function_name"]
                tool_call_id = tool_function["tool_call_id"]
                function = getattr(self, function_name)
                # get the arguments
                try:
                    arguments = json.loads(tool_function["arguments"])

                except json.JSONDecodeError as e:
                    # log
                    await self.helper.log(
                        f"Error: could not parse arguments: {tool_function['arguments']}"
                    )
                    arguments = {}
                # run the function
                # TODO: parse the arguments to the function from the tools dict instead of this hardcoded bs but it's literally from the example from openai
                if function_name == "download_webpage":
                    function_result = await function(arguments.get("url"))
                elif function_name == "web_search":
                    function_result = await function(arguments.get("searchterm"))
                else:
                    # we shouldn't get to here. panic and run (return)
                    await self.helper.log(f"Error: function not found: {function_name}")
                    return
                # add the result to the full message
                if function_result != None:
                    # limit all the keys in the dict to 1000 characters
                    # function_result = function_result[:6000]
                    pass
                else:
                    function_result = "Error: function returned None"
                # log
                # log length
                # await self.helper.log(f"function_result len: {len(full_message)}")
                # await self.helper.log(f"function_result: {full_message}")
                # add tool call to chatlog
                
                #drop the .index from the tool_function["tool_call_message"]
                #if "index" in tool_function["tool_call_message"]:
                #    tool_function["tool_call_message"].index = None
                self.append_thread_and_get_messages(
                    thread_id, tool_function["tool_call_message"]
                )

                # if the function_result is not a string serialize it using the default serializer and turn it into a string
                if not isinstance(function_result, str) and function_result != None:
                    try:
                        function_result = json.dumps(function_result)
                    except json.JSONDecodeError as e:
                        # log
                        await self.helper.log(
                            f"Error: could not parse function_result: {function_result}: {e}"
                        )
                        function_result = "Error: could not parse function_result"
                # limit the length
                function_result = function_result[:20000]
                # add result to chatlog
                self.append_thread_and_get_messages(
                    thread_id,
                    {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_result,
                    },
                )
                # add a user message to the chatlog so it doesn't break when we call chatgpt with the result no idea why this is needed but it is
                # self.append_chatlog(
                #    thread_id, {"role": "user", "content": ""}
                # )
                # save the tool_call_id to the redis db so we can check next time and skip the tool call if it's already been run
                self.redis.hset(call_key, tool_call_id, "true")
                # log
                # await self.helper.log(f"added to chatlog: {pformat({ 'tool_call_id': tool_call_id, 'role': 'tool', 'name': function_name, 'content': function_result })}")
                if not tool_run:
                    message.tool_run = True
                    message.reply_msg_id = reply_msg_id
                    status_msg += f"ran: {function_name} with arguments: ```{json.loads(tool_function['arguments'])}```\n"
                    self.driver.posts.patch_post(
                        reply_msg_id, {"message": f"{post_prefix} {status_msg}"}
                    )
                    await self.helper.debug(
                        f"ran: {function_name}, for user: {message.sender_name} with arguments: {tool_function['arguments']}"
                    )
                    # just return becuase we let the other thread handle the rest
            if exit_after_loop and not tool_run:
                # we ran all the functions, now run the chatgpt again to get the response
                await self.helper.debug(
                    f"exit_after_loop: {exit_after_loop} and not tool_run: {not tool_run}"
                )
                # log the messages
                # mm = self.get_chatlog(thread_id)
                # await self.helper.log(f"messages: {pformat(mm)[:1000]}")
                await self.helper.debug(f"running chatgpt again")
                await self.helper.debug(message)
                await self.chat(message, model)
                return

            # update the message a final time to make sure we have the full message
            self.driver.posts.patch_post(
                reply_msg_id, {"message": f"{post_prefix}{full_message}"}
            )

            # add response to chatlog if it wasn't a tool run
            if not tool_run and full_message != "":
                self.thread_append(
                    thread_id, {"role": "assistant", "content": full_message}
                )
                # if self.users.is_admin(message.sender_name) and message.sender_name == "lbr":
                #    await self.helper.log(f"appended: 'role': 'assistant', 'content': {full_message}]")
                #    await self.helper.log(pformat(self.get_chatlog(thread_id)))
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

        await self.helper.log(f"User: {message.sender_name} used {model}")

    @listen_to(r"^@gpt3[ \n]+.+", regexp_flag=re_DOTALL)
    async def chat_gpt3(self, message: Message):
        """listen to everything and respond when mentioned"""
        await self.chat(message, model="gpt-3.5-turbo")

    @listen_to(r"^@gpt4{0,1}[ \n]+.+", regexp_flag=re_DOTALL)
    async def chat_gpt4(self, message: Message):
        """listen to everything and respond when mentioned"""
        if "4" not in self.model:
            await self.chat(message, "gpt-4-turbo-preview")
        else:
            await self.chat(message)

    @listen_to(r".+", needs_mention=True)
    async def chat_gpt4_mention(self, message: Message):
        """listen to everything and respond when mentioned"""
        # if direct and starting with names bail
        for name in self.names:
            if message.text.startswith(name):
                return
        if "4" not in self.model:
            await self.chat(message, "gpt-4-turbo-preview")
        else:
            await self.chat(message)

    def serialize_choice_delta(self, choice_delta):
        # This function will create a JSON-serializable representation of ChoiceDelta and its nested objects.
        tool_calls = []
        for tool_call in choice_delta.tool_calls:
            tool_calls.append({
                #'index': tool_call.index,
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

    def append_thread_and_get_messages(self, thread_id, msg):
        """append a message to a chatlog"""
        # self.helper.slog(f"append_chatlog {thread_id} {msg}")
        expiry = 60 * 60 * 24 * 7
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.redis_serialize_json(msg))
        self.redis.expire(thread_key, expiry)
        messages = self.helper.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
        return messages

    def get_thread_messages_from_redis(self, thread_id):
        """get a chatlog"""
        thread_key = REDIS_PREPEND + thread_id
        messages = self.helper.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
        return messages

    def redis_serialize_json(self,msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""
        # return json.dumps(msg)
        return self.redis_serialize_jsonpickle(msg)

    def redis_deserialize_json(self, msg):
        """deserialize a message from json"""
        return self.redis_deserialize_jsonpickle(msg)

    def redis_serialize_jsonpickle(self,msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""
        import jsonpickle
        return jsonpickle.encode(msg, unpicklable=False)

    def redis_deserialize_jsonpickle(self, msg):
        """deserialize a message from json"""
        import jsonpickle
        if isinstance(msg, list):
            return [jsonpickle.decode(m) for m in msg]
        return jsonpickle.decode(msg)


if __name__ == "__main__":
    ChatGPT()
