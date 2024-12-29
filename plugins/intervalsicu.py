import base64
import datetime
import json

import requests
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from dateutil import parser

from plugins.base import PluginLoader


class IntervalsIcu(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
        self.valkey = self.helper.valkey
        self.intervals_prefix = "INTERVALSICU"
        self.api_url = "https://app.intervals.icu/api/v1"
        self.athletes = self.valkey.smembers(f"{self.intervals_prefix}_athletes") or set()
        for uid in self.athletes:
            # cleanup broken athletes
            if not self.verify_api_key(uid):
                self.remove_athlete(uid)
        self.opted_in = self.valkey.smembers(f"{self.intervals_prefix}_athletes_opted_in") or set()

    def return_pretty_activities(self, activities: list):
        """return pretty activities"""
        pretty = []
        for activity in activities:
            pretty.append(f"{activity.get('start_date_local')} {activity.get('type')} {activity.get('name')} {activity.get('distance')} {activity.get('duration')} {activity.get('calories')}")
        return pretty
    def add_athlete(self, uid: str):
        self.valkey.sadd(f"{self.intervals_prefix}_athletes", uid)
        if uid not in self.athletes:
            self.athletes.add(uid)
    def remove_athlete(self, uid: str):
        self.valkey.srem(f"{self.intervals_prefix}_athletes", uid)
        if uid in self.athletes:
            self.athletes.remove(uid)
    def add_athlete_opted_in(self, uid: str):
        self.valkey.sadd(f"{self.intervals_prefix}_athletes_opted_in", uid)
        if uid not in self.opted_in:
            self.opted_in.add(uid)
    def remove_athlete_opted_in(self, uid: str):
        self.valkey.srem(f"{self.intervals_prefix}_athletes_opted_in", uid)
        if uid in self.opted_in:
            self.opted_in.remove(uid)
    def add_activity(self, uid: str, activity: dict):
        # check if the list exists
        if self.valkey.exists(f"{self.intervals_prefix}_athlete_{uid}_activities"):                
            # check if activity already exists
            self.helper.slog(self.return_pretty_activities([activity]))
            if json.dumps(activity) in self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, -1):
                return

        self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_activities", json.dumps(activity))
    def remove_activity(self, uid: str, activity: dict):
        self.valkey.lrem(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, activity)
    def get_activities(self, uid: str):
        activities = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, -1)
        self.helper.slog("Got activities")
        if activities:
            for activity in activities:
                self.helper.slog(self.return_pretty_activities([json.loads(activity)]))
        # decode the json
        if activities:
            return [json.loads(activity) for activity in activities]
        return []

    def _headers(self, uid: str):
        """Basic authorization headers"""
        username ="API_KEY"
        api_key = self.valkey.get(f"{self.intervals_prefix}_{uid}_apikey")
        encoded = base64.b64encode(f"{username}:{api_key}".encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json", "Accept": "application/json"}


    def _endpoint(self, endpoint: str):
        return f"{self.api_url}/athlete/0/{endpoint}"

    def _request(self, endpoint: str, method: str, data: dict | None = None, headers: dict | None = None, uid: str = ""):
        """make a request to intervals api"""
        if headers is None and uid:
            headers = self._headers(uid)
        if headers is None:
            headers = {}
        if data is None:
            data = {}
        if method == "GET":
            try:
                response = requests.get(self._endpoint(endpoint), headers=headers, params=data)
                return response
            except Exception:
                self.helper.slog(response.text())
                return False
        if method == "POST":
            try:
                response = requests.post(method, self._endpoint(endpoint), json=data, headers=headers)
                return response
            except Exception:
                self.helper.slog(response.text())
                return False
        return False
    async def _scrape_activities(self, uid: str, oldest: str | None = None, newest: str | None = None):
        """scrape activities from intervals"""
        # date format is YYYY-MM-DD
        # oldest set it to the previous month
        # newest set it to the current month and day + 1
        today = datetime.datetime.now()
        if newest is None:
            newest = (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        if oldest is None:
            # first lets try and get the oldest activity from the user
            activities = self.get_activities(uid)
            if activities:
                oldest = parser.parse(activities[-1].get("start_date")).strftime("%Y-%m-%d")
            else:
                oldest = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        data = {"oldest": oldest, "newest": newest}
        try:
            await self.helper.log(f"Getting activities from intervals {oldest} to {newest}")
            response = self._request("activities", "GET", uid=uid, data=data)
            if response.status_code == 200:
                activities = response.json()
                for activity in activities:
                    await self.helper.log("Got activity")
                    await self.helper.log(self.return_pretty_activities([activity]))
                    self.add_activity(uid, activity)
            else:
                await self.helper.log("Failed to get activities")
                await self.helper.log(response.status_code)
        except Exception:
            return False
    def verify_api_key(self, uid: str):
        """this uses the athlete endpoint to verify the api key"""
        try:
            response = self._request("profile", "GET", headers=self._headers(uid))
            if response.status_code == 200:
                athlete = response.json().get("athlete", {})
                if athlete.get("id"):
                    return True
            return False
        except Exception:
            return False

    @listen_to(r"^\.intervals login ([\s\S]*)")
    async def login(self, message: Message, text: str):
        """login to intervals"""
        # this is done by providing an api key
        # get uid from message sender
        uid = message.user_id
        self.valkey.set(f"{self.intervals_prefix}_{uid}_apikey", text)
        # verify the api key
        works = self.verify_api_key(uid)
        if works:
            self.add_athlete(uid)
            self.driver.reply_to(message, "API key verified\nYou are now logged in\n to participate in the public usage use\n.intervals opt-in\n you can opt out at any time using:\n.intervals opt-out")
        else:
            self.driver.reply_to(message, "API key verification failed")
    @listen_to(r"^\.intervals opt-in")
    async def opt_in(self, message: Message):
        """opt in to public usage"""
        uid = message.user_id
        if self.verify_api_key(uid):
            self.add_athlete_opted_in(uid)
            self.driver.reply_to(message, "You have opted in to public usage")
        else:
            self.driver.reply_to(message, "You need to login first using .intervals login")
    @listen_to(r"^\.intervals opt-out")
    async def opt_out(self, message: Message):
        """opt out of public usage"""
        uid = message.user_id
        self.remove_athlete_opted_in(uid)
        self.driver.reply_to(message, "You have opted out of public usage")
    @listen_to(r"^\.intervals logout")
    async def logout(self, message: Message):
        """logout of intervals"""
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_{uid}_apikey")
        self.remove_athlete(uid)
        self.remove_athlete_opted_in(uid)
        self.driver.reply_to(message, "You have been logged out")
    @listen_to(r"^\.intervals verify")
    async def verify(self, message: Message):
        """verify the api key"""
        uid = message.user_id
        works = self.verify_api_key(uid)
        if works:
            self.driver.reply_to(message, "API key verified")
        else:
            self.driver.reply_to(message, "API key verification failed")
    @listen_to(r"^\.intervals activities")
    async def activities(self, message: Message):
        """get activities"""
        uid = message.user_id
        #await self._scrape_activities(uid)
        activities = self.get_activities(uid)
        if activities:
            activities_str = "\n".join(self.return_pretty_activities(activities))
            self.driver.reply_to(message, activities_str)
        else:
            self.driver.reply_to(message, "No activities found try .intervals refresh activities")

    @listen_to(r"^\.intervals refresh activities")
    async def refresh(self, message: Message):
        """refresh activities"""
        uid = message.user_id
        await self._scrape_activities(uid)
    @listen_to(r"^\.intervals reset activities")
    async def reset(self, message: Message):
        """reset activities"""
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_activities")
        self.driver.reply_to(message, "Activities reset")
    @listen_to(r"^\.intervals athletes")
    async def athletes_cmd(self, message: Message):
        """get athletes"""
        # check if the user is an admin
        if not self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, "You need to be an admin to use this command")
            return
        athletes = self.valkey.smembers(f"{self.intervals_prefix}_athletes")
        if not athletes:
            self.driver.reply_to(message, "No athletes found")
            return
        # convert to usernames
        athletes = ["@" + self.users.id2unhl(uid) for uid in athletes]
        athletes = "\n".join(athletes)
        self.driver.reply_to(message, athletes)
    @listen_to(r"^\.intervals participants")
    async def participants(self, message: Message):
        """get participants"""
        athletes = self.valkey.smembers(f"{self.intervals_prefix}_athletes_opted_in")
        if not athletes:
            self.driver.reply_to(message, "No participants found. ask them to use .intervals opt-in")
            return
        # convert to usernames
        athletes = ["@" + self.users.id2unhl(uid) for uid in athletes]
        athletes = "\n".join(athletes)
        self.driver.reply_to(message, athletes)
    @listen_to(r"^\.intervals help")
    async def help(self, message: Message):
        """help"""
        help_str = """
        .intervals login [api_key] - login
        .intervals opt-in - opt in to public usage
        .intervals opt-out - opt out of public usage
        .intervals logout - logout
        .intervals verify - verify the api key
        .intervals activities - get activities
        .intervals refresh activities - refresh activities
        .intervals reset activities - reset activities
        .intervals athletes - get athletes (admin only)
        .intervals participants - get participants
        """
        self.driver.reply_to(message, help_str)
