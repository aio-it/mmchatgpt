"""users plugin"""

import datetime

from environs import Env
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message

from plugins.helper import Helper

env = Env()

ADMINS = []  # put admins in here to prepopulate the valkey db
MM_BOT_ADMINS = env.list("MM_BOT_ADMINS", ADMINS)
# merge admins
ADMINS = ADMINS + MM_BOT_ADMINS
USERS = []  # put users in here to prepopulate the valkey db
MM_BOT_USERS = env.list("MM_BOT_USERS", USERS)
# merge users
USERS = USERS + MM_BOT_USERS
NEEDWHITELIST = False  # if true only users in the users can use the bot
MM_BOT_USERS_NEEDWHITELIST = env.bool(
    "MM_BOT_USERS_NEEDWHITELIST", NEEDWHITELIST)


class UserNotFound(Exception):
    """user not found exception"""


class TooManyUsersFound(Exception):
    """too many users found exception"""
class UserIsSystem(Exception):
    """user is system exception and they dont have an id"""


class Users(Plugin):
    """manage users"""
    # pylint: disable=super-init-not-called
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
        self.valkey = self.helper.valkey
        # add admins and users to valkey
        # walk through ADMINS
        for admin in ADMINS:
            # check if admin is already in valkey
            try:
                uid = self.get_uid(admin)
            except UserNotFound:
                self.helper.slog(
                    f"unable to add admin. User not found: {admin}")
            if self.valkey.sismember("admins", uid):
                continue
            if uid is not None:
                self.valkey.sadd("admins", uid)
            else:
                self.helper.slog(f"Admin not found: {admin}")
        # walk through USERS
        for user in USERS:
            # check if user is already in valkey
            try:
                uid = self.get_uid(user)
            except UserNotFound:
                self.helper.slog(f"unable to add user. User not found: {user}")
            if self.valkey.sismember("users", uid):
                continue
            if uid is not None:
                self.valkey.sadd("users", uid)
            else:
                self.helper.slog(f"User not found: {user}")
        self.helper.slog(f"Plugin initialized {self.__class__.__name__}")
        # log admins
        self.helper.slog(f"Admins: {self.valkey.smembers('admins')}")
        # log users
        self.helper.slog(f"Users: {self.valkey.smembers('users')}")

    def on_start(self):
        """on start"""
        # self.log("ChatGPT Bot started")
        # self.log("model: " + self.model)
        # convert all admins usernames to user ids and save to valkey
        for admin in self.valkey.smembers("admins"):
            # check if it is already a uid
            if self.check_if_username_or_id(admin) == "uid":
                continue
            # replace current admin username with uid in valkey
            self.valkey.srem("admins", admin)
            try:
                uid = self.get_uid(admin)
                self.valkey.sadd("admins", uid)
            except UserNotFound:
                # user not found must be wrong. delete him.
                self.valkey.srem("admins", admin)

        # convert all users usernames to user ids and save to valkey
        for user in self.valkey.smembers("users"):
            # check if it is already a uid
            if self.check_if_username_or_id(user) == "uid":
                continue
            # replace current user username with uid in valkey
            self.valkey.srem("users", user)
            try:
                uid = self.get_uid(user)
                self.valkey.sadd("users", uid)
            except UserNotFound:
                self.valkey.srem("users", user)

        # convert all bans usernames to user ids and save to valkey
        for key in self.valkey.scan_iter("ban:*"):
            user = key.split(":")[1]
            # check if it is already a uid
            if self.check_if_username_or_id(user) == "uid":
                continue
            # get expire time
            expire = self.valkey.ttl(key)
            # replace current ban username with uid in valkey
            self.valkey.delete(key)
            self.valkey.set(f"ban:{self.get_uid(user)}", expire)

    def on_stop(self):
        """on stop"""

    def is_user(self, username):
        """check if user is user"""
        # check if user is banned
        if self.valkey.exists(f"ban:{self.u2id(username)}"):
            return False
        if NEEDWHITELIST is False:
            return True
        return True if self.u2id(username) in self.valkey.smembers("users") else False

    def is_admin(self, username):
        """check if user is admin"""
        # convert username to uid
        return True if self.u2id(username) in self.valkey.smembers("admins") else False

    def u2id(self, username):
        """convert username to uid"""
        return self.get_uid(username)

    def id2u(self, user_id):
        """convert uid to username"""
        return self.get_user_by_user_id(user_id)["username"]
    def id2unhl(self, user_id):
        """convert uid to username without highlighting"""
        return self.nohl(self.get_user_by_user_id(user_id)["username"])
    def check_if_username_or_id(self, username_or_id):
        """check if username or id"""
        try:
            user = self.get_user_by_username(username_or_id)["username"]
        # pylint: disable=broad-except
        except Exception:
            user = None
        try:
            uid = self.get_user_by_user_id(username_or_id)["id"]
        # pylint: disable=broad-except
        except Exception:
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
        # check if user is cached in valkey
        if self.valkey.exists(f"user:{username}"):
            return self.helper.valkey_deserialize_json(self.valkey.get(f"user:{username}"))
        users = self.driver.users.get_users_by_usernames([username])
        if len(users) == 1:
            # cache the user in valkey for 1 hour
            self.valkey.set(
                f"user:{username}", self.helper.valkey_serialize_json(users[0]), ex=60 * 60
            )
            return users[0]
        if len(users) > 1:
            # throw exception if more than one user is found
            raise TooManyUsersFound(
                f"More than one user found: {users} this is undefined behavior"
            )
        return None

    def get_user_by_user_id(self, user_id):
        """get user id from user_id"""
        # check if user is cached in valkey
        if self.valkey.exists(f"user:{user_id}"):
            return self.helper.valkey_deserialize_json(self.valkey.get(f"user:{user_id}"))
        try:
            user = self.driver.users.get_user(user_id)
            # cache the user in valkey for 1 hour
            self.valkey.set(
                f"user:{user_id}", self.helper.valkey_serialize_json(user), ex=60 * 60
            )
            return user
        # pylint: disable=broad-except
        except Exception:
            return None

    def get_uid(self, username, force=False):
        """get uid from username"""
        if username == "System":
            raise UserIsSystem(f"User is system and does not have an id")
        # check if uid is cached in valkey
        if not force and self.valkey.exists(f"uid:{username}"):
            return self.valkey.get(f"uid:{username}")
        try:
            uid = self.get_user_by_username(username)["id"]
        # pylint: disable=broad-except
        except Exception as e:
            # uid not found
            uid = None
            # throw exception if user is not found
            raise UserNotFound(f"User not found: {username}") from e
        # cache the uid in valkey for 10 hours
        if uid is not None:
            self.valkey.set(f"uid:{username}", uid, ex=10 * 60 * 60)
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
            for key in self.valkey.scan_iter("ban:*"):
                # get time left for ban
                uid = key.split(":")[1]
                user = self.id2u(uid)
                time = self.valkey.get(key)
                timeleft = self.valkey.ttl(key)
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
            self.valkey.set(f"ban:{uid}", 0)
        else:
            # calc ban time in seconds
            days = int(days)
            hours = int(hours)
            minutes = int(minutes)
            seconds = int(seconds)
            seconds += minutes * 60
            seconds += hours * 60 * 60
            seconds += days * 24 * 60 * 60
            self.valkey.set(f"ban:{uid}", seconds, ex=seconds)
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
            await self.helper.log(
                f"{message.sender_name} banned {user} for {days} days"
            )

    @listen_to(r"^\.unban ([a-zA-Z0-9_-]+)")
    async def unban(self, message: Message, user):
        """unban user"""
        if self.is_admin(message.sender_name):
            # check if user exists
            if self.get_user_by_username(user) is None:
                self.driver.reply_to(message, f"User not found: {user}")
                return
            # check if user is banned
            if not self.valkey.exists(f"ban:{self.u2id(user)}"):
                self.driver.reply_to(message, f"User not banned: {user}")
                return
            # unban user
            uid = self.u2id(user)
            self.driver.reply_to(message, f"Unbanned {user}")
            self.valkey.delete(f"ban:{uid}")
            await self.helper.log(f"{message.sender_name} unbanned {user}")

    @listen_to(r"^\.users remove (.+)")
    async def users_remove(self, message: Message, username: str):
        """remove user"""
        if self.is_admin(message.sender_name):
            # convert username to uid
            uid = self.u2id(username)
            self.valkey.srem("users", uid)
            self.driver.reply_to(message, f"Removed user: {username} ({uid})")
            await self.helper.log(f"Removed user: {username} ({uid})")

    @listen_to(r"^\.users add (.+)")
    async def users_add(self, message: Message, username: str):
        """add user"""
        if self.is_admin(message.sender_name):
            # check if user exists
            if self.get_user_by_username(username) is None:
                self.driver.reply_to(message, f"User not found: {username}")
                return
            self.valkey.sadd("users", self.u2id(username))
            self.driver.reply_to(
                message, f"Added user: {username} ({self.u2id(username)})"
            )

    @listen_to(r"^\.users list")
    async def users_list(self, message: Message):
        """list the users"""
        if self.is_admin(message.sender_name):
            # loop through all users and get their usernames
            users = ""
            for user in self.valkey.smembers("users"):
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
            self.valkey.sadd("admins", uid)
            self.driver.reply_to(message, f"Added admin: {username}")

    @listen_to(r"^\.admins remove (.*)")
    async def admins_remove(self, message: Message, username: str):
        """remove admin"""
        if self.is_admin(message.sender_name):
            self.valkey.srem("admins", self.u2id(username))
            self.driver.reply_to(message, f"Removed admin: {username}")

    @listen_to(r"^\.admins list")
    async def admins_list(self, message: Message):
        """list the admins"""
        if self.is_admin(message.sender_name):
            # get a list of all admins and convert their uids to usernames
            admins = ""
            for admin in self.valkey.smembers("admins"):
                admins += f"{self.id2u(admin)} ({admin})\n"
            self.driver.reply_to(message, f"Allowed admins:\n{admins}")
