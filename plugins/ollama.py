from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
import requests
import time
import aiohttp.client_exceptions as aiohttp_client_exceptions
class Ollama(PluginLoader):
    REDIS_PREFIX = "ollama_"
    DEFAULT_MODEL = "mistral"
    URL= "http://localhost:11434/api"
    CHAT_ENDPOINT = "/chat"
    DEFAULT_STREAM = True
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
    @listen_to("ollama", needs_mention=True)
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
        stream = True if self.get_chatgpt_setting("stream") == "true" else False
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
            # self.helper.debug(response)

            # self.helper.debug(f"reply_msg_id: {reply_msg_id}")
            # get current time and set that as last_update_time
            last_update_time = time.time()
            # get the setting for how often to update the message
            stream_update_delay_ms = float(
                self.get_chatgpt_setting("stream_update_delay_ms")
            )
            try:
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

                    # extract the message
                    from pprint import pprint

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