from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
import time
import json
import aiohttp
import aiohttp.client_exceptions as aiohttp_client_exceptions
from pprint import pformat
REDIS_PREPEND = "ollama_"
class Ollama(PluginLoader):
    REDIS_PREFIX = "ollama_"
    DEFAULT_MODEL = "mistral"
    URL= "http://***REMOVED***:11434/api"
    CHAT_ENDPOINT = "/chat"
    PULL_ENDPOINT = "/pull"
    SHOW_ENDPOINT = "/show"
    TAGS_ENDPOINT = "/tags"
    DEFAULT_STREAM = True
    DEFAULT_SYSTEM_MESSAGE = ""
    DEFAULT_STREAM_DELAY = 100
    def __init__(self):
        super().__init__()
    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
        self.name = "ollama"
        if self.redis.get(self.REDIS_PREFIX + "model") is None:
            self.redis.set(self.REDIS_PREFIX + "model", self.DEFAULT_MODEL)
        self.model = self.redis.get(self.REDIS_PREFIX + "model")
        if self.redis.get(self.REDIS_PREFIX + "stream") is None:
            self.redis.set(self.REDIS_PREFIX + "stream", self.DEFAULT_STREAM)
        self.stream = self.redis.get(self.REDIS_PREFIX + "stream")
        if self.redis.get(self.REDIS_PREFIX + "system_message") is None:
            self.redis.set(self.REDIS_PREFIX + "system_message", self.DEFAULT_SYSTEM_MESSAGE)
        self.system_message = self.redis.get(self.REDIS_PREFIX + "system_message")
        if self.redis.get(self.REDIS_PREFIX + "stream_delay") is None:
            self.redis.set(self.REDIS_PREFIX + "stream_delay", self.DEFAULT_STREAM_DELAY)
        self.stream_delay = self.redis.get(self.REDIS_PREFIX + "stream_delay")
        self.helper.slog(f"model: {self.model}")
        self.helper.slog(f"stream: {self.stream}")
        self.helper.slog(f"system_message: {self.system_message}")
        self.helper.slog(f"stream_delay: {self.stream_delay}ms")
    @listen_to(r"^\.ollama help")
    async def ollama_help(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"commands: model set/get/show/pull/list, stream enable/disable, stream delay get/set, system_message set/get")
    @listen_to(r"^\.ollama stream disable")
    async def ollama_stream_disable(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.redis.set(self.REDIS_PREFIX + "stream", 0)
            self.stream = 0
            self.driver.reply_to(message, f"streaming disabled")
    @listen_to(r"^\.ollama stream enable")
    async def ollama_stream_enable(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.redis.set(self.REDIS_PREFIX + "stream", 1)
            self.stream = 1
            delay = self.redis.get(self.REDIS_PREFIX + "stream_delay")
            self.driver.reply_to(message, f"streaming enabled. delay: {delay}ms")
    @listen_to(r"^\.ollama stream delay set ([\s\S]*)")
    async def ollama_stream_delay_set(self, message: Message, delay: str):
        if self.users.is_admin(message.sender_name):
            self.redis.set(self.REDIS_PREFIX + "stream_delay", delay)
            self.stream_delay = delay
            self.driver.reply_to(message, f"stream delay set to: {delay}ms")
    @listen_to(r"^\.ollama model show ([\s\S]*)")
    async def ollama_model_show(self, message: Message, model: str):
        if self.users.is_admin(message.sender_name):
            try:
                data = {
                    "name": model,
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.URL + self.SHOW_ENDPOINT, json=data) as response:
                        obj = await response.json(content_type=None)
                        modeltxt = f"model info:\n{pformat(obj)}"
                        self.driver.reply_to(message, modeltxt)
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.helper.add_reaction(message, "x")
    @listen_to (r"^\.ollama model list")
    async def ollama_model_list(self, message: Message):
        if self.users.is_admin(message.sender_name):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.URL + self.TAGS_ENDPOINT) as response:
                        obj = await response.json(content_type=None)
                        modeltxt = "models:\n"
                        if "models" in obj:
                            for model in obj["models"]:
                                name = model["name"]
                                size = model["size"]
                                modified_at = model["modified_at"]
                                modeltxt += f"model: {name} size: {size} modified_at: {modified_at}\n"
                            self.driver.reply_to(message, modeltxt)
            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.helper.add_reaction(message, "x")
    @listen_to(r"^\.ollama model pull ([\s\S]*)")
    async def ollama_model_pull(self, message: Message, model: str):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"pulling {model}")
            data = {
            "name": model,
            "stream": False
            }
            try:
                timeout = aiohttp.ClientTimeout(total=60*60*24*7)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.URL + self.PULL_ENDPOINT, json=data) as response:
                        async for chunk in response.content.iter_any():
                            chunk = chunk.decode("utf-8")
                            # chunk contains one or more json objects, separated by newlines
                            # loop through them
                            chunk = chunk.split("\n")
                            for obj in chunk:
                                if obj == "":
                                    continue
                                obj = json.loads(obj)
                                if "status" in obj:
                                    self.driver.reply_to(message, f"{pformat(obj['status'])}")
                        self.driver.reply_to(message, f"pulled {model}")

            except Exception as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.helper.add_reaction(message, "x")
    
    @listen_to(r"^\.ollama model set ([\s\S]*)")
    async def ollama_model_set(self, message: Message, model: str):
        if self.users.is_admin(message.sender_name):
            self.redis.set(self.REDIS_PREFIX + "model", model)
            self.model = model
            self.driver.reply_to(message, f"model set to: {model}")
    @listen_to(r"^\.ollama model get")
    async def ollama_model_get(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"model: {self.redis.get(self.REDIS_PREFIX + 'model')}")
    def get_system_message(self,model):
        """get system message for model"""
        # if : is in model, get system message for model
        if ":" in model:
            model = model.split(":")[0]
        message = self.redis.get(f"{self.REDIS_PREFIX}_{model}_system_message")
        return "" if message is None else message
    def set_system_message(self,model,system_message):
        """set system message for model"""
        # if : is in model, set system message for model
        if ":" in model:
            model = model.split(":")[0]
        self.redis.set(f"{self.REDIS_PREFIX}_{model}_system_message", system_message)
    @listen_to(r"^\.ollama system_message set ([\s\S]*) ([\s\S]*)")
    async def ollama_system_message_set(self, message: Message, model: str, system_message: str):
        # if : is in model, set system message for model
        if ":" in model:
            model = model.split(":")[0]
        if self.users.is_admin(message.sender_name):
            self.set_system_message(model,system_message)
            self.driver.reply_to(message, f"system_message for {model} set to: {system_message}")
    @listen_to(r"^\.ollama system_message get ([\s\S]*)")
    async def ollama_system_message_get(self, message: Message, model: str):
        # if : is in model, get system message for model
        if ":" in model:
            model = model.split(":")[0]
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"system_message for {model}: {self.get_system_message(model)}")
    @listen_to("^bitch please")
    @listen_to("^sudo")
    @listen_to("^ollama")
    async def ollama_chat(self, message: Message):
        """listen to everything and respond when mentioned"""
        #self.driver.reply_to(message, "Hej")
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
        stream = True if self.stream == "1" else False
        msg = message.text
        # log the message if user is admin
        # if self.is_admin(message.sender_name):
        #    await self.helper.log(f"{message.sender_name}:  {pformat(message.body)}")
        thread_id = message.reply_id
        thread_key = REDIS_PREPEND + thread_id
        # check if thread exists in redis
        messages = []
        cache_thread = False
        if self.redis.exists(thread_key) and cache_thread:
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
                thread_post["message"] = thread_post["message"].replace(
                    self.name+" ", ""
                )
                # if post is from self, set role to assistant
                if self.driver.client.userid == thread_post["user_id"]:
                    role = "assistant"
                else:
                    # post is from user, set role to user
                    role = "user"

                # self.redis.rpush(thread_key, self.helper.redis_serialize_json(
                #    {"role": role, "content": thread_post['message']}))
                    msg = {"role": role, "content": thread_post["message"]}
                if cache_thread:
                    messages = self.append_chatlog(
                        thread_id, msg
                    )
                else:
                    messages.append(msg)

        # add system message
        if self.get_system_message(self.model) != "":
            messages.insert(
                0, {"role": "system", "content": self.get_system_message(self.model)}
            )
        # add thought balloon to show assistant is thinking
        self.driver.react_to(message, "thought_balloon")
        if not stream:
            try:
                data = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False
                }
                timeout = aiohttp.ClientTimeout(total=60*60*24*7)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.URL + self.CHAT_ENDPOINT, json=data) as response:
                        response = await response.json(content_type=None)
            except error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return
            # self.helper.debug(response)
            # send response to user
            if "message" in response:

                self.driver.reply_to(
                    message,
                    f"({self.model}) @{message.sender_name}: {response['message']['content']}",
                )
                # add response to chatlog
                if cache_thread:
                    self.append_chatlog(thread_id, response['message']['content'])
                else:
                    messages.append(response['message']['content'])
        else:
            # we are streaming baby
            full_message = ""
            post_prefix = f"({self.model}) @{message.sender_name}: "
            # post initial message as a reply and save the message id
            reply_msg_id = self.driver.reply_to(message, f"{self.model} working...")["id"]
            # send async request to openai
            last_update_time = time.time()
            stream_update_delay_ms = float(100)
            try:
                data = {
                  "model": self.model,
                  "messages": messages
                }
                timeout = aiohttp.ClientTimeout(total=60*60*24*7)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.URL + self.CHAT_ENDPOINT, json=data) as response:
                        #await self.helper.log(f"response: {response}")
                        async for chunks in response.content.iter_any():
                            chunks = chunks.decode("utf-8")
                            # chunk contains one or more json objects, separated by newlines
                            # loop through them
                            chunks = chunks.split("\n")
                            for chunk in chunks:
                                if chunk == "":
                                    continue
                                chunk = chunk.strip()
                                try:
                                    chunk = json.loads(chunk)
                                    if "message" not in chunk:
                                        continue
                                except json.JSONDecodeError as error:
                                    self.driver.reply_to(message, f"Error: {error}")
                                    self.driver.reactions.delete_reaction(
                                        self.driver.user_id, message.id, "thought_balloon"
                                    )
                                    self.driver.react_to(message, "x")
                                    return
                                # extract the message
                                chunk_message = chunk['message']
                                # self.driver.reply_to(message, chunk_message.content)
                                # if the message has content, add it to the full message
                                if "content" in chunk_message:
                                    full_message += chunk_message['content']
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

            
            except (aiohttp_client_exceptions.ClientConnectorError, aiohttp_client_exceptions.ClientOSError) as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return
            # update the message a final time to make sure we have the full message
            self.driver.posts.patch_post(
                reply_msg_id, {"message": f"{post_prefix}{full_message}"}
            )
            # add response to chatlog
            if cache_thread:
                self.append_chatlog(
                    thread_id, {"role": "assistant", "content": full_message}
                )

        # remove thought balloon after successful response
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, "thought_balloon"
        )

        await self.helper.log(f"User: {message.sender_name} used {self.model}")


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