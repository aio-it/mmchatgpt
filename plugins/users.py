from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
import datetime
from environs import Env
from plugins.helper import Helper
env = Env()

ADMINS = []  # put admins in here to prepopulate the redis db
MM_BOT_ADMINS = env.list("MM_BOT_ADMINS", ADMINS)
# merge admins
ADMINS = ADMINS + MM_BOT_ADMINS
USERS = []  # put users in here to prepopulate the redis db
MM_BOT_USERS = env.list("MM_BOT_USERS", USERS)
# merge users
USERS = USERS + MM_BOT_USERS
NEEDWHITELIST = False  # if true only users in the users can use the bot
MM_BOT_USERS_NEEDWHITELIST = env.bool(
    "MM_BOT_USERS_NEEDWHITELIST", NEEDWHITELIST)


class UserNotFound(Exception):
    """user not found exception"""

    pass


class Users(Plugin):
    """manage users"""

    def __init__(self, driver: Driver = None, plugin_manager: PluginManager = None, settings: Settings = None):
        if (driver is not None) and (plugin_manager is not None) and (settings is not None):
            self.initialize(driver, plugin_manager, settings)

    def initialize(
        self,
        driver: Driver,
        plugin_manager: PluginManager,
        settings: Settings,
    ):
        """initialize"""
        self.driver = driver
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.helper = Helper(self.driver)
        self.redis = self.helper.redis
        # add admins and users to redis
        # walk through ADMINS
        for admin in ADMINS:
            # check if admin is already in redis
            try:
                uid = self.get_uid(admin)
            except UserNotFound:
                self.helper.slog(
                    f"unable to add admin. User not found: {admin}")
            if self.redis.sismember("admins", uid):
                continue
            if uid is not None:
                self.redis.sadd("admins", uid)
            else:
                self.helper.slog(f"Admin not found: {admin}")
        # walk through USERS
        for user in USERS:
            # check if user is already in redis
            try:
                uid = self.get_uid(user)
            except UserNotFound:
                self.helper.slog(f"unable to add user. User not found: {user}")
            if self.redis.sismember("users", uid):
                continue
            if uid is not None:
                self.redis.sadd("users", uid)
            else:
                self.helper.slog(f"User not found: {user}")
        self.helper.slog(f"Plugin initialized {self.__class__.__name__}")
        # log admins
        self.helper.slog(f"Admins: {self.redis.smembers('admins')}")
        # log users
        self.helper.slog(f"Users: {self.redis.smembers('users')}")

    def on_start(self):
        """on start"""
        # self.log("ChatGPT Bot started")
        # self.log("model: " + self.model)
        # convert all admins usernames to user ids and save to redis
        for admin in self.redis.smembers("admins"):
            # check if it is already a uid
            if self.check_if_username_or_id(admin) == "uid":
                continue
            # replace current admin username with uid in redis
            self.redis.srem("admins", admin)
            try:
                uid = self.get_uid(admin)
                self.redis.sadd("admins", uid)
            except UserNotFound:
                # user not found must be wrong. delete him.
                self.redis.srem("admins", admin)

        # convert all users usernames to user ids and save to redis
        for user in self.redis.smembers("users"):
            # check if it is already a uid
            if self.check_if_username_or_id(user) == "uid":
                continue
            # replace current user username with uid in redis
            self.redis.srem("users", user)
            try:
                uid = self.get_uid(user)
                self.redis.sadd("users", uid)
            except UserNotFound:
                self.redis.srem("users", user)

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
        """on stop"""
        pass

    def is_user(self, username):
        """check if user is user"""
        # check if user is banned
        if self.redis.exists(f"ban:{self.u2id(username)}"):
            return False
        if NEEDWHITELIST == False:
            return True
        return True if self.u2id(username) in self.redis.smembers("users") else False

    def is_admin(self, username):
        """check if user is admin"""
        # convert username to uid
        return True if self.u2id(username) in self.redis.smembers("admins") else False

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
            raise UserNotFound(f"User not found: {username}")
        # cache the uid in redis for 10 hours
        if uid != None:
            self.redis.set(f"uid:{username}", uid, ex=10 * 60 * 60)
        return uid

    @listen_to(r"\.uid ([a-zA-Z0-9_-]+)")
    async def uid(self, message: Message, username: str):
        """get user id from username"""
        if self.is_admin(message.sender_name):
            self.driver.reply_to(message, self.get_uid(username))

    @listen_to(r"^\.banlist")
    async def banlist(self, message: Message):
        """list banned users"""
        if self.is_admin(message.sender_name):
            # list banned users
            bans = ""
            for key in self.redis.scan_iter("ban:*"):
                # get time left for ban
                uid = key.split(":")[1]
                user = self.id2u(uid)
                time = self.redis.get(key)
                timeleft = self.redis.ttl(key)
                if timeleft > 0:
                    # convert seconds to timeleft string
                    timeleft = str(datetime.timedelta(seconds=timeleft))
                    bans += f"{user} ban: {time} days.  left: {timeleft}\n"
                else:
                    bans += f"{user} - permanent\n"
            self.driver.reply_to(message, f"Bans:\n{bans}")

    def ban_user(self, username, days=0, hours=0, minutes=0, seconds=0):
        """ban user"""
        # check if user is admin
        if self.is_admin(username):
            return False
        # ban user
        uid = self.u2id(username)
        if days == 0:
            self.redis.set(f"ban:{uid}", 0)
        else:
            # calc ban time in seconds
            days = int(days)
            hours = int(hours)
            minutes = int(minutes)
            seconds = int(seconds)
            seconds += minutes * 60
            seconds += hours * 60 * 60
            seconds += days * 24 * 60 * 60
            self.redis.set(f"ban:{uid}", seconds, ex=seconds)
            return True

    def nohl(self, user):
        """prevent highlighting the user by adding a zero width space to the username after the first letter"""
        return user[0] + "\u200B" + user[1:]

    @listen_to(r"^\.ban ([a-zA-Z0-9_-]+) ?([0-9]?)")
    async def ban(self, message: Message, user, days=0):
        """ban user"""
        days = int(days)
        if self.is_admin(message.sender_name):
            # check if user is admin
            if self.is_admin(user):
                self.driver.reply_to(message, f"Can't ban admin: {user}")
                return
            # ban user
            # check if user exists
            if self.get_user_by_username(user) is None:
                self.driver.reply_to(message, f"User not found: {user}")
                return
            if days == 0:
                self.driver.reply_to(message, f"Banned {user} forever")
                self.ban_user(user)
            else:
                self.driver.reply_to(message, f"Banned {user} for {days} days")
                self.ban_user(user, days)
            await self.log(f"{message.sender_name} banned {user} for {days} days")

    @listen_to(r"^\.unban ([a-zA-Z0-9_-]+)")
    async def unban(self, message: Message, user):
        """unban user"""
        if self.is_admin(message.sender_name):
            # check if user exists
            if self.get_user_by_username(user) is None:
                self.driver.reply_to(message, f"User not found: {user}")
                return
            # check if user is banned
            if not self.redis.exists(f"ban:{self.u2id(user)}"):
                self.driver.reply_to(message, f"User not banned: {user}")
                return
            # unban user
            uid = self.u2id(user)
            self.driver.reply_to(message, f"Unbanned {user}")
            self.redis.delete(f"ban:{uid}")
            await self.log(f"{message.sender_name} unbanned {user}")

    @listen_to(r"^\.users remove (.+)")
    async def users_remove(self, message: Message, username: str):
        """remove user"""
        if self.is_admin(message.sender_name):
            # convert username to uid
            uid = self.u2id(username)
            self.redis.srem("users", uid)
            self.driver.reply_to(message, f"Removed user: {username} ({uid})")
            await self.log(f"Removed user: {username} ({uid})")

    @listen_to(r"^\.users add (.+)")
    async def users_add(self, message: Message, username: str):
        """add user"""
        if self.is_admin(message.sender_name):
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
        if self.is_admin(message.sender_name):
            # loop through all users and get their usernames
            users = ""
            for user in self.redis.smembers("users"):
                users += f"{self.nohl(self.id2u(user))} ({user})\n"
            self.driver.reply_to(message, f"Allowed users:\n{users}")

    @listen_to(r"^\.admins add (.*)")
    async def admins_add(self, message: Message, username: str):
        """add admin"""
        if self.is_admin(message.sender_name):
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
        if self.is_admin(message.sender_name):
            self.redis.srem("admins", self.u2id(username))
            self.driver.reply_to(message, f"Removed admin: {username}")

    @listen_to(r"^\.admins list")
    async def admins_list(self, message: Message):
        """list the admins"""
        if self.is_admin(message.sender_name):
            # get a list of all admins and convert their uids to usernames
            admins = ""
            for admin in self.redis.smembers("admins"):
                admins += f"{self.id2u(admin)} ({admin})\n"
            self.driver.reply_to(message, f"Allowed admins:\n{admins}")
