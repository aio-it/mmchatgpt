from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
import redis
from plugins.base import PluginLoader
from plugins.common import Helper
from plugins.users import Users
from environs import Env
env = Env()

class Pushups(PluginLoader):

    @listen_to(r"^\.pushups reset ([a-zA-Z0-9_-]+)")
    async def pushups_reset(self, message: Message, user):
        """pushups reset for user"""
        if self.helper.is_admin(message.sender_name):
            # reset pushups for user
            for key in self.redis.scan_iter(f"pushupsdaily:{user}:*"):
                self.redis.delete(key)
            for key in self.redis.scan_iter(f"pushupstotal:{user}"):
                self.redis.delete(key)
            messagetxt = f"{user} pushups reset"
            self.driver.reply_to(message, messagetxt)
            await self.helper.log(messagetxt)

    @listen_to("^\.pushups reset$")
    async def pushups_reset_self(self, message: Message):
        """pushups reset for self"""
        if self.helper.is_user(message.sender_name):
            # reset pushups for self
            for key in self.redis.scan_iter(f"pushupsdaily:{message.sender_name}:*"):
                self.redis.delete(key)
            for key in self.redis.scan_iter(f"pushupstotal:{message.sender_name}"):
                self.redis.delete(key)
            messagetxt = f"{message.sender_name} pushups reset"
            self.driver.reply_to(message, messagetxt)
            await self.helper.log(messagetxt)

    async def pushups_return_score_string(self, user):
        """return score string for user"""
        # get total pushups
        total = 0
        for key in self.redis.scan_iter(f"pushupsdaily:{user}:*"):
            total += int(self.redis.get(key))
        # get today pushups
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_key = f"pushupsdaily:{user}:{today}"
        today_pushups = int(self.redis.get(today_key))
        return f"{user} has {today_pushups} pushups today and {total} pushups total"

    @listen_to(r"^\.pushups sub ([0-9]+)")  # pushups
    async def pushups_sub(self, message: Message, pushups_sub):
        """pushups substract"""
        if self.helper.is_user(message.sender_name):
            # check if we are substracting more than we have
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            today_key = f"pushupsdaily:{message.sender_name}:{today}"
            today_pushups = int(self.redis.get(today_key))
            if int(pushups_sub) > today_pushups:
                self.driver.reply_to(
                    message,
                    f"You can't substract more pushups than you have done today ({today_pushups})",
                )
                return
            pushups_sub = int(pushups_sub)
            messagetxt = f"{message.sender_name} substracted {pushups_sub} pushups\n"
            await self.helper.log(messagetxt)
            # store pushups in redis per day
            self.redis.decr(key, pushups_sub)
            pushups_today = self.redis.get(today_key)
            messagetxt += (
                f"{message.sender_name} has done {pushups_today} pushups today\n"
            )
            # store pushups in redis total
            key = f"pushupstotal:{message.sender_name}"
            self.redis.decr(key, pushups_sub)
            pushups_total = self.redis.get(key)
            messagetxt += f"{message.sender_name} has {pushups_total} pushups total\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups ([-+]?[0-9]+)")  # pushups
    @listen_to(r"^\.pushups add ([-+]?[0-9]+)")  # pushups
    async def pushups_add(self, message: Message, pushups_add):
        """pushups"""
        if self.helper.is_user(message.sender_name):
            # check if pushups more than 1000
            pushups_add = int(pushups_add)
            if pushups_add > 1000:
                gif = "https://media.tenor.com/d0VNnBZkSUkAAAAC/bongocat-banhammer.gif"
                gif_string = f"![gif]({gif})"
                self.driver.reply_to(
                    message,
                    f"Are you the hulk? Quit your bullshit {message.sender_name}. Enjoy the 6 hour timeout :middle_finger: {gif_string}",
                )
                self.driver.react_to(message, "middle_finger")
                # ban user for 6 hours
                self.ban_user(message.sender_name, 0, 6)
                # log the ban
                await self.helper.log(
                    f"{message.sender_name} banned for 6 hours trying to bullshit their way through life"
                )
                # react hammer
                self.driver.react_to(message, "hammer")
                # reset self pushups
                # await self.pushups_reset_self(message)
                return
            messagetxt = f"{message.sender_name} did {pushups_add} pushups\n"
            await self.helper.log(f"{message.sender_name} did {pushups_add} pushups")
            # store pushups in redis per day
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            key = f"pushupsdaily:{message.sender_name}:{today}"
            self.redis.incr(key, pushups_add)
            pushups = self.redis.get(key)
            messagetxt += f"{message.sender_name} has done {pushups} pushups today\n"
            # store pushups in redis per user
            key = f"pushupstotal:{message.sender_name}"
            self.redis.incr(key, pushups_add)
            pushups = self.redis.get(key)
            messagetxt += f"{message.sender_name} has done {pushups} pushups total\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups scores$")
    async def pushups_scores(self, message: Message):
        """pushups scores for all users"""
        if self.helper.is_user(message.sender_name):
            # get pushups in redis per user
            keys = self.redis.keys("pushupstotal:*")
            messagetxt = ""
            for key in keys:
                pushups = self.redis.get(key)
                key = key.split(":")[1]
                messagetxt += f"{key} has done {pushups} pushups total\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups score$")
    async def pushups_score(self, message: Message):
        """pushups score"""
        if self.helper.is_user(message.sender_name):
            # get pushups for last 7 days and print them and a sum of those 7 days and a total
            messagetxt = ""
            today = datetime.datetime.now()
            totals_for_last_7_days = 0
            for i in range(7):
                day = today - datetime.timedelta(days=i)
                day = day.strftime("%Y-%m-%d")
                key = f"pushupsdaily:{message.sender_name}:{day}"
                pushups = self.redis.get(key)
                if pushups is None:
                    pushups = 0
                totals_for_last_7_days += int(pushups)
                messagetxt += f"{day}: {pushups}\n"
            # reverse the lines
            messagetxt = messagetxt.split("\n")
            messagetxt = messagetxt[::-1]
            messagetxt = "\n".join(messagetxt)
            messagetxt += f"\nTotal for last 7 days: {totals_for_last_7_days}\n"
            # get total pushups
            total = 0
            for key in self.redis.scan_iter(f"pushupsdaily:{message.sender_name}:*"):
                total += int(self.redis.get(key))
            messagetxt += f":weight_lifter: Alltime Total: {total}\n"
            self.driver.reply_to(message, messagetxt)
    @listen_to(r"^\.pushups$")
    @listen_to(r"^\.pushups help$")
    async def pushups_helps(self, message: Message):
        """pushups scores for all users"""
        if self.users.is_user(message.sender_name):
            # print help message
            messagetxt = f".pushups <number> - add pushups for own user\n"
            messagetxt += f".pushups add <number> - add pushups for own user\n"
            messagetxt += f".pushups sub <number> - substract pushups for own user for today and total\n"
            messagetxt += f".pushups top5 - top 5 pushups scores\n"
            messagetxt += f".pushups scores - scores for all users\n"
            messagetxt += f".pushups score - score for own user\n"
            messagetxt += f".pushups reset - reset pushups for self\n"
            messagetxt += (
                f".pushups reset <user> - reset pushups for user (admin-only)\n"
            )
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.pushups top([1-9][0-9]*)")
    async def pushups_top(self, message: Message, topcount):
        """pushups scores for all users"""
        # TODO: add streaks
        if self.users.is_user(message.sender_name):
            topcount = int(topcount)
            if topcount > 100:
                topcount = 100
            # print help message
            messagetxt = f"Top {topcount} pushups scores :weight_lifter:\n"
            scores = {}
            averages = {}
            days = {}
            for key in self.redis.scan_iter("pushupsdaily:*"):
                user = key.split(":")[1]
                score = int(self.redis.get(key))
                if user in scores:
                    scores[user] += score
                else:
                    scores[user] = score
            # get averages
            for user in scores:
                # get day count for user
                userdays = self.redis.keys(f"pushupsdaily:{user}:*")
                if len(userdays) > 0:
                    days[user] = len(userdays)
                    import math

                    averages[user] = math.ceil(scores[user] / len(userdays))
                else:
                    days[user] = 0
                    averages[user] = 0
            top = []
            for user, score in scores.items():
                top.append((user, score))
            top.sort(key=lambda x: x[1], reverse=True)
            for i in range(topcount):
                if i < len(top):
                    place = i + 1
                    if place == 1:
                        place = ":first_place_medal: "
                    elif place == 2:
                        place = ":second_place_medal: "
                    elif place == 3:
                        place = ":third_place_medal: "
                    else:
                        place = f"{place}. "
                    messagetxt += f"**{place} {self.helper.nohl(top[i][0])}: {top[i][1]}**\t(avg: {averages[top[i][0]]}. days: {days[top[i][0]]})\n"
            self.driver.reply_to(message, messagetxt)