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
    URL= "http://localhost:11434/api"
    CHAT_ENDPOINT = "/chat"
    PULL_ENDPOINT = "/pull"
    SHOW_ENDPOINT = "/show"
    TAGS_ENDPOINT = "/tags"
    DEFAULT_STREAM = True
    DEFAULT_SYSTEM_MESSAGE = ""
    def __init__(self):
        super().__init__()
    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
        if self.redis.get(self.REDIS_PREFIX + "model") is None:
            self.redis.set(self.REDIS_PREFIX + "model", self.DEFAULT_MODEL)
        self.model = self.redis.get(self.REDIS_PREFIX + "model")
        if self.redis.get(self.REDIS_PREFIX + "stream") is None:
            self.redis.set(self.REDIS_PREFIX + "stream", self.DEFAULT_STREAM)
        self.stream = self.redis.get(self.REDIS_PREFIX + "stream")
        if self.redis.get(self.REDIS_PREFIX + "system_message") is None:
            self.redis.set(self.REDIS_PREFIX + "system_message", self.DEFAULT_SYSTEM_MESSAGE)
        self.system_message = self.redis.get(self.REDIS_PREFIX + "system_message")
    @listen_to(r"^\.ollama stream set ([\s\S]*)")
    async def ollama_stream_set(self, message: Message, stream: str):
        if self.users.is_admin(message.sender_name):
            self.redis.set(self.REDIS_PREFIX + "stream", stream)
            self.stream = stream
            self.driver.reply_to(message, f"stream set to: {stream}")
    @listen_to(r"^\.ollama stream get")
    async def ollama_stream_get(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"stream: {self.redis.get(self.REDIS_PREFIX + 'stream')}")
    @listen_to(r"^\.ollama system_message set ([\s\S]*)")
    async def ollama_system_message_set(self, message: Message, system_message: str):
        if self.users.is_admin(message.sender_name):
            self.redis.set(self.REDIS_PREFIX + "system_message", system_message)
            self.system_message = system_message
            self.driver.reply_to(message, f"system_message set to: {system_message}")
    @listen_to(r"^\.ollama system_message get")
    async def ollama_system_message_get(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"system_message: {self.redis.get(self.REDIS_PREFIX + 'system_message')}")
    @listen_to(r"^\.ollama model show")
    async def ollama_model_show(self, message: Message):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"model: {self.model}")
    @listen_to(r"^\.ollama model pull ([\s\S]*)")
    async def ollama_model_pull(self, message: Message, model: str):
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"pulling {model}")
            data = {
            "name": model
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.URL + self.PULL_ENDPOINT, json=data) as response:
                        buffer = ""
                        async for chunk in response.content.iter_any():
                            for char in chunk.decode('utf-8'):
                                buffer += char
                                if '}' in buffer:
                                    try:
                                        self.helper.log(f"buffer: {buffer}")
                                        obj, idx = json.JSONDecoder().raw_decode(buffer)
                                        buffer = buffer[idx:].lstrip()
                                        if "status" in obj:
                                            self.driver.reply_to(message, f"status: {obj['status']}")
                                    except ValueError:
                                        # Not enough data to decode, fetch more
                                        pass
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
    @listen_to("ollama")
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
        stream = self.stream
        msg = message.text
        # log the message if user is admin
        # if self.is_admin(message.sender_name):
        #    await self.helper.log(f"{message.sender_name}:  {pformat(message.body)}")
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
        if self.system_message != "":
            messages.insert(
                0, {"role": "system", "content": self.system_message}
            )
        # add thought balloon to show assistant is thinking
        self.driver.react_to(message, "thought_balloon")
        if not stream:
            try:
                # send async request to openai
                response = await aclient.chat.completions.create(
                    model=self.model,
                    messages=messages,
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
            except error:
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
            reply_msg_id = self.driver.reply_to(message, full_message)["id"]
            # send async request to openai
            last_update_time = time.time()
            stream_update_delay_ms = float(100)
            from pprint import pformat
            try:
                data = {
                  "model": self.model,
                  "messages": messages
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.URL + self.CHAT_ENDPOINT, json=data) as response:
                        response = await response.json()
                        self.driver.reply_to(message, f"@{message.sender_name}: {pformat(response)}")
            except error:
                # update the message
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"Error: {error}"}
                )
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon"
                )
                self.driver.react_to(message, "x")
                return
            try:
                async for chunk in response:
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
                    from pprint import pformat
                    self.reply_to(message, pformat(chunk))
                    chunk_message = chunk.choices[0].delta
                    # self.driver.reply_to(message, chunk_message.content)
                    # if the message has content, add it to the full message
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
            await self.helper.log(
                f"User: {message.sender_name} used {response['usage']['total_tokens']} tokens"
            )
        else:
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
