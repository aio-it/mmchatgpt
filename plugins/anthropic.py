"""ChatGPT plugin for mmpy_bot"""

import time
import json
from re import DOTALL as re_DOTALL
from pprint import pformat
import jsonpickle

from environs import Env
from anthropic import (
    AsyncAnthropic,
    Anthropic as SyncAnthropic,
    BadRequestError,
    APIStatusError,
    APIError,
    APIConnectionError,
    APITimeoutError,
)

from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message

from plugins.base import PluginLoader

env = Env()

aclient = AsyncAnthropic(
    # This is the default and can be omitted
    api_key=env.str("ANTHROPIC_API_KEY"),
)
client = SyncAnthropic(
    api_key=env.str("ANTHROPIC_API_KEY"),
)

MODEL = "claude-3-7-sonnet-20250219"
VALKEY_PREPEND = "anthropic_thread_"

# Custom Exceptions

# exception for missing api key


class MissingApiKey(Exception):
    """Missing API key exception"""


class Anthropic(PluginLoader):
    """mmypy anthropic plugin"""

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    DEFAULT_MODEL = MODEL
    ALLOWED_MODELS = [
        DEFAULT_MODEL,
        "claude-3-7-sonnet-20250219",
    ]
    MAX_TOKENS_PER_MODEL = {
        DEFAULT_MODEL: 4096,
        "claude-3-7-sonnet-20250219": 4096,
    }
    ANTHROPIC_DEFAULTS = {
        "temperature": 1.0,
        "system": """You're a helpful assistant.""",
        "top_p": 1.0,
        "moderation": "false",
        "stream": "true",
        "stream_update_delay_ms": 200,
    }
    SETTINGS_KEY = "anthropic_settings"

    def __init__(self):
        super().__init__()
        self.names = ["@claude", "@sonnet", "@s"]
        self.headers = {
            "User-Agent": self.USER_AGENT,
        }

    # pylint: disable=attribute-defined-outside-init
    def initialize(
        self,
        driver: Driver,
        plugin_manager: PluginManager,
        settings: Settings,
    ):
        super().initialize(driver, plugin_manager, settings)
        # Fetch available models from Anthropic API on startup
        try:
            self.fetch_available_models()
            print(f"Fetched allowed models from Anthropic API: {self.ALLOWED_MODELS}")
            print(f"Using latest sonnet model as default: {self.DEFAULT_MODEL}")
        except Exception as e:
            print(f"Error fetching models on initialization: {str(e)}")
            print(f"Using default allowed models: {self.ALLOWED_MODELS}")

        # Apply default model to valkey if not set and set self.model
        self.model = self.valkey.hget(self.SETTINGS_KEY, "model")
        if self.model is None:
            self.valkey.hset(self.SETTINGS_KEY, "model", self.DEFAULT_MODEL)
            self.model = self.DEFAULT_MODEL
        # Apply defaults to valkey if not set
        for key, value in self.ANTHROPIC_DEFAULTS.items():
            if self.valkey.hget(self.SETTINGS_KEY, key) is None:
                self.valkey.hset(self.SETTINGS_KEY, key, value)
        print(f"Using model: {self.model}")

    @listen_to(r"^\.ant model set ([a-zA-Z0-9_-]+)")
    async def model_set(self, message: Message, model: str):
        """set the model"""
        self.fetch_available_models()
        if self.users.is_admin(message.sender_name):
            if model in self.ALLOWED_MODELS:
                self.valkey.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Set model to {model}")
            else:
                self.driver.reply_to(
                    message, f"Model not allowed. Allowed models: {self.ALLOWED_MODELS}"
                )

    @listen_to(r"^\.ant model available")
    async def model_available(self, message: Message):
        """get the available models from the anthropic api"""
        if self.users.is_admin(message.sender_name):
            try:
                models = self.fetch_available_models()
                if models:
                    model_list = "\n".join(models)
                    self.driver.reply_to(message, f"Available Anthropic models:\n```\n{model_list}\n```")
                else:
                    self.driver.reply_to(message, "Failed to fetch available models from Anthropic API.")
            except Exception as e:
                await self.helper.debug(f"Error fetching models: {str(e)}")
                self.driver.reply_to(message, f"Error fetching models: {str(e)}")

    def fetch_available_models(self):
        """Fetch available models from Anthropic API"""
        try:
            response = client.models.list()
            models = [model.id for model in response.data]

            # Update the class' ALLOWED_MODELS list
            if models:
                self.ALLOWED_MODELS = models

                # Find the latest sonnet model to use as default
                sonnet_models = [m for m in models if m.startswith("claude-3-7-sonnet-")]
                if sonnet_models:
                    # Sort models to find the latest version (assuming version format allows string comparison)
                    latest_sonnet = sorted(sonnet_models)[-1]
                    self.DEFAULT_MODEL = latest_sonnet

                # Also update MAX_TOKENS_PER_MODEL with default values for any new models
                for model_id in models:
                    if model_id not in self.MAX_TOKENS_PER_MODEL:
                        self.MAX_TOKENS_PER_MODEL[model_id] = 4096  # Default token limit

            return models
        # pylint: disable=bare-except
        except:  # noqa: E722
            return None

    @listen_to(r"^\.ant model get")
    async def model_get(self, message: Message):
        """get the model"""
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {self.model}")

    @listen_to(r"^\.ant set ([a-zA-Z0-9_-]+) (.*)", regexp_flag=re_DOTALL)
    async def set_anthropic(self, message: Message, key: str, value: str):
        """set the anthropic key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"set_anthropic {key} {value}")
        if self.users.is_admin(message.sender_name):
            self.valkey.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.ant reset ([a-zA-Z0-9_-]+)")
    async def reset_anthropic(self, message: Message, key: str):
        """reset the anthropic key"""
        settings_key = self.SETTINGS_KEY
        if self.users.is_admin(message.sender_name) and key in self.ANTHROPIC_DEFAULTS:
            value = self.ANTHROPIC_DEFAULTS[key]
            await self.helper.debug(f"reset_anthropic {key} {value}")
            self.valkey.hset(settings_key, key, self.ANTHROPIC_DEFAULTS[key])
            self.valkey.hdel(settings_key, key)
            self.driver.reply_to(message, f"Reset {key} to {value}")

    @listen_to(r"^\.ant get ([a-zA-Z0-9_-])")
    async def get_anthropic(self, message: Message, key: str):
        """get the anthropic key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"get_anthropic {key}")
        if self.users.is_admin(message.sender_name):
            value = self.valkey.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.ant get$")
    async def get_anthropic_all(self, message: Message):
        """get all the anthropic keys"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug("get_anthropic_all")
        if self.users.is_admin(message.sender_name):
            for key in self.valkey.hkeys(settings_key):
                if key in self.ANTHROPIC_DEFAULTS:
                    self.driver.reply_to(
                        message, f"{key}: {self.valkey.hget(settings_key, key)}"
                    )
                else:
                    # key not in defaults, delete it. unsupported key
                    self.valkey.hdel(settings_key, key)

    @listen_to(r"^\.ant help")
    async def help(self, message: Message):
        """help message"""
        self.driver.reply_to(
            message,
            """```
                .ant is short for anthropic
                .ant set <key> <value> - set the anthropic key
                .ant get <key> - get the anthropic key
                .ant get - get all the anthropic keys
                .ant model set <model> - set the model
                .ant model get - get the model
                .ant model available - get the available models
                .ant help - this help message
            ```""",
        )

    def get_anthropic_setting(self, key: str):
        """get the anthropic key setting"""
        settings_key = self.SETTINGS_KEY
        value = self.valkey.hget(settings_key, key)
        if value is None and key in self.ANTHROPIC_DEFAULTS:
            value = self.ANTHROPIC_DEFAULTS[key]
        return value

    def thread_append(self, thread_id, message) -> None:
        """append a message to a chatlog"""
        thread_key = VALKEY_PREPEND + thread_id
        self.valkey.rpush(thread_key, self.helper.valkey_serialize_json(message))

    def get_thread_messages(self, thread_id: str, force_fetch: bool = False):
        """get the message thread from the thread_id"""
        messages = []
        thread_key = VALKEY_PREPEND + thread_id
        if not force_fetch and self.valkey.exists(thread_key):
            # the thread exists in valkey and we are running a tool.
            messages = self.get_thread_messages_from_valkey(thread_id)
        else:
            # thread does not exist, fetch all posts in thread
            thread = self.driver.get_post_thread(thread_id)
            user_message_content = ""
            for thread_index in thread["order"]:
                thread_post = thread["posts"][thread_index]
                # turn the thread post into a Message object
                thread_post = Message.create_message(thread_post)
                # self.helper.slog(f"Processing post: {thread_post.text[:50]}...")  # Log first 50 chars

                # remove mentions of self
                thread_post.text = self.helper.strip_self_username(
                    thread_post.text)
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

                # concatenate sequential user messages
                if role == "user":
                    user_message_content += thread_post.text + "\n"
                else:
                    # create message object for the concatenated user messages
                    if user_message_content:
                        user_message = {
                            "role": "user",
                            "content": user_message_content.strip(),
                        }
                        messages.append(user_message)
                        self.thread_append(thread_id, user_message)
                        user_message_content = ""

                    # create message object for the assistant message
                    assistant_message = {"role": role,
                                         "content": thread_post.text}
                    messages.append(assistant_message)
                    self.thread_append(thread_id, assistant_message)

            # if there are any remaining user messages, create a message object and append it
            if user_message_content:
                user_message = {"role": "user",
                                "content": user_message_content.strip()}
                messages.append(user_message)
                self.thread_append(thread_id, user_message)

        return messages

    # function that debugs a chat thread
    @listen_to(r"^\.ant debugchat")
    async def debug_chat_thread(self, message: Message):
        """debug a chat thread"""
        # set to root_id if set else use reply_id
        thread_id = message.root_id if message.root_id else message.reply_id
        # thread_key = VALKEY_PREPEND + thread_id
        messages = self.get_thread_messages_from_valkey(thread_id)
        if len(messages) > 0:
            for msg in messages:
                await self.helper.debug(f"message: {pformat(msg)}")
            # send all messages to the user in a single message
            # truncating the message if it's too long
        else:
            await self.helper.debug("no messages in valkey thread")
        self.driver.reply_to(message, json.dumps(messages, indent=4)[:4000])

    def get_latest_model(self, prefix):
        """get the latest model that starts with the prefix"""
        models = self.fetch_available_models()
        latest_model = None
        for model in models:
            if model.startswith(prefix):
                latest_model = model
        return latest_model

    @listen_to(r"^@s .+", regexp_flag=re_DOTALL)
    @listen_to(r"^@sonnet .+", regexp_flag=re_DOTALL)
    async def chat_sonnet(self, message: Message):
        """alias for a specific model: claude-3-7-sonnet-"""
        # await self.helper.log(f"@sonnet from {message.sender_name}")
        model = self.get_latest_model("claude-3-7-sonnet-")
        if model is None:
            self.driver.reply_to(message, "No sonnet models found. Please try again later.")
            return
        return await self.chat(message, model)

    @listen_to(r"^@claude .+", re_DOTALL)
    async def chat(self, message: Message, model: str = None):
        """listen to everything and respond when mentioned"""
        # fetch the latest sonnet3.7 model
        if model is None:
            model = self.get_latest_model("claude-3-7-sonnet-")
        if model is None:
            model = self.get_anthropic_setting("model") or self.DEFAULT_MODEL
        # if message is not from a user, ignore
        # await self.helper.log(f"chat from {message.sender_name} to {model}")
        if not self.users.is_user(message.sender_name):
            return

        # message text exceptions. bail if message starts with any of these
        for skip in [".", "!", "ollama"]:
            if message.text.lower().startswith(skip):
                return

        # This function checks if the thread exists in valkey and if not,
        # fetches all posts in the thread and adds them to valkey
        thread_id = message.reply_id
        messages = []
        messages = self.get_thread_messages(thread_id)
        if len(messages) != 1:
            # remove mentions of self
            message.text = self.helper.strip_self_username(message.text)
            # await self.helper.log(f"Retrieved {len(messages)} messages for thread {thread_id}")
            # remove mentions of self from self.names
            for name in self.names:
                message.text = message.text.replace(f"{name} ", "")
                message.text = message.text.replace(f"{name}", "")
            # we don't need to append if length = 1 because then it is already
            # fetched via the mattermost api so we don't need to append it to the thread
            # append message to threads
            # check if the last message was of type role user if
            # so append to it instad of creating a new message
            if messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n" + message.text
            else:
                message_append = {"role": "user", "content": message.text}
                # append to messages and valkey
                messages.append(message_append)
                self.thread_append(thread_id, message_append)

        # add thought balloon to show assistant is thinking
        self.driver.react_to(message, "thought_balloon")
        # set the full message to empty string so we can append to it later
        full_message = ""
        # post_prefix is so we can add the sender name to the message to prevent
        # confusion as to who the reply is to
        post_prefix = f"({model}) @{message.sender_name}: "

        # lets create a message to send to the user that we can update
        # as we get more messages from anthropic
        reply_msg_id = self.driver.reply_to(message, full_message)["id"]

        # self.helper.debug(f"reply_msg_id: {reply_msg_id}")
        # get current time and set that as last_update_time
        last_update_time = time.time()
        # get the setting for how often to update the message
        stream_update_delay_ms = float(
            self.get_anthropic_setting("stream_update_delay_ms")
        )
        i = 0
        try:
            # await self.helper.log("Messages being sent to Anthropic API:")
            # for idx, msg in enumerate(messages):
            #    await self.helper.log(f"Message {idx}: Role: {msg['role']}, Content: {msg['content'][:50]}...")
            async with aclient.with_options(max_retries=5).messages.stream(
                max_tokens=self.MAX_TOKENS_PER_MODEL[model],
                messages=messages,
                system=self.get_anthropic_setting("system").replace("\n", " "),
                model=model,
                temperature=float(self.get_anthropic_setting("temperature")),
            ) as stream:
                async for text in stream.text_stream:
                    # await self.helper.debug(text)
                    # self.driver.reply_to(message, chunk_message.content)
                    # if the message has content, add it to the full message
                    if text:
                        full_message += text
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
        except (
            BadRequestError,
            APIStatusError,
            APIError,
            APIConnectionError,
            APITimeoutError,
        ) as anthropic_exception:
            exception_type = type(anthropic_exception).__name__
            await self.helper.debug(
                f"Exception {exception_type}: {pformat(anthropic_exception)}"
            )
            # update the message to show the error
            self.driver.posts.patch_post(
                reply_msg_id,
                {
                    "message": f"{post_prefix}{full_message}\n\
Exception {exception_type}: {pformat(anthropic_exception)}"
                },
            )
            # post reaction to message
            self.driver.reactions.delete_reaction(
                self.driver.user_id, message.id, "thought_balloon"
            )
            self.driver.react_to(message, "x")
            await self.helper.log(
                f"User: {message.sender_name} used {model} but got an exception"
            )

            # bail out of the function so we don't append to
            # the chatlog
            return

        # update the message a final time to make sure we have the full message
        self.driver.posts.patch_post(
            reply_msg_id, {"message": f"{post_prefix}{full_message}"}
        )

        # add response to chatlog
        self.thread_append(
            thread_id, {"role": "assistant", "content": full_message})

        # remove thought balloon after successful response
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, "thought_balloon"
        )

        await self.helper.log(f"User: {message.sender_name} used {model}")

    def append_thread_and_get_messages(self, thread_id, msg):
        """append a message to a chatlog"""
        # self.helper.slog(f"append_chatlog {thread_id} {msg}")
        expiry = 60 * 60 * 24 * 7
        thread_key = VALKEY_PREPEND + thread_id
        self.valkey.rpush(thread_key, self.valkey_serialize_json(msg))
        self.valkey.expire(thread_key, expiry)
        messages = self.helper.valkey_deserialize_json(
            self.valkey.lrange(thread_key, 0, -1)
        )
        return messages

    def get_thread_messages_from_valkey(self, thread_id):
        """get a chatlog"""
        thread_key = VALKEY_PREPEND + thread_id
        messages = self.helper.valkey_deserialize_json(
            self.valkey.lrange(thread_key, 0, -1)
        )
        return messages

    @staticmethod
    def valkey_serialize_json(msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""
        # return json.dumps(msg)
        return jsonpickle.encode(msg, unpicklable=False)

    @staticmethod
    def valkey_deserialize_json(msg):
        """deserialize a message from json"""
        if isinstance(msg, list):
            return [jsonpickle.decode(m) for m in msg]
        return jsonpickle.decode(msg)


if __name__ == "__main__":
    Anthropic()
