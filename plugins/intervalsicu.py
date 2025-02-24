import asyncio
import base64
import datetime
import inspect
import json
import re
from functools import wraps
from typing import Dict, List

import nest_asyncio

nest_asyncio.apply()
import requests
import schedule
from dateutil import parser
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message

from plugins.base import PluginLoader
from plugins.models.intervals_activity import IntervalsActivity
from plugins.models.intervals_wellness import IntervalsWellness, SportInfo


def bot_command(category: str, description: str, pattern: str = None, admin: bool = False):
    """
    Decorator to specify command metadata
    """
    def decorator(func):

        @wraps(func)
        @listen_to(f"^\.intervals {pattern}")
        async def wrapper(self, message: Message, *args, **kwargs):
            if admin and not self.users.is_admin(message.sender_name):
                self.driver.reply_to(message, "You need to be an admin to use this command")
                return
            return await func(self, message, *args, **kwargs)
        
        # Store command metadata
        wrapper._command_meta = {
            "category": category,
            "description": description,
            "pattern": pattern,
            "is_admin": admin
        }
        return wrapper
    return decorator

class IntervalsIcu(PluginLoader):
    """IntervalsIcu plugin"""
    _INTERNAL_TIMER_LOOP = 300
    _MINIMUM_REFRESH_INTERVAL_FOR_ATHLETE = 60  # 5 minutes
    ACTIVITY_OVERVIEW_COMMON_FIELDS = [
        "moving_time",
        "calories",
        "average_heartrate",
        "max_heartrate",
    ]
    ACTIVITY_OVERVIEW_RUNNING_FIELDS = [
        "distance",
        "pace",
        "average_speed",
        "max_speed",
    ]
    ACTIVITY_OVERVIEW_CYCLING_FIELDS = [
        "distance",
        "pace",
        "average_speed",
        "max_speed",
    ]
    ACTIVITY_OVERVIEW_WEIGHTTRAINING_FIELDS = [
        "kg_lifted"
    ]
    ACTIVITY_MAPPING_REGEX = {
        "run|walk|hike|trailrun|treadmill": ACTIVITY_OVERVIEW_COMMON_FIELDS + ACTIVITY_OVERVIEW_RUNNING_FIELDS,
        "ride|cycling": ACTIVITY_OVERVIEW_COMMON_FIELDS + ACTIVITY_OVERVIEW_CYCLING_FIELDS,
        "weighttraining": ACTIVITY_OVERVIEW_COMMON_FIELDS + ACTIVITY_OVERVIEW_WEIGHTTRAINING_FIELDS,
    }
    # Add categories for commands
    COMMAND_CATEGORIES = {
        "login": "Login commands",
        "opt": "Public usage commands",
        "profile": "Personal Information commands", 
        "activities": "Personal Activity & wellness commands",
        "refresh": "Data refresh commands",
        "admin": "Admin only commands",
        "reset": "Data management commands",
        "steps|weight|distance|hr": "Metric commands"
    }

    def __init__(self):
        super().__init__()
        self._command_cache = None

    def get_commands(self) -> Dict[str, Dict[str, List[str]]]:
        """Get all commands grouped by category with their descriptions"""
        if self._command_cache is not None:
            return self._command_cache

        commands = {}

        # Get all methods with command metadata
        for name, method in inspect.getmembers(self):
            if hasattr(method, '_command_meta'):
                meta = method._command_meta
                category = meta["category"]

                if category not in commands:
                    commands[category] = []

                commands[category].append({
                    "pattern": meta["pattern"],
                    "description": meta["description"],
                    "is_admin": meta["is_admin"]
                })

        # Define category order
        category_order = [

            "Authentication",
            "Privacy Settings",
            "Activity & Wellness Management",
            "Data Refresh",
            "Metrics",
            "Profile",
            "Help",
            "Admin"
        ]

        # Sort commands by category order
        sorted_commands = {}
        for category in category_order:
            if category in commands:
                sorted_commands[category] = commands[category]

        # Add any remaining categories not in the order list
        for category in commands:
            if category not in sorted_commands:
                sorted_commands[category] = commands[category]

        self._command_cache = sorted_commands
        return sorted_commands

    def generate_help_message(self) -> str:
        """Generate help message dynamically from commands"""
        commands = self.get_commands()

        help_sections = []

        # Add each category
        for category, command_list in commands.items():
            section = [f"\n**{category}**:"]

            for cmd in command_list:
                pattern = cmd["pattern"]
                desc = cmd["description"]

                # Format the command help line
                # Convert regex patterns to readable format
                pattern = pattern.replace("([\s\S]*)", "<value>")  # For login and generic input
                pattern = pattern.replace("([a-zA-Z0-9_]+)", "<name>")  # For profile set name
                pattern = pattern.replace("([0-9.]+)", "<value>")  # For profile set value
                pattern = pattern.replace("([0-9]+[ymdw])", "<period>")  # For metrics period

                cmd_str = f".intervals {pattern}"

                # Add admin marker if needed
                if cmd["is_admin"]:
                    cmd_str += " (admin only)"

                section.append(f"{cmd_str} - {desc}")

            help_sections.append("\n".join(section))

        # Add parameters section
        parameters = """
Parameters:
[metric] - distance, duration, calories, steps, count, weight
[period] - Format: <number><unit> where unit is d(days), w(weeks), m(months), y(years). Example: 7d, 4w
[goal] - number
[profile_key] - height, weight(only for starting reference will be used for goals)
[api_key] - Your Intervals.icu API key
"""

        # Combine all sections
        full_help = "Intervals.icu Bot Commands:\n" + "\n".join(help_sections) + "\n" + parameters

        return full_help

    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
        self.valkey = self.helper.valkey
        self.intervals_prefix = "INTERVALSICU"
        self.api_url = "https://app.intervals.icu/api/v1"

        # get all athletes and opted in athletes
        self.athletes = self.valkey.smembers(f"{self.intervals_prefix}_athletes") or set()
        # fix bug where valkey returns as list
        if self.athletes and isinstance(self.athletes, list):
            self.athletes = set(self.athletes)
            self.helper.log("Fixed bug where athletes was a list")
        self.opted_in = self.valkey.smembers(f"{self.intervals_prefix}_athletes_opted_in") or set()
        # fix bug where valkey returns as list
        if self.opted_in and isinstance(self.opted_in, list):
            self.opted_in = set(self.opted_in)
            self.helper.log("Fixed bug where opted_in was a list")
        # announcement config
        if self.get_announcement_channel() is None:
            self.announcements_enabled = False
        else:
            self.announcements_enabled = True
            self.announcement_channel = self.get_announcement_channel()
        # jobs
        self.jobs = {}
        self.jobs['refresh_all_athletes'] = schedule.every(self._INTERNAL_TIMER_LOOP).seconds.do(self.refresh_all_athletes)
        self.jobs['cleanup_duplicates'] = schedule.every(1).minutes.do(self.cleanup_duplicates_for_all_athletes)
        self.jobs['cleanup_broken_athletes'] = schedule.every(1).days.do(self.cleanup_broken_athletes)
        # activity announcement job
        self.jobs['announce_added_activities'] = schedule.every(5).seconds.do(self.announce_added_activities)
        # leaderboards announcement job
        self.jobs['announce_leaderboard'] = schedule.every(1).days.at("18:00").do(self.announce_leaderboards)

        # check if the key auto_refresh is set if not set it to true
        if not self.valkey.exists(f"{self.intervals_prefix}_auto_refresh"):
            self.valkey.set(f"{self.intervals_prefix}_auto_refresh", "true")
            self.valkey.set(f"{self.intervals_prefix}_refresh_interval", "900")

        # clear refresh lock
        self.clear_lock("refresh_all_athletes")

        # run the jobs on startup
        self.refresh_all_athletes(force=True)
        self.cleanup_duplicates_for_all_athletes()
        self.cleanup_broken_athletes()

    def cleanup_broken_athletes(self):
        for athlete in self.athletes:
            if not self.verify_api_key(athlete):
                self.remove_athlete(athlete)

    def cleanup_duplicates_for_all_athletes(self):
        for athlete in self.athletes:
            self.cleanup_duplicates(athlete)

    def cleanup_duplicates(self, uid: str):
        activities = self.get_activities(uid)
        wellness = self.get_wellnesses(uid)
        # get wellnesses directy from the valkey
        wellnesses = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1)
        # sort wellnesses by id
        wellnesses = sorted(wellnesses, key=lambda x: json.loads(x).get("id"))
        if activities:
            activities = sorted(activities, key=lambda x: x.id)
            for i in range(1, len(activities)):
                if activities[i].id == activities[i-1].id:
                    self.helper.console(f"Removing duplicate activity for user {self.users.id2u(uid)} - {activities[i].id} and {activities[i-1].id}")
                    self.remove_activity(uid, activities[i].to_json())
        if wellness:
            # sort by "id" and "updated"
            wellness = sorted(wellness, key=lambda x: (x.id, x.updated))
            for i in range(1, len(wellness)):
                old_wellness = wellness[i-1]
                new_wellness = wellness[i]
                if old_wellness.id == new_wellness.id:
                    # merge the two wellnesses
                    merged = IntervalsWellness.from_dict({**old_wellness.to_dict(), **new_wellness.to_dict()})
                    self.helper.console(f"Removing duplicate wellness for user {self.users.id2u(uid)} - {old_wellness.id} and {new_wellness.id}")
                    self.remove_wellness(uid, json.dumps(wellnesses[i]))
                    self.add_wellness(uid, merged)
    def return_pretty_activities(self, activities: list[IntervalsActivity]):
        """return pretty activities"""
        activities_str = ""
        for activity in activities:
            # use the ACTIVITY_MAPPING_REGEX to get the fields by checking each type of activity against activity.type
            fields = self.ACTIVITY_OVERVIEW_COMMON_FIELDS
            regexes = self.ACTIVITY_MAPPING_REGEX.keys()
            for regex in regexes:
                matched = False
                # use search instead of match to match anywhere in the string
                if re.search(regex, activity.type, re.IGNORECASE):
                    matched = True
                    fields = self.ACTIVITY_MAPPING_REGEX[regex]
                    break

            # print the header
            activities_str += f"Activity: {activity.start_date_local} - {activity.type} - {activity.activity_link_markdown}\n"
            data = []
            # only print fields that are not None
            for field in fields:
                value = getattr(activity, field)
                if value is not None:
                    data.append([self.convert_snakecase_and_camelcase_to_ucfirst(field), self.get_metric_to_human_readable(field, value)])
            activities_str += self.generate_markdown_table(["Field", "Value"], data)
            activities_str += "--------------------------------\n"
        return activities_str

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

    def add_activity(self, uid: str, activity: IntervalsActivity) -> str:
        """Add an activity to storage"""
        activity_id = activity.id
        activities = self.get_activities(uid)
        if activities:
            for i, act in enumerate(activities):
                if act.id == activity_id:
                    if act == activity:
                        return "alreadyexists"
                    self.remove_activity(uid, act.to_dict())
                    self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_activities", activity.to_json())
                    return "changed"
        if self.valkey.exists(f"{self.intervals_prefix}_athlete_{uid}_activities"):                
            if activity.to_json() in self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, -1):
                return "alreadyexists"

        self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_activities", activity.to_json())
        # lets keep track of the added activities so we can announce them to the channel
        if uid in self.opted_in:
            self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_activities_added", activity.to_json())
        return "added"
    def announce_added_activities(self):
        if self.announcements_enabled and self.get_announcement_channel() is not None:
            for uid in self.opted_in:
                # do a while loop to get all the activities using lpop
                while True:
                    activity = self.valkey.lpop(f"{self.intervals_prefix}_athlete_{uid}_activities_added")
                    if activity is None:
                        # no more activities
                        # self.helper.slog(f"No more activities for {self.users.id2unhl(uid)}")
                        break
                    if activity:
                        activity = IntervalsActivity.from_dict(json.loads(activity))
                        # TODO: change this
                        pretty = self.return_pretty_activities([activity])
                        self.helper.slog(f"Announcing activity for {self.users.id2unhl(uid)}: {pretty}")
                        self.driver.create_post(self.get_announcement_channel(),f"New activity for {self.users.id2unhl(uid)}: {pretty}")
    def lookup_metric_table(self, metric: str) -> str:
        """get the table where the metric is stored"""
        if IntervalsActivity.has_field(metric):
            return "activities"
        if IntervalsWellness.has_field(metric):
            return "wellness"

    def remove_activity(self, uid: str, activity: dict):
        self.valkey.lrem(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, json.dumps(activity))

    def get_activities(self, uid: str, oldest: str | None = None, newest: str | None = None) -> list[IntervalsActivity]:
        """get activities"""
        activities = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, -1)
        if activities:
            # Convert JSON strings to IntervalsActivity objects
            activities = [IntervalsActivity.from_dict(json.loads(activity)) for activity in activities]
            # Sort by start_date
            activities = sorted(activities, key=lambda x: x.start_date)
            if oldest and newest:
                activities = [activity for activity in activities
                       if parser.parse(oldest) <= parser.parse(activity.start_date_local) <= parser.parse(newest)]
                return activities
            return activities
        return []

    def add_wellness(self, uid: str, wellness: IntervalsWellness) -> str:
        """Add a wellness entry to storage"""
        wellness_id = wellness.id
        wellnesses = self.get_wellnesses(uid)
        if wellnesses:
            for i, well in enumerate(wellnesses):
                if well.id == wellness_id:
                    # if the id already exists lets merge the new with the old one and update it
                    old_wellness = wellnesses[i].to_dict()
                    new_wellness = wellness.to_dict()
                    # merge the two dictionaries
                    wellness = IntervalsWellness.from_dict({**old_wellness, **new_wellness})
                    # remove the old wellness
                    self.remove_wellness(uid, well.to_json())
                    # add the new wellness
                    self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_wellness", wellness.to_json())
                    return "changed"
        if self.valkey.exists(f"{self.intervals_prefix}_athlete_{uid}_wellness"):
            if wellness.to_json() in self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1):
                return "alreadyexists"
        self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_wellness", wellness.to_json())
        return "added"

    def remove_wellness(self, uid: str, wellness: dict):
        """remove wellness"""
        # check if it is a string or a dict
        if isinstance(wellness, dict):
            wellness = json.dumps(wellness)
        self.valkey.lrem(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, wellness)

    def get_wellnesses(self, uid: str, oldest: str | None = None, newest: str | None = None) -> list[IntervalsWellness]:
        """get wellness"""
        wellnesses = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1)
        if wellnesses:
            # Convert JSON strings to IntervalsWellness objects
            wellnesses = [IntervalsWellness.from_dict(json.loads(wellness)) for wellness in wellnesses]
            # Sort by id (date)
            wellnesses = sorted(wellnesses, key=lambda x: x.id)
            # self.helper.slog(f"Got wellnesses: {wellnesses[:10]}")
            if oldest and newest:
                return [wellness for wellness in wellnesses
                       if parser.parse(oldest) <= parser.parse(wellness.id) <= parser.parse(newest)]
            return wellnesses
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
            raise Exception("No headers provided")
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

    def _scrape_athlete(self, uid: str, force_all: bool = False):
        """scrape all things from intervals"""
        today = datetime.datetime.now()
        newest = (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        activities = self.get_activities(uid)
        wellness = self.get_wellnesses(uid)
        wellnesses_added = 0
        activities_added = 0
        wellnesses_changed = 0
        activities_changed = 0

        if activities:
            oldest_activity = parser.parse(activities[-1].start_date).strftime("%Y-%m-%d")
            oldest_activity = (parser.parse(oldest_activity) - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        else:
            oldest_activity = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")

        if wellness:
            oldest_wellness = parser.parse(wellness[-1].id).strftime("%Y-%m-%d")
            oldest_wellness = (parser.parse(oldest_wellness) - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        else:
            oldest_wellness = (today - datetime.timedelta(days=10*365)).strftime("%Y-%m-%d")

        if force_all:
            oldest_activity = "2010-01-01"
            oldest_wellness = "2010-01-01"

        params_activity = {"oldest": oldest_activity, "newest": newest}
        params_wellness = {"oldest": oldest_wellness, "newest": newest}

        try:
            # get activities
            # self.helper.slog(f"Getting activities from intervals {oldest_activity} to {newest}")
            response = self._request("activities", "GET", uid=uid, data=params_activity)
            if response.status_code == 200:
                activities_data = response.json()
                for activity_data in activities_data:
                    # self.helper.slog(f"Got activity: {self.users.id2u(uid)} - {activity_data.get('start_date')} - {activity_data.get('id')}")
                    if activity_data.get("source","").lower() == "strava":
                        # strava activities not supported via the api for some reason
                        continue
                    activity = IntervalsActivity.from_dict(activity_data)
                    result = self.add_activity(uid, activity)
                    if result == "added":
                        activities_added += 1
                    elif result == "changed":
                        activities_changed += 1
            else:
                pass
                # self.helper.slog("Failed to get activities")
                # self.helper.slog(response.status_code)

            # get wellness
            # self.helper.slog(f"Getting wellness from intervals {oldest_wellness} to {newest}")
            response = self._request("wellness", "GET", uid=uid, data=params_wellness)
            if response.status_code == 200:
                wellness_data = response.json()
                for wellness_entry in wellness_data:
                    # self.helper.slog(f"Got wellness: {self.users.id2u(uid)} - {wellness_entry.get('id')}")
                    wellness = IntervalsWellness.from_dict(wellness_entry)
                    result = self.add_wellness(uid, wellness)
                    if result == "added":
                        wellnesses_added += 1
                    elif result == "changed":
                        wellnesses_changed += 1
            else:
                pass
                # self.helper.slog("Failed to get wellness")
                # self.helper.slog(response.status_code)

            self.valkey.set(f"{self.intervals_prefix}_{uid}_last_refresh", str(int(datetime.datetime.now().timestamp())))

        except Exception as e:
            self.helper.slog(f"Error in _scrape_athlete: {str(e)}")
            raise e

        return {
            "activities_added": activities_added,
            "activities_changed": activities_changed,
            "wellnesses_added": wellnesses_added,
            "wellnesses_changed": wellnesses_changed
        }

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

    # Commands organized by category:

    # Authentication Commands
    @bot_command(
        category="Authentication",
        description="Connect your Intervals.icu account by providing your API key",
        pattern="login ([\s\S]*)"  # Hidden regex
    )
    async def login(self, message: Message, text: str):
        uid = message.user_id
        self.valkey.set(f"{self.intervals_prefix}_{uid}_apikey", text)
        # verify the api key
        works = self.verify_api_key(uid)
        if works:
            self.add_athlete(uid)
            self.driver.reply_to(message, "API key verified\nYou are now logged in\n to participate in the public usage use\n.intervals opt-in\n you can opt out at any time using:\n.intervals opt-out")
        else:
            self.driver.reply_to(message, "API key verification failed")

    @bot_command(
        category="Authentication",
        description="Check if your API key is valid and working",
        pattern="verify"
    )
    async def verify(self, message: Message):
        uid = message.user_id
        works = self.verify_api_key(uid)
        if works:
            self.driver.reply_to(message, "API key verified")
        else:
            self.driver.reply_to(message, "API key verification failed")

    @bot_command(
        category="Authentication",
        description="Remove your API key and disconnect your account",
        pattern="logout"
    )
    async def logout(self, message: Message):
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_{uid}_apikey")
        self.remove_athlete(uid)
        self.remove_athlete_opted_in(uid)
        self.driver.reply_to(message, "You have been logged out")

    # Privacy Settings Commands
    @bot_command(
        category="Privacy Settings",
        description="Enable sharing your data with other users in the community",
        pattern="opt-in"
    )
    async def opt_in(self, message: Message):
        uid = message.user_id
        if self.verify_api_key(uid):
            self.add_athlete_opted_in(uid)
            self.driver.reply_to(message, "You have opted in to public usage")
        else:
            self.driver.reply_to(message, "You need to login first using .intervals login")

    @bot_command(
        category="Privacy Settings",
        description="Disable sharing your data with other users",
        pattern="opt-out"
    )
    async def opt_out(self, message: Message):
        uid = message.user_id
        self.remove_athlete_opted_in(uid)
        self.driver.reply_to(message, "You have opted out of public usage")
    def convert_snakecase_and_camelcase_to_ucfirst(self, string: str) -> str:
        """Convert snake_case and camelcase and capitalize each letter of each word"""
        if "_" in string:
            string = string.lower()
            return " ".join([word.capitalize() for word in string.split("_")])
        # Convert camelCase to Ucfirst allowing multiple words
        # example "camelCase" -> "Camel Case"
        # example "camelCaseExample" -> "Camel Case Example"
        w = re.sub(r"([a-z])([A-Z])", r"\1 \2", string)
        return " ".join([word.capitalize() for word in w.split(" ")])
    # Activity & Wellness Management Commands
    @bot_command(
        category="Activity & Wellness Management",
        description="Display your recent activities and workouts",
        pattern="activities"
    )
    async def activities(self, message: Message):
        uid = message.user_id
        # only return the last 10 activities
        activities = self.get_activities(uid)
        # reverse the list
        activities = activities[::-1][:10]
        # get the fields for the activities using the mapping

        if activities:
            activities = sorted(activities, key=lambda x: x.start_date, reverse=True)
            activities_str = "Last 10 activities:\n (or whatever fits in 14000 characters)\n"
            for activity in activities:
                activities_str += self.return_pretty_activities([activity])
            # limit to 14000 characters
            activities_str = activities_str[:14000]
            self.driver.reply_to(message, activities_str)
        else:
            self.driver.reply_to(message, "No activities found try .intervals refresh data")

    @bot_command(
        category="Activity & Wellness Management",
        description="Delete all your stored wellness data",
        pattern="reset wellness"
    )
    async def reset_wellness(self, message: Message):
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_wellness")
        self.driver.reply_to(message, "Wellnesses reset")
    @bot_command(
        category="Activity & Wellness Management",
        description="Delete all your stored activities data",
        pattern="reset activities"
    )
    async def reset_activities(self, message: Message):
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_activities")
        self.driver.reply_to(message, "Activities reset")
    @bot_command(
        category="Activity & Wellness Management",
        description="Delete all your stored activities and wellness data",
        pattern="reset alldata"
    )
    async def reset(self, message: Message):
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_activities")
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_wellness")
        self.driver.reply_to(message, "Activities & Wellness reset")

    # Data Refresh Commands
    @bot_command(
        category="Data Refresh",
        description="Force sync all historical data from Intervals.icu (may take a while)",
        pattern="refresh data force"
    )
    async def refresh_force(self, message: Message):
        uid = message.user_id
        try:
            result = self._scrape_athlete(uid, force_all=True)
        except Exception as e:
            self.driver.reply_to(message, f"Error: {str(e)}")
            return
        # count the number of activities and wellness
        wellness_count_new = len(self.get_wellnesses(uid))
        activities_count_new = len(self.get_activities(uid))
        if result:
            self.driver.reply_to(message, f"Refreshed activities newly total:{activities_count_new} new:{result.get('activities_added')} changed:{result.get('activities_changed')} & wellness total:{wellness_count_new} new:{result.get('wellnesses_added')} changed:{result.get('wellnesses_changed')}")
        else:
            self.driver.reply_to(message, "No new activities & wellness found")

    @bot_command(
        category="Data Refresh",
        description="Sync recent data from Intervals.icu",
        pattern="refresh data"
    )
    async def refresh(self, message: Message):
        uid = message.user_id
        # check if the last refresh was too recent
        refresh_interval = int(self._MINIMUM_REFRESH_INTERVAL_FOR_ATHLETE)
        current_time = int(datetime.datetime.now().timestamp())
        last_refresh = self.valkey.get(f"{self.intervals_prefix}_{uid}_last_refresh")
        if last_refresh:
            if current_time - int(float(last_refresh)) < refresh_interval:
                self.driver.reply_to(message, f"Refresh too recent wait {refresh_interval - (current_time - int(float(last_refresh)))} seconds")
                return
        try:
            result = self._scrape_athlete(uid)
        except Exception as e:
            self.driver.reply_to(message, f"Error: {str(e)}")
            return
        # get counts of activities and wellness
        wellness_count_new = len(self.get_wellnesses(uid))
        activities_count_new = len(self.get_activities(uid))
        if result:
            self.driver.reply_to(message, f"Refreshed activities newly total:{activities_count_new} new:{result.get('activities_added')} changed:{result.get('activities_changed')} & wellness total:{wellness_count_new} new:{result.get('wellnesses_added')} changed:{result.get('wellnesses_changed')}")
        else:
            self.driver.reply_to(message, "No new activities & wellness found")

    # Profile Commands
    @bot_command(
        category="Profile",
        description="View your stored profile settings and preferences",
        pattern="profile"
    )
    async def profile(self, message: Message):
        uid = message.user_id
        # valkey stored profile
        profile = self.valkey.hgetall(f"{self.intervals_prefix}_profiles", uid)
        if profile:
            self.driver.reply_to(message, profile)
            return

    @bot_command(
        category="Profile",
        description="Update a profile setting. Usage: .intervals profile set <setting_name> <value> (example: profile set weight 75)",
        pattern="profile set ([a-zA-Z0-9_]+) ([0-9.]+)"  # Hidden regex
    )
    async def profile_set(self, message: Message, key: str, value: str):
        uid = message.user_id
        self.valkey.hset(f"{self.intervals_prefix}_profiles", uid, {key: value})
        self.driver.reply_to(message, f"Set {key} to {value}")

    # Metrics Commands
    @bot_command(
        category="Metrics",
        description="View statistics over time. Usage: .intervals <metric> <timespan> (example: steps 7d or weight 2w)",
        pattern="stats ([-_A-Za-z0-9]+) ([0-9]+[ymdw])"  # Hidden regex
    )
    async def get_user_metrics(self, message: Message, metric: str, period: str):
        uid = message.user_id
        original_metric = metric
        if metric == "sleep":
            metric = "sleepSecs"
        # parse the period
        try:
            date_from, date_to = self.parse_period(period)
        except Exception:
            self.driver.reply_to(message, "Invalid period")
            return
        metrics_table = self.lookup_metric_table(metric)
        if not metrics_table:
            self.driver.reply_to(message, "Invalid metric")
            return
        metrics = await self.get_athlete_metrics(uid, metrics_table, metric, date_from=date_from, date_to=date_to)
        hmetric = self.convert_snakecase_and_camelcase_to_ucfirst(original_metric)
        msg = ""
        # substract 1 day from the date_to to get the correct period
        date_to_str = (parser.parse(date_to) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        msg += f"Showing {hmetric} for {self.users.id2unhl(uid)} from {str(date_from)} to {str(date_to_str)}"
        if metrics:
            # do some calculations
            metric_sum = 0
            for met in metrics:
                metric_sum += int(met.get(metric,0))
            # dont show hr and weight totals
            if metric not in ["hr", "weight"]:
                msg += f"\nTotal {hmetric} {self.get_metric_to_human_readable(original_metric,metric_sum)}"
            # lets calculate two averages. one for the period and one for the active days
            active_days = len(metrics)
            total_days = (parser.parse(date_to) - parser.parse(date_from)).days -1
            inactive_days = total_days - active_days
            if active_days:
                msg += f"\nAverage {hmetric} for the period on active days {self.get_metric_to_human_readable(original_metric,metric_sum/active_days)}"
                msg += f"\nActive days {active_days}"
            if total_days:
                msg += f"\nAverage {hmetric} for the total period {self.get_metric_to_human_readable(original_metric,metric_sum/total_days)}"
                msg += f"\nTotal days {total_days}"
            if inactive_days:
                msg += f"\nInactive days {inactive_days}"
            # lets get the median
            metric_median = 0
            metric_vals = [met.get(metric,0) for met in metrics]
            if metric_vals:
                metric_vals.sort()
                if len(metric_vals) % 2 == 0:
                    metric_median = (metric_vals[len(metric_vals)//2] + metric_vals[len(metric_vals)//2 - 1]) / 2
                else:
                    metric_median = metric_vals[len(metric_vals)//2]
                msg += f"\nMedian {hmetric} {self.get_metric_to_human_readable(metric,metric_median)}"
            # lets get the min and max
            metric_min =   min([met.get(metric,0) for met in metrics])
            metric_max =   max([met.get(metric,0) for met in metrics])
            # find the date for the min and max
            metric_min_date = [met.get("date") for met in metrics if met.get(metric,0) == metric_min]
            metric_max_date = [met.get("date") for met in metrics if met.get(metric,0) == metric_max]
            msg += f"\nMin {hmetric} {self.get_metric_to_human_readable(original_metric,metric_min)} on {', '.join([parser.parse(d).strftime('%Y-%m-%d %H:%M:%S') for d in metric_min_date])}"
            msg += f"\nMax {hmetric} {self.get_metric_to_human_readable(original_metric,metric_max)} on {', '.join([parser.parse(d).strftime('%Y-%m-%d %H:%M:%S') for d in metric_max_date])}"
            limit = 100
            msg += f"\n\nData (Limited to showing only the latest {limit} entries calculations are performed in the entire period):\n"
            msg += self.get_table_for_metrics(metrics, limit=limit)
            self.driver.reply_to(message, msg)
        else:
            self.driver.reply_to(message, f"No {metric} found")

    # Admin Commands
    @bot_command(
        category="Admin",
        description="Display list of all registered athletes in the system",
        pattern="athletes",
        admin=True
    )
    async def athletes_cmd(self, message: Message):
        athletes = self.valkey.smembers(f"{self.intervals_prefix}_athletes")
        if not athletes:
            self.driver.reply_to(message, "No athletes found")
            return
        # convert to usernames
        athletes = ["@" + self.users.id2unhl(uid) for uid in athletes]
        athletes = "\n".join(athletes)
        self.driver.reply_to(message, athletes)
    @bot_command(
        category="Admin",
        description="Enable/disable announcements for new activities",
        pattern="admin set announcements ([\s\S]*)",
        admin=True
    )
    async def set_announcements(self, message: Message, value: str):
        if value.lower() == "true":
            self.announcements_enabled = True
            self.driver.reply_to(message, "Announcements enabled")
        elif value.lower() == "false":
            self.announcements_enabled = False
            self.driver.reply_to(message, "Announcements disabled")
        else:
            self.driver.reply_to(message, "Invalid value")
    @bot_command(
        category="Admin",
        description="Set the announcement channel",
        pattern="admin set announcement_channel ([a-z0-9]+)",
        admin=True
    )
    async def chat_set_announcement_channel(self, message: Message, channel_id: str):
        self.set_announcement_channel(channel_id)
        self.driver.reply_to(message, f"Set announcement channel to {channel_id}")
    def set_announcement_channel(self, channel_id: str):
        self.valkey.set(f"{self.intervals_prefix}_announcement_channel", channel_id)
        self.announcement_channel = channel_id
    def get_announcement_channel(self):
        return self.valkey.get(f"{self.intervals_prefix}_announcement_channel")
    @bot_command(
        category="Privacy Settings",
        description="Show all users who have opted in to data sharing",
        pattern="participants"
    )
    async def participants(self, message: Message):
        athletes = self.valkey.smembers(f"{self.intervals_prefix}_athletes_opted_in")
        if not athletes:
            self.driver.reply_to(message, "No participants found. ask them to use .intervals opt-in")
            return
        # convert to usernames
        athletes = ["@" + self.users.id2unhl(uid) for uid in athletes]
        athletes = "\n".join(athletes)
        self.driver.reply_to(message, athletes)

    @bot_command(
        category="Admin",
        description="Enable or disable automatic data sync. Usage: .intervals admin set auto_refresh <true/false>",
        pattern="admin set auto_refresh ([\s\S]*)",  # Hidden regex
        admin=True
    )
    async def set_auto_refresh(self, message: Message, value: str):
        self.valkey.set(f"{self.intervals_prefix}_auto_refresh", value)
        self.driver.reply_to(message, f"Set auto refresh to {value}")

    @bot_command(
        category="Admin",
        description="Set sync interval in seconds. Usage: .intervals admin set refresh_interval <seconds>",
        pattern="admin set refresh_interval ([\s\S]*)",  # Hidden regex
        admin=True
    )
    async def set_refresh_interval(self, message: Message, value: str):
        self.valkey.set(f"{self.intervals_prefix}_refresh_interval", value)
        self.driver.reply_to(message, f"Set refresh interval to {value}")

    @bot_command(
        category="Admin",
        description="Manually trigger synchronization for all athletes",
        pattern="admin refresh all$",
        admin=True
    )
    async def refresh_all(self, message: Message):
        self.refresh_all_athletes(force=True)
        self.driver.reply_to(message, "Refreshed all activities")

    @bot_command(
        category="Admin",
        description="Manually trigger synchronization for all athletes",
        pattern="admin refresh all force$",
        admin=True
    )
    async def refresh_all_force_all(self, message: Message):
        self.refresh_all_athletes(force=True,force_all=True)
        self.driver.reply_to(message, "Refreshed all activities")

    # Help Commands
    @bot_command(
        category="Help",
        description="Display this help message with all available commands",
        pattern="help"
    )
    async def help(self, message: Message):
        help_str = self.generate_help_message()
        self.driver.reply_to(message, help_str)

    async def get_athlete_metrics(self, uid: str, table: str, metric: str|list, date_from: str, date_to: str)->list[dict]:
        """get athlete metrics"""
        # check if we are doing wellness or activities
        if type(metric) == str:
            metric = [metric]
        if table == "wellness":
            data = self.get_wellnesses(uid, date_from, date_to)
            date_field = "id"
        elif table == "activities":
            data = self.get_activities(uid, date_from, date_to)
            date_field = "start_date"
        if not data:
            return []
        # get the metric and return the date and metric
        metrics_rows = []
        for entry in data:
            metrics_vals = {}
            metrics_vals["date"] = getattr(entry, date_field)
            for m in metric:
                val = getattr(entry, m)
                if val is not None:
                    metrics_vals[m] = val
            # check if we have any values exluding the date
            if len(metrics_vals) > 1:
                metrics_rows.append(metrics_vals)
        return metrics_rows

    def parse_period(self, period: str):
        """parse period returns start_date and end_date"""
        """takes in one or more digits + [d, w, m, y]"""
        # get the last character
        period_type = period[-1]
        # get the number
        period_number = int(period[:-1])
        # get the current date
        today = datetime.datetime.now()
        end_date = today.strftime("%Y-%m-%d")
        if period_type == "d":
            if period_number == 1:
                # dont substract 1 day
                start_date = today.strftime("%Y-%m-%d")
            else:
                start_date = (today - datetime.timedelta(days=period_number)).strftime("%Y-%m-%d")
        elif period_type == "w":
            start_date = (today - datetime.timedelta(weeks=period_number)).strftime("%Y-%m-%d")
        elif period_type == "m":
            start_date = (today - datetime.timedelta(days=30*period_number)).strftime("%Y-%m-%d")
        elif period_type == "y":
            start_date = (today - datetime.timedelta(days=365*period_number)).strftime("%Y-%m-%d")
        else:
            raise Exception("Invalid period")
        # add one day to the end date
        end_date = (parser.parse(end_date) + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        return start_date, end_date

    def generate_markdown_table(self, headers, rows):
        # Create the header row
        header_row = "| " + " | ".join(headers) + " |"
        # Create the separator row with appropriate dashes for each header
        separator_row = "|-" + "-|-".join(['-' * len(header) for header in headers]) + "-|"
        # Create the data rows
        data_rows = ["| " + " | ".join(map(str, row)) + " |" for row in rows]

        # Combine all parts into a full table
        table = "\n" + "\n".join([header_row, separator_row] + data_rows) + "\n"
        return table

    def get_table_for_metrics(self, metrics: list, limit: int = 5) -> str:
        """format a table for metrics in a mattermost format"""
        # get the headers
        headers = list(metrics[0].keys())
        pretty_headers = [self.convert_snakecase_and_camelcase_to_ucfirst(header) for header in headers]
        # generate the list of data rows
        rows = [[self.get_metric_to_human_readable(header, metric.get(header)) for header in headers] for metric in metrics]

        # reverse the rows
        rows = rows[::-1]
        # limit the rows
        rows = rows[:limit]

        # generate the table
        table = self.generate_markdown_table(pretty_headers, rows)
        # limit the metrics
        return table
    def get_metric_to_human_readable(self, metric: str, value: any) -> str:
        """get metric to human readable"""
        metric = metric.lower()
        if metric == "date" or "date" in metric:
            # parse and format the date %Y-%m-%d
            f =  parser.parse(value).strftime("%Y-%m-%d %H:%M:%S")
            if f.split(" ")[1] == "00:00:00":
                return f.split(" ")[0]
            return f
        if type(value) == float and metric != "pace":
            # limit to 2 decimal places
            value = round(value, 2)
        if metric == "speed" or "speed" in metric:
            # convert speed in meters per second to km/h
            value = round(value * 3.6, 2)
            return f"{value} km/h"
        if metric == "distance":
            # convert distance in meters to km
            value = round(value/1000, 2)
            return f"{value} km"
        if metric == "duration" or metric == "moving_time":
            # convert seconds to 00:00:00
            return self.seconds_to_human_readable(value)
        if metric == "calories":
            return f"{value} kcal"
        if metric == "steps":
            return f"{value} steps"
        if metric == "weight":
            return f"{value} kg"
        if metric == "sleep" or "sleep" in metric:
            # convert seconds to 00:00:00
            if type(value) == float:
                value = int(value)
            return self.seconds_to_hms(value)
        if metric == "pace":
            if value == 0:
                return "0:00/km"
            # Convert pace from meters per second to mm:ss per kilometer
            seconds_per_km = 1000 / value  # Calculate seconds per kilometer
            return f"{self.seconds_to_hms(seconds_per_km)}/km"
        if metric == "hr" or metric == "heartrate" or "heartrate" in metric:
            return f"{value} bpm"
        return value
    def seconds_to_hms(self, seconds: int) -> str:
        """convert seconds to hh:mm:ss"""
        seconds = int(round(seconds))  # Round to nearest whole number
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        elif minutes > 0:
            return f"{minutes}:{secs:02d}"
        else:
            return f"{secs}s"
    def seconds_to_human_readable(self, seconds: int) -> str:
        """Convert seconds to a human-readable string like '1y 2w 3d 4h 5m 6s'."""
        seconds = int(round(seconds))
        time_units = [
            ('y', 365*24*3600),
            ('w', 7*24*3600),
            ('d', 24*3600),
            ('h', 3600),
            ('m', 60),
            ('s', 1)
        ]
        parts = []
        for suffix, length in time_units:
            value = seconds // length
            if value > 0 or suffix == 's':  # Always show seconds
                parts.append(f"{value}{suffix}")
            seconds %= length
        return ' '.join(parts)

    def get_units_for_metric(self, metric: str) -> str:
        """get units for metric"""
        units = {
            "distance": "km",
            "duration": "minutes",
            "calories": "cal",
            "steps": "steps",
            "weight": "kg",
            "sleep": "hours",
            "hr": "bpm"
        }
        if metric in units:
            return units.get(metric)
        return ""

    def clear_lock(self, lockname: str):
        self.valkey.delete(f"{self.intervals_prefix}_locks_{lockname}")

    def get_lock(self, lockname: str):
        lock = self.helper.str2bool(self.valkey.get(f"{self.intervals_prefix}_locks_{lockname}"))
        if lock:
            return True
        return False

    def refresh_all_athletes(self, force: bool = False, force_all: bool = False):
        """refresh all from all athletes"""
        # self.helper.slog("Refreshing all athletes initiated")
        # create a lock in valkey to prevent multiple refreshes running at the same time
        if self.helper.str2bool(self.get_lock("refresh_all_athletes")):
            # self.helper.slog("Refresh lock is on")
            return
        auto_refresh = self.helper.str2bool(self.valkey.get(f"{self.intervals_prefix}_auto_refresh"))
        # self.helper.slog(f"Auto refresh is {auto_refresh}")
        if not force and not auto_refresh:
            # self.helper.slog(f"Auto refresh is off")
            self.clear_lock("refresh_all_athletes")
            return

        refresh_interval = int(self.valkey.get(f"{self.intervals_prefix}_refresh_interval")) or 3*3600  # 3 hours default
        current_time = int(datetime.datetime.now().timestamp())

        # Check global refresh time
        last_refresh = self.valkey.get(f"{self.intervals_prefix}_last_refresh")
        if not last_refresh:
            last_refresh = str(current_time - 7*24*3600)  # 7 days ago

        if not force and current_time - int(float(last_refresh)) < refresh_interval:
            # self.helper.slog(f"Global refresh too recent. Next refresh in {refresh_interval - (current_time - int(float(last_refresh)))} seconds")
            self.clear_lock("refresh_all_athletes")
            return

        try:
            for athlete in self.athletes:
                athlete_last_refresh = self.valkey.get(f"{self.intervals_prefix}_{athlete}_last_refresh")
                if not athlete_last_refresh:
                    athlete_last_refresh = str(current_time - 7*24*3600)  # 7 days ago

                if not force and current_time - int(float(athlete_last_refresh)) < refresh_interval:
                    self.helper.slog(f"Skipping {self.users.id2u(athlete)} - refreshed too recently")
                    continue

                self.helper.slog(f"Refreshing data for {self.users.id2u(athlete)}")
                try:
                    result = self._scrape_athlete(athlete, force_all=force_all)
                except Exception as e:
                    self.helper.slog(f"Error in refresh_all_athletes: {str(e)}")
                    self.clear_lock("refresh_all_athletes")
                    continue
                if result:
                    self.helper.slog(f"Refreshed data for {self.users.id2u(athlete)} total activities:{len(self.get_activities(athlete))} new:{result.get('activities_added')} changed:{result.get('activities_changed')} & wellness total:{len(self.get_wellnesses(athlete))} new:{result.get('wellnesses_added')} changed:{result.get('wellnesses_changed')}")
                else:
                    self.helper.slog(f"Failed to refresh activities for {self.users.id2u(athlete)}")

        except Exception as e:
            self.helper.slog(f"Failed to refresh all activities: {str(e)}")
            self.clear_lock("refresh_all_athletes")
            return

        self.valkey.set(f"{self.intervals_prefix}_last_refresh", str(current_time))
        self.helper.slog("Refreshed all activities successfully")
        self.clear_lock("refresh_all_athletes")
    @bot_command(
        category="Activity & Wellness Management",
        description="Display your recent wellness entries",
        pattern="wellness"
    )
    async def wellness(self, message: Message):
        uid = message.user_id
        # only return the last 10 wellness entries
        wellness = self.get_wellnesses(uid)
        # reverse the list
        wellness = wellness[::-1][:10]
        if wellness:
            wellness = sorted(wellness, key=lambda x: x.id, reverse=True)
            wellness_str = "Last 10 wellness entries:\n"
            for entry in wellness:
                # print the header
                wellness_str += f"Wellness: {entry.id}\n"
                data = []
                # only print fields that are not None
                for field in entry.__dict__:
                    value = getattr(entry, field)
                    if value is not None:
                        data.append([self.convert_snakecase_and_camelcase_to_ucfirst(field), self.get_metric_to_human_readable(field, value)])
                wellness_str += self.generate_markdown_table(["Field", "Value"], data)
                wellness_str += "--------------------------------\n"
            # limit to 14000 characters
            wellness_str = wellness_str[:14000]
            self.driver.reply_to(message, wellness_str)
        else:
            self.driver.reply_to(message, "No wellness entries found try .intervals refresh data")
    def announce_leaderboards(self):
        """announce leaderboards"""
        leaderboard_str = self.generate_leaderboards()
        channel_id = self.get_announcement_channel()
        if not channel_id:
            return
        # create a message that can act as a container for the leaderboard
        post = self.driver.create_post(channel_id, f"Daily Leaderboard for {datetime.datetime.now().strftime('%Y-%m-%d')}")
        # remove first line from the leaderboard_str
        leaderboard_str = "\n".join(leaderboard_str.split("\n")[1:])
        # post the leaderboard
        self.driver.create_post(channel_id, f"\n{leaderboard_str}", root_id=post.get('id'))

    def generate_leaderboards(self):
        # get the leaderboard for the last 7 days
        # get the metrics for all the athletes
        period = "7d"
        start_date, end_date = self.parse_period(period)
        summable_metrics = ["moving_time","steps","calories", "distance", "kg_lifted"]
        max_metrics = ["pace", "max_speed", "average_speed"]
        metrics = summable_metrics + max_metrics
        all_metrics = {}
        for user in self.athletes:
            if not user in self.opted_in:
                continue
            all_metrics[user] = {}
            for metric in metrics:
                metrics_table = self.lookup_metric_table(metric)
                loop = asyncio.get_event_loop()
                all_metrics[user][metric] = loop.run_until_complete(self.get_athlete_metrics(user, metrics_table, metric, date_from=start_date, date_to=end_date))
        # for each metric get the top 5 and rank them based on the sum of the metric
        leaderboard = {}
        leaderboard_str = f"Leaderboards for the last 7 days {start_date} -> {end_date}\n"
        # make a custom one for count of activities
        leaderboard["activities"] = {}
        # get the count of activities

        for user in self.opted_in:
            leaderboard["activities"][user] = len(self.get_activities(user, oldest=start_date, newest=end_date))
        leaderboard["activities"] = dict(sorted(leaderboard["activities"].items(), key=lambda item: item[1], reverse=True))
        # generate the string for the activities count
        leaderboard_str += f"### Activities\n"
        headers = ["Rank", "Athlete", "Sum"]
        rows = []
        rank = 1
        for user in leaderboard["activities"].keys():
            rows.append([rank, self.users.id2unhl(user), leaderboard["activities"].get(user)])
            rank += 1
        table = self.generate_markdown_table(headers, rows)
        leaderboard_str += table
        leaderboard_str += "--------------------------------\n"
        # get the sum of the metrics
        for metric in metrics:
            leaderboard[metric] = {}
            for user in all_metrics.keys():
                # get the sum of the metric
                metric_val = 0
                metric_val = [met.get(metric,0) for met in all_metrics.get(user).get(metric)]
                if len(metric_val) == 0:
                    continue
                if metric in summable_metrics:
                    metric_val = sum(metric_val)
                elif metric in max_metrics:
                    metric_val = max(metric_val)
                leaderboard[metric][user] = metric_val
            # sort the leaderboard
            leaderboard[metric] = dict(sorted(leaderboard[metric].items(), key=lambda item: item[1], reverse=True))
        # generate the leaderboard

        for metric in metrics:
            leaderboard_str += f"### {self.convert_snakecase_and_camelcase_to_ucfirst(metric)}\n"
            headers = ["Rank", "User", "Value"]
            rows = []
            rank = 1
            for user in leaderboard[metric].keys():
                rows.append([rank, self.users.id2unhl(user), self.get_metric_to_human_readable(metric,leaderboard[metric].get(user))])
                rank += 1
            table = self.generate_markdown_table(headers, rows)
            leaderboard_str += table
            leaderboard_str += "--------------------------------\n"
        return leaderboard_str
    @bot_command(
        category="Leaderboards & Competitions",
        description="Leaderboards for bunch of metrics",
        pattern="leaderboards"
    )
    async def leaderboards(self, message: Message):
        """leaderboards for bunch of metrics"""
        self.driver.reply_to(message, self.generate_leaderboards())
    # command to get next execution time of self.jobs
    @bot_command(
        category="Admin",
        description="Get the next execution time of jobs",
        pattern="admin jobs next"
    )
    async def get_jobs(self, message: Message):
        """get the next execution time of jobs"""
        next_jobs = []
        for name, job in self.jobs.items():
            next_run = job.next_run
            # convert that next_run datetime to seconds
            next_run = next_run.timestamp()
            now = datetime.datetime.now().timestamp()
            next_run = next_run - now
            next_run = self.seconds_to_human_readable(next_run)
            next_jobs.append(f"Job: {name} Next Execution: {next_run}")
        self.driver.reply_to(message, "\n".join(next_jobs))
    @bot_command(
        category="Admin",
        description="Force run all jobs",
        pattern="admin jobs force"
    )
    async def force_jobs(self, message: Message):
        """force run all jobs"""
        for name, job in self.jobs.items():
            job.run()
        self.driver.reply_to(message, "Forced all jobs")
    @bot_command(
        category="Activity & Wellness Management",
        description="Display your recent wellness entries",
        pattern="compare (.*) (.*)"
    )
    async def compare_stats(self,message: Message, metric:str, period:str):
        """compare a stat against other users within a period"""
        # get our own stats for a metric
        uid = message.user_id
        period = period.lower()
        start_date, end_date = self.parse_period(period)
        metrics_table = self.lookup_metric_table(metric)
        if not metrics_table:
            self.driver.reply_to(message, "Invalid metric")
            return
        metrics = await self.get_athlete_metrics(uid, metrics_table, metric, date_from=start_date, date_to=end_date)
        all_metrics = {}
        for user in self.athletes:
            if not metrics_table:
                self.driver.reply_to(message, "Invalid metric")
                return
            # check if the user is opted in
            if not user in self.opted_in:
                continue
            metrics = await self.get_athlete_metrics(user, metrics_table, metric, date_from=start_date, date_to=end_date)
            # store the metrics
            all_metrics[user] = metrics
        # create a table with all of the metrics for all the users the headers should be each user and the rows the metrics for each day
        # get the headers
        # TODO fix this. it is broken
        headers = ["Date"]
        headers.extend([self.users.id2unhl(user) for user in all_metrics.keys()])
        # get the dates
        dates = []
        if metrics_table == "wellness":
            dates = [metric.get("id") for metric in metrics]
        elif metrics_table == "activities":
            dates = [metric.get("start_date") for metric in metrics]
        # create the rows
        rows = []
        for date in dates:
            row = [date]
            for user in all_metrics.keys():
                for metric in all_metrics.get(user):
                    if metric.get("date") == date:
                        row.append(metric.get(metric))
            rows.append(row)
        table = self.generate_markdown_table(headers, rows)

        # generate the table
        self.driver.reply_to(message, table)
