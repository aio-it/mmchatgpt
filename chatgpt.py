"""ChatGPT plugin for mmpy_bot"""
import os
import subprocess
import time
import json
import openai
import redis
import aiohttp.client_exceptions as aiohttp_client_exceptions
import tiktoken

import ping3
import ipaddress
import regex as re

# import serialized_redis
from mmpy_bot import Plugin, listen_to
from mmpy_bot import Message
from redis_rate_limit import RateLimit, TooManyRequests

MODEL = "gpt-3.5-turbo-0301"
ADMINS = []  # put admins in here to prepopulate the redis db
USERS = []  # put users in here to prepopulate the redis db
REDIS_PREPEND = "thread_"
PRICE_PER_TOKEN = 0.002/1000
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

    def __init__(self, openai_api_key=None, log_channel=None):
        super().__init__()
        self.name = "ChatGPT"
        self.redis = redis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True)
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
            if 'content' in message_obj:
                content = message_obj["content"]
                message_length_in_tokens = len(
                    self.string_to_tokens(content, model=self.model))

                if current_length_in_tokens + message_length_in_tokens <= max_length_in_tokens:
                    current_length_in_tokens += message_length_in_tokens
                    limited_messages.append(message_obj)
                else:
                    break

        return list(reversed(limited_messages))

    @listen_to(r"^\.s2t (.*)")  # , re.MULTILINE | re.IGNORECASE)
    async def string_to_tokens_bot(self, message, string):
        """convert a string to tokens"""
        tokens = self.string_to_tokens(string, model=self.model)
        string_from_tokens = self.tokens_to_string(tokens, model=self.model)
        tokens_to_list_of_bytestrings = self.tokens_to_list_of_strings(tokens)
        tokens_to_list_of_strings = [bytestring.decode(
            'utf-8') for bytestring in tokens_to_list_of_bytestrings]

        await self.driver.reply_to(message,
                                   f"tokens length: {len(tokens)}\n\
                tokens: {tokens}\n\
                token strings: {tokens_to_list_of_strings}\n\
                string length: {len(string)}\n\
                original string: {string}\n\
                string length from tokens: {len(string_from_tokens)}\n\
                string from tokens: {string_from_tokens}",
                                   )

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
        return True if username in self.redis.smembers("users") else False

    def is_admin(self, username):
        """check if user is admin"""
        return True if username in self.redis.smembers("admins") else False

    async def wall(self, message):
        """send message to all admins"""
        for admin in self.redis.smembers("admins"):
            self.driver.direct_message(receiver_id=self.get_user_by_username(admin)['id'],
                                       message=message)

    async def log(self, message: str):
        """send message to log channel"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)

    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        if self.log_to_channel and not private:
            self.log(f"DEBUG: {message}")
        elif not self.log_to_channel and private:
            self.wall(f"DEBUG: {message}")

    @listen_to(r"^\.usage")
    async def usage(self, message: Message):
        """reply with usage"""
        if self.is_admin(message.sender_name):
            users = self.redis.hkeys("usage")
            for user in users:
                if user == message.sender_name:
                    continue
                usage = self.get_usage_for_user(user)
                self.driver.reply_to(message,
                                     f"{user} Usage:\n\tCount: {usage['usage']}\n\tTokens: {usage['tokens']}\n\tPrice: {(float(usage['tokens'])*PRICE_PER_TOKEN)*DOLLAR_TO_DKK}kr",
                                     direct=True)

        usage = self.get_usage_for_user(message.sender_name)
        self.driver.reply_to(message,
                             f"{message.sender_name} Usage:\n\tCount: {usage['usage']}\n\tTokens: {usage['tokens']}\n\tPrice: {(float(usage['tokens'])*PRICE_PER_TOKEN)*DOLLAR_TO_DKK}kr")

    @listen_to(r"^\.users remove (.+)")
    async def users_remove(self, message: Message, username: str):
        """remove user"""
        if self.is_admin(message.sender_name):
            self.redis.srem("users", username)
            self.driver.ry_toepl(message, f"Removed user: {username}")
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
                message, f"Allowed users: {self.redis.smembers('users')}")

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
                message, f"Allowed admins: {self.redis.smembers('admins')}")

    @listen_to(r"^\.models list")
    async def model_list(self, message: Message):
        """list the models"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(
                message, f"Allowed models: {self.ALLOWED_MODELS}")

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

    @listen_to(r"^\.clear")
    async def clear(self, message: Message):
        """clear the chatlog"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(message, "Chatlog cleared")

    @listen_to(r"^\.getchatlog")
    async def getchatlog(self, message: Message):
        """get the chatlog"""
        if self.is_admin(message.sender_name):
            thread_id = message.reply_id
            thread_key = REDIS_PREPEND+thread_id
            chatlog = self.redis_deserialize_json(
                self.redis.lrange(thread_key, 0, -1))
            if self.get_chatgpt_setting("system") != "":
                chatlog.insert(
                    0, {"role": "system", "content": self.get_chatgpt_setting("system")})
            chatlogmsg = ""
            for msg in chatlog:
                chatlogmsg += f"{msg['role']}: {msg['content']}\n"
            self.driver.reply_to(message, chatlogmsg)

    @listen_to(r"^\.mkimg (.*)")
    async def mkimg(self, message: Message, text: str):
        """use the openai module to get and image from text"""
        if self.is_user(message.sender_name):
            try:
                with RateLimit(resource="mkimg", client=message.sender_name, max_requests=1, expire=5):
                    response = openai.Image.create(
                        prompt=text,
                        n=1,
                        size="1024x1024"
                    )
                    image_url = response['data'][0]['url']
                    await self.debug(response)
                    self.driver.reply_to(message, image_url)
                    await self.log(f"{message.sender_name} used .mkimg")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/5s)")
            except openai.error.InvalidRequestError as error:
                self.driver.reply_to(message, f"Error: {error}")
            except:  # pylint: disable=bare-except
                self.driver.reply_to(message, "Error: OpenAI API error")

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
                        message, f"{key}: {self.redis.hget(settings_key, key)}")
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
        stream = True if self.get_chatgpt_setting(
            "stream") == 'true' else False
        msg = message.text
        thread_id = message.reply_id
        thread_key = REDIS_PREPEND+thread_id
        # check if thread exists in redis
        messages = []
        if self.redis.exists(thread_key):
            messages = self.append_chatlog(
                thread_id, {"role": "user", "content": msg})
        else:
            # thread does not exist, fetch all posts in thread
            thread = self.driver.get_post_thread(thread_id)
            for thread_index in thread['order']:
                thread_post = thread['posts'][thread_index]
                # remove mentions of self
                thread_post['message'] = thread_post['message'].replace(
                    "@" + self.driver.client.username + ' ', '')
                # if post is from self, set role to assistant
                if self.driver.client.userid == thread_post['user_id']:
                    role = "assistant"
                else:
                    # post is from user, set role to user
                    role = "user"

                # self.redis.rpush(thread_key, self.redis_serialize_json(
                #    {"role": role, "content": thread_post['message']}))
                messages = self.append_chatlog(
                    thread_id, {"role": role, "content": thread_post['message']})
        # add system message
        if self.get_chatgpt_setting("system") != "":
            messages.insert(
                0, {"role": "system", "content": self.get_chatgpt_setting("system")})
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
                        messages, self.MAX_TOKENS_PER_MODEL[self.model]),
                    temperature=temperature,
                    top_p=top_p,
                    stream=stream,
                )
                # check for error in the responses and send error message
                if "error" in response:
                    if "message" in response:
                        self.driver.reply_to(
                            message, f"Error: {response['message']}")
                    else:
                        self.driver.reply_to(message, "Error")
                    # remove thought balloon
                    self.driver.reactions.delete_reaction(
                        self.driver.user_id, message.id, "thought_balloon")
                    # add x reaction to the message that failed to show error
                    self.driver.react_to(message, "x")
                    return
            except openai.error.InvalidRequestError as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon")
                self.driver.react_to(message, "x")
                return
            except openai.error.RateLimitError as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon")
                self.driver.react_to(message, "x")
                return
            # self.debug(response)
            # send response to user
            self.driver.reply_to(
                message, f"@{message.sender_name}: {response.choices[0].message.content}")
            # add response to chatlog
            self.append_chatlog(thread_id, response.choices[0].message)
        else:
            # we are streaming baby
            full_message = ""
            post_prefix = f"@{message.sender_name}: "
            # post initial message as a reply and save the message id
            reply_msg_id = self.driver.reply_to(
                message, full_message)['id']
            # send async request to openai
            try:
                response = await openai.ChatCompletion.acreate(
                    model=self.model,
                    messages=self.return_last_x_messages(
                        messages, self.MAX_TOKENS_PER_MODEL[self.model]),
                    temperature=temperature,
                    top_p=top_p,
                    stream=stream,
                )
            except (openai.error.RateLimitError, openai.error.APIError) as error:
                # update the message
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"Error: {error}"})
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon")
                self.driver.react_to(message, "x")
                return
            # self.debug(response)

            # self.debug(f"reply_msg_id: {reply_msg_id}")
            # get current time and set that as last_update_time
            last_update_time = time.time()
            # get the setting for how often to update the message
            stream_update_delay_ms = float(
                self.get_chatgpt_setting("stream_update_delay_ms"))
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
                                message, f"Error: {response['message']}")
                        else:
                            self.driver.reply_to(message, "Error")
                        # remove thought balloon
                        self.driver.reactions.delete_reaction(
                            self.driver.user_id, message.id, "thought_balloon")
                        # add x reaction to the message that failed to show error
                        self.driver.react_to(message, "x")
                        return

                    # extract the message
                    chunk_message = chunk['choices'][0]['delta']
                    # if the message has content, add it to the full message
                    if 'content' in chunk_message:
                        full_message += chunk_message['content']
                        # await self.debug((time.time() - last_update_time) * 1000)
                        if (time.time() - last_update_time) * 1000 > stream_update_delay_ms:
                            # await self.debug("updating message")
                            # update the message
                            self.driver.posts.patch_post(
                                reply_msg_id, {"message": f"{post_prefix}{full_message}"})
                            # update last_update_time
                            last_update_time = time.time()
                # update the message a final time to make sure we have the full message
                self.driver.posts.patch_post(
                    reply_msg_id, {"message": f"{post_prefix}{full_message}"})

                # add response to chatlog
                self.append_chatlog(
                    thread_id, {"role": "assistant", "content": full_message})
            except aiohttp_client_exceptions.ClientPayloadError as error:
                self.driver.reply_to(message, f"Error: {error}")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon")
                self.driver.react_to(message, "x")
                return

        # remove thought balloon after successful response
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, "thought_balloon")

        if not stream:
            # add usage for user
            # TODO: add per model usage
            self.add_usage_for_user(message.sender_name,
                                    response['usage']['total_tokens'])
            # log usage for user
            await self.log(
                f"User: {message.sender_name} used {response['usage']['total_tokens']} tokens")
        else:
            await self.log(f"User: {message.sender_name} used {self.model}")

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
        code = code.split(" ")
        if self.is_admin(message.sender_name):
            try:
                resp = subprocess.run(
                    code, shell=True, text=True)
                reply = f"Executed: {code} \nResult: {resp.returncode} \nOutput: {resp.stdout} \nError: {resp.stderr}"
            except Exception as error_message:
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)

    def get_all_usage(self):
        """get all usage"""
        return {"usage": self.redis.hgetall("usage"), "tokens": self.redis.hgetall("tokens")}

    def get_usage_for_user(self, username):
        """get usage for user"""
        return {"usage": self.redis.hget("usage", username), "tokens": self.redis.hget("tokens", username)}

    def add_usage_for_user(self, username, usage):
        """add usage for user"""
        self.redis.hincrby("usage", username, 1)
        self.redis.hincrby("tokens", username, usage)

    def append_chatlog(self, thread_id, msg):
        """append a message to a chatlog"""
        expiry = 60*60*24*7
        thread_key = REDIS_PREPEND+thread_id
        self.redis.rpush(thread_key, self.redis_serialize_json(msg))
        self.redis.expire(thread_key, expiry)
        messages = self.redis_deserialize_json(
            self.redis.lrange(thread_key, 0, -1))
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
