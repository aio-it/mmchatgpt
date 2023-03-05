"""ChatGPT plugin for mmpy_bot"""
import json
import openai
import redis
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
chatgpt_defaults = {
    "temperature": 1.0,
    "system_prompt": "",
    "top_p": 1.0,
}

class ChatGPT(Plugin):
    """mmypy chatgpt plugin"""
    MODEL = "gpt-3.5-turbo-0301"
    ALLOWED_MODELS = [
        "gpt-3.5-turbo-0301",
        "gpt-3.5-turbo"
    ]

    def __init__(self, openai_api_key=None, log_channel=None):
        super().__init__()
        self.name = "ChatGPT"
        self.model = MODEL
        self.redis = redis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True)
        if self.redis.scard("admins") <= 0 and len(ADMINS) > 0:
            self.redis.sadd("admins", *ADMINS)
        if self.redis.scard("users") <= 0 and len(USERS) > 0:
            self.redis.sadd("users", *USERS)
        if self.redis.scard("admins") > 0 and len(ADMINS) > 0:
            self.redis.sadd("users", *ADMINS)
        if openai_api_key is None:
            raise Exception("No OPENAI API key provided")
        if log_channel is None:
            self.log_to_channel = False
        else:
            self.log_to_channel = True
            self.log_channel = log_channel
        openai.api_key = openai_api_key

        print(f"Allowed users: {self.redis.smembers('users')}")
        print(f"Allowed admins: {self.redis.smembers('admins')}")
        print(f"Allowed models: {self.ALLOWED_MODELS}")

    def get_user_by_username(self, username):
        """get user id from username"""
        return self.driver.users.get_user_by_username(username)

    def get_user_by_user_id(self, user_id):
        """get user id from user_id"""
        return self.driver.users.get_user(user_id)

    def on_start(self):
        """send startup message to all admins"""
        # self.send_message_to_all_admins("ChatGPT Bot started")
        # self.send_message_to_all_admins(f"price per token: {PRICE_PER_TOKEN}$")

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

    def wall(self, message):
        """send message to all admins"""
        for admin in self.redis.smembers("admins"):
            self.driver.direct_message(receiver_id=self.get_user_by_username(admin)['id'],
                                       message=message)

    def log(self, message: str):
        """send message to log channel"""
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, message)

    def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        if self.log_to_channel and not private:
            self.log(f"DEBUG: {message}")
        elif not self.log_to_channel and private:
            self.wall(f"DEBUG: {message}")

    @listen_to(".usage")
    async def usage(self, message: Message):
        """reply with usage"""
        if self.is_admin(message.sender_name):
            users = self.redis.hkeys("usage")
            for user in users:
                if user == message.sender_name:
                    continue
                usage = self.get_usage_for_user(user)
                self.driver.reply_to(message,
                                     f"{user} Usage:\n\tCount: {usage['usage']}\n\tTokens: {usage['tokens']}\n\tPrice: {(float(usage['tokens'])*PRICE_PER_TOKEN)*DOLLAR_TO_DKK}kr", direct=True)

        usage = self.get_usage_for_user(message.sender_name)
        self.driver.reply_to(message,
                             f"Usage:\n\tCount: {usage['usage']}\n\tTokens: {usage['tokens']}\n\tPrice: {(float(usage['tokens'])*PRICE_PER_TOKEN)*DOLLAR_TO_DKK}kr")

    @listen_to(".users remove (.+)")
    async def users_remove(self, message: Message, username: str):
        """remove user"""
        if self.is_admin(message.sender_name):
            self.redis.srem("users", username)
            self.driver.reply_to(message, f"Removed user: {username}")
            self.log(f"Removed user: {username}")

    @listen_to(".users add (.+)")
    async def users_add(self, message: Message, username: str):
        """add user"""
        if self.is_admin(message.sender_name):
            self.redis.sadd("users", username)
            self.driver.reply_to(message, f"Added user: {username}")

    @listen_to(".users list")
    async def users_list(self, message: Message):
        """list the users"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(
                message, f"Allowed users: {self.redis.smembers('users')}")

    @listen_to(".admins add (.*)")
    async def admins_add(self, message: Message, username: str):
        """add admin"""
        if self.is_admin(message.sender_name):
            self.redis.sadd("admins", username)
            self.driver.reply_to(message, f"Added admin: {username}")

    @listen_to(".admins list")
    async def admins_list(self, message: Message):
        """list the admins"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(
                message, f"Allowed admins: {self.redis.smembers('admins')}")

    @listen_to(".models list")
    async def model_list(self, message: Message):
        """list the models"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(
                message, f"Allowed models: {self.ALLOWED_MODELS}")

    @listen_to(".model set (.*)")
    async def model_set(self, message: Message, model: str):
        """set the model"""
        if self.is_admin(message.sender_name):
            if model in self.ALLOWED_MODELS:
                self.model = model
                self.driver.reply_to(message, f"Model set to: {model}")
            else:
                self.driver.reply_to(message, f"Model not allowed: {model}")

    @listen_to(".model get", allowed_users=["lbr"])
    async def model_get(self, message: Message):
        """get the model"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {MODEL}")

    @listen_to(".clear")
    async def clear(self, message: Message):
        """clear the chatlog"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(message, "Chatlog cleared")

    @listen_to(".getchatlog")
    async def getchatlog(self, message: Message):
        """get the chatlog"""
        if self.is_admin(message.sender_name):
            thread_id = message.reply_id
            thread_key = REDIS_PREPEND+thread_id
            chatlog = self.redis_deserialize_json(
                self.redis.lrange(thread_key, 0, -1))
            self.driver.reply_to(message, f"Chatlog: {chatlog}")

    @listen_to(".mkimg (.*)")
    async def mkimg(self, message: Message, text: str):
        """use the openai module to get and image from text"""
        if self.is_user(message.sender_name):
            try:
                with RateLimit(resource="mkimg", client=message.sender_name, max_requests=1, expire=60):
                    response = openai.Image.create(
                        prompt=text,
                        n=1,
                        size="1024x1024"
                    )
                    image_url = response['data'][0]['url']
                    self.debug(response)
                    self.driver.reply_to(message, image_url)
                    self.log(f"{message.sender_name} used .mkimg")
            except TooManyRequests:
                self.driver.reply_to(message, "Rate limit exceeded (1/60s)")
            except openai.error.InvalidRequestError as error:
                self.driver.reply_to(message, f"Error: {error}")
            except:
                self.driver.reply_to(message, "Error")

    @listen_to(".set chatgpt ([a-zA-Z0-9_-]) (.*)")
    async def set_chatgpt(self, message: Message, key: str, value: str):
        """set the chatgpt key"""
        settings_key = "chatgpt_settings"
        self.debug(f"set_chatgpt {key} {value}")
        if self.is_admin(message.sender_name):
            self.redis.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(".get chatgpt ([a-zA-Z0-9_-])")
    async def get_chatgpt(self, message: Message, key: str):
        """get the chatgpt key"""
        settings_key = "chatgpt_settings"
        self.debug(f"get_chatgpt {key}")
        if self.is_admin(message.sender_name):
            value = self.redis.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(".+", needs_mention=True)
    async def chat(self, message: Message):
        """listen to everything and respond when mentioned"""
        if not self.is_user(message.sender_name):
            return
        if message.is_direct_message and not self.is_admin(message.sender_name):
            return
        if message.text[0] == ".":  # ignore commands
            return
        msg = message.text
        thread_id = message.reply_id
        thread_key = REDIS_PREPEND+thread_id
        if self.redis.exists(thread_key):
            self.debug(f"thread exists {thread_id}")
        else:
            self.debug(
                f"thread does not exist {thread_id} fetching all posts in thread")
            thread = self.driver.get_post_thread(thread_id)
            for thread_index in thread['order']:
                thread_post = thread['posts'][thread_index]
                thread_post['message'] = thread_post['message'].replace(
                    "@" + self.driver.client.username + ' ', '')
                if self.driver.client.userid == thread_post['user_id']:
                    role = "assistant"
                else:
                    role = "user"

                self.redis.rpush(thread_key, self.redis_serialize_json(
                    {"role": role, "content": thread_post['message']}))

        messages = self.append_chatlog(
            thread_id, {"role": "user", "content": msg})
        self.driver.react_to(message, "thought_balloon")
        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
                temperature=0,
            )
            if "error" in response:
                if "message" in response:
                    self.driver.reply_to(
                        message, f"Error: {response['message']}")
                else:
                    self.driver.reply_to(message, "Error")
                self.driver.reactions.delete_reaction(
                    self.driver.user_id, message.id, "thought_balloon")
                self.driver.react_to(message, "x")
                return
        except openai.error.InvalidRequestError as error:
            self.driver.reply_to(message, f"Error: {error}")
            self.driver.reactions.delete_reaction(
                self.driver.user_id, message.id, "thought_balloon")
            self.driver.react_to(message, "x")
            return
        self.debug(response)
        self.add_usage_for_user(message.sender_name,
                                response['usage']['total_tokens'])
        self.log(
            f"User: {message.sender_name} used {response['usage']['total_tokens']} tokens")
        self.driver.reply_to(
            message, f"@{message.sender_name}: {response.choices[0].message.content}")
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, "thought_balloon")
        self.append_chatlog(thread_id, response.choices[0].message)

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
