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
import schedule
from plugins.models.intervals_activity import IntervalsActivity
from plugins.models.intervals_wellness import IntervalsWellness, SportInfo
from typing import Dict, List
import inspect
import re
from functools import wraps

def bot_command(category: str, description: str, pattern: str, admin: bool = False):
    """
    Decorator to specify command metadata
    
    Args:
        category: Command category for grouping
        description: Help description
        pattern: Command pattern (without .intervals prefix)
        admin: Whether command requires admin privileges
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
        self.opted_in = self.valkey.smembers(f"{self.intervals_prefix}_athletes_opted_in") or set()

        # jobs
        self.jobs = {}
        self.jobs['refresh_all_athletes'] = schedule.every(self._INTERNAL_TIMER_LOOP).seconds.do(self.refresh_all_athletes)
        self.jobs['cleanup_duplicates'] = schedule.every(1).days.do(self.cleanup_duplicates_for_all_athletes)
        self.jobs['cleanup_broken_athletes'] = schedule.every(1).days.do(self.cleanup_broken_athletes)

        # check if the key auto_refresh is set if not set it to true
        if not self.valkey.exists(f"{self.intervals_prefix}_auto_refresh"):
            self.valkey.set(f"{self.intervals_prefix}_auto_refresh", "true")
            self.valkey.set(f"{self.intervals_prefix}_refresh_interval", "900")

        # clear refresh lock
        self.clear_lock("refresh_all_athletes")

        # run the jobs on startup
        self.refresh_all_athletes()
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
        if activities:
            activities = sorted(activities, key=lambda x: x.id)
            for i in range(1, len(activities)):
                if activities[i].id == activities[i-1].id:
                    self.remove_activity(uid, activities[i].to_dict())
        if wellness:
            wellness = sorted(wellness, key=lambda x: x.id)
            for i in range(1, len(wellness)):
                if wellness[i].id == wellness[i-1].id:
                    self.helper.log(f"Removing duplicate wellness for user {self.users.id2u(uid)} - {wellness[i].id}")
                    self.remove_wellness(uid, wellness[i].to_dict())

    def return_pretty_activities(self, activities: list[IntervalsActivity]):
        """return pretty activities"""
        pretty = []
        for activity in activities:
            pretty.append(f"{activity.start_date_local} {activity.type} {activity.name} {activity.distance} {activity.moving_time} {activity.calories}")
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
        return "added"

    def generate_and_set_metric_lookup_table(self) -> dict:
        """generate and set the metric table from wellness and activities"""
        mappings = {}
        # fetch one activity and one wellness and check if the metric is in the activity or wellness
        for uid in self.athletes:
            activities = self.get_activities(uid)
            if activities:
                for act in activities:
                    for key in act:
                        mappings[key] = "activities"
                    # break after the first activity
                    break
            wellness = self.get_wellnesses(uid)
            if wellness:
                for well in wellness:
                    for key in well:
                        mappings[key] = "wellness"
                    # break after the first wellness
                    break
            # break after the first athlete
            break
        self.metric_lookup_table = mappings
        return self.metric_lookup_table
    
    def lookup_metric_in_table(self, metric: str) -> str:
        """get the table where the metric is stored"""
        if not hasattr(self, "metric_lookup_table"):
            self.generate_and_set_metric_lookup_table()
        return self.metric_lookup_table.get(metric, "activities")

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
                return [activity for activity in activities 
                       if parser.parse(oldest) <= parser.parse(activity.start_date) <= parser.parse(newest)]
            return activities
        return []

    def add_wellness(self, uid: str, wellness: IntervalsWellness) -> str:
        """Add a wellness entry to storage"""
        wellness_id = wellness.id
        wellnesses = self.get_wellnesses(uid)
        if wellnesses:
            for i, well in enumerate(wellnesses):
                if well.id == wellness_id:
                    if well == wellness:
                        return "alreadyexists"
                    self.remove_wellness(uid, well.to_dict())
                    self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_wellness", wellness.to_json())
                    return "changed"
        if self.valkey.exists(f"{self.intervals_prefix}_athlete_{uid}_wellness"):
            if wellness.to_json() in self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1):
                return "alreadyexists"
        self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_wellness", wellness.to_json())
        return "added"

    def remove_wellness(self, uid: str, wellness: dict):
        """remove wellness"""
        self.valkey.lrem(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, json.dumps(wellness))

    def get_wellnesses(self, uid: str, oldest: str | None = None, newest: str | None = None) -> list[IntervalsWellness]:
        """get wellness"""
        wellnesses = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1)
        if wellnesses:
            # Convert JSON strings to IntervalsWellness objects
            wellnesses = [IntervalsWellness.from_dict(json.loads(wellness)) for wellness in wellnesses]
            # Sort by id (date)
            wellnesses = sorted(wellnesses, key=lambda x: x.id)
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
            self.helper.slog(f"Getting activities from intervals {oldest_activity} to {newest}")
            response = self._request("activities", "GET", uid=uid, data=params_activity)
            if response.status_code == 200:
                activities_data = response.json()
                for activity_data in activities_data:
                    self.helper.slog(f"Got activity: {self.users.id2u(uid)} - {activity_data.get('start_date')} - {activity_data.get('id')}")
                    activity = IntervalsActivity.from_dict(activity_data)
                    result = self.add_activity(uid, activity)
                    if result == "added":
                        activities_added += 1
                    elif result == "changed":
                        activities_changed += 1
            else:
                self.helper.slog("Failed to get activities")
                self.helper.slog(response.status_code)

            # get wellness
            self.helper.slog(f"Getting wellness from intervals {oldest_wellness} to {newest}")
            response = self._request("wellness", "GET", uid=uid, data=params_wellness)
            if response.status_code == 200:
                wellness_data = response.json()
                for wellness_entry in wellness_data:
                    self.helper.slog(f"Got wellness: {self.users.id2u(uid)} - {wellness_entry.get('id')}")
                    wellness = IntervalsWellness.from_dict(wellness_entry)
                    result = self.add_wellness(uid, wellness)
                    if result == "added":
                        wellnesses_added += 1
                    elif result == "changed":
                        wellnesses_changed += 1
            else:
                self.helper.slog("Failed to get wellness")
                self.helper.slog(response.status_code)

            self.valkey.set(f"{self.intervals_prefix}_{uid}_last_refresh", str(int(datetime.datetime.now().timestamp())))
            
        except Exception as e:
            self.helper.slog(f"Error in _scrape_athlete: {str(e)}")
            return False

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
        if activities:
            activities = sorted(activities, key=lambda x: x.start_date, reverse=True)
            activities_str = ""
            for activity in activities:
                # only print fields that are not None
                # print the header
                activities_str += f"Activity: {activity.start_date} - {activity.type} - {activity.name}\n"
                data = []
                for key, value in activity.to_dict().items():
                    if value:
                        data.append([key, value])
                activities_str += self.generate_markdown_table(["Field", "Value"], data)
                activities_str += "--------------------------------\n"
            self.driver.reply_to(message, activities_str)
        else:
            self.driver.reply_to(message, "No activities found try .intervals refresh data")

    @bot_command(
        category="Activity & Wellness Management",
        description="Delete all your stored activities and wellness data",
        pattern="reset data"
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
        result = self._scrape_athlete(uid, force_all=True)
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
        refresh_interval = int(self.valkey.get(f"{self.intervals_prefix}_refresh_interval")) or 900  # 15 minutes default
        current_time = int(datetime.datetime.now().timestamp())
        last_refresh = self.valkey.get(f"{self.intervals_prefix}_{uid}_last_refresh")
        if last_refresh:
            if current_time - int(float(last_refresh)) < 900:
                self.driver.reply_to(message, f"Refresh too recent wait {refresh_interval - (current_time - int(float(last_refresh)))} seconds")
                return
        result = self._scrape_athlete(uid)
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
        pattern="(steps|weight|distance|hr) ([0-9]+[ymdw])"  # Hidden regex
    )
    async def get_user_metrics(self, message: Message, metric: str, period: str):
        uid = message.user_id
        # parse the period
        try:
            date_from, date_to = self.parse_period(period)
        except Exception:
            self.driver.reply_to(message, "Invalid period")
            return
        metrics_table = self.lookup_metric_in_table(metric)
        metrics = await self.get_athlete_metrics(uid, metrics_table, metric, date_from=date_from, date_to=date_to)
        msg = ""
        msg += f"Showing {metric} for {self.users.id2unhl(uid)} from {str(date_from)} to {str(date_to)}"
        if metrics:
            # do some calculations
            metric_sum = 0
            for met in metrics:
                metric_sum += int(met.get(metric) or 0)
            # dont show hr and weight totals
            if metric not in ["hr", "weight"]:
                msg += f"\nTotal {metric} {metric_sum}"
            # lets calculate two averages. one for the period and one for the active days
            active_days = len(metrics)
            total_days = (parser.parse(date_to) - parser.parse(date_from)).days
            inactive_days = total_days - active_days
            if active_days:
                msg += f"\nAverage {metric} for the period on active days {metric_sum/active_days}"
                msg += f"\nActive days {active_days}"
            if total_days:
                msg += f"\nAverage {metric} for the total period {metric_sum/total_days}"
                msg += f"\nTotal days {total_days}"
            if inactive_days:
                msg += f"\nInactive days {inactive_days}"
            # lets get the median
            metric_median = 0
            metric_vals = [int(met.get(metric) or 0) for met in metrics]
            if metric_vals:
                metric_vals.sort()
                if len(metric_vals) % 2 == 0:
                    metric_median = (metric_vals[len(metric_vals)//2] + metric_vals[len(metric_vals)//2 - 1]) / 2
                else:
                    metric_median = metric_vals[len(metric_vals)//2]
                msg += f"\nMedian {metric} {metric_median}"
            # lets get the min and max
            metric_min =   min([int(met.get(metric) or 0) for met in metrics])
            metric_max =   max([int(met.get(metric) or 0) for met in metrics])
            # find the date for the min and max
            metric_min_date = [met.get("date") for met in metrics if int(met.get(metric) or 0) == metric_min]
            metric_max_date = [met.get("date") for met in metrics if int(met.get(metric) or 0) == metric_max]
            msg += f"\nMin {metric} {metric_min} on {metric_min_date}"
            msg += f"\nMax {metric} {metric_max} on {metric_max_date}"
            limit = 100
            msg += f"\n\nData (Limited to showing only the latest {limit} entries calculations are performed in the entire period):\n"
            msg += self.get_template_for_metrics(metrics, limit=limit)
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
        pattern="admin refresh all",
        admin=True
    )
    async def refresh_all(self, message: Message):
        self.refresh_all_athletes()
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
                val = getattr(entry, m, None)
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
            start_date = (today - datetime.timedelta(days=period_number)).strftime("%Y-%m-%d")

        elif period_type == "w":
            start_date = (today - datetime.timedelta(weeks=period_number)).strftime("%Y-%m-%d")
        elif period_type == "m":
            start_date = (today - datetime.timedelta(days=30*period_number)).strftime("%Y-%m-%d")
        elif period_type == "y":
            start_date = (today - datetime.timedelta(days=365*period_number)).strftime("%Y-%m-%d")
        else:
            raise Exception("Invalid period")
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

    def get_template_for_metrics(self, metrics: list, limit: int = 5) -> str:
        """format a table for metrics in a mattermost format"""
        # get the headers
        headers = list(metrics[0].keys())
        # generate the list of data rows
        rows = [[metric.get(header) for header in headers] for metric in metrics]

        # reverse the rows
        rows = rows[::-1]
        # limit the rows
        rows = rows[:limit]

        # generate the table
        table = self.generate_markdown_table(headers, rows)
        # limit the metrics
        return table

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

    def refresh_all_athletes(self):
        """refresh all from all athletes"""
        self.helper.slog("Refreshing all athletes initiated")
        # create a lock in valkey to prevent multiple refreshes running at the same time
        if self.helper.str2bool(self.get_lock("refresh_all_athletes")):
            self.helper.slog("Refresh lock is on")
            return
        auto_refresh = self.helper.str2bool(self.valkey.get(f"{self.intervals_prefix}_auto_refresh"))
        self.helper.slog(f"Auto refresh is {auto_refresh}")
        if not auto_refresh:
            self.helper.slog(f"Auto refresh is off")
            self.clear_lock("refresh_all_athletes")
            return

        refresh_interval = int(self.valkey.get(f"{self.intervals_prefix}_refresh_interval")) or 3*3600  # 3 hours default
        current_time = int(datetime.datetime.now().timestamp())
        
        # Check global refresh time
        last_refresh = self.valkey.get(f"{self.intervals_prefix}_last_refresh")
        if not last_refresh:
            last_refresh = str(current_time - 7*24*3600)  # 7 days ago
        
        if current_time - int(float(last_refresh)) < refresh_interval:
            self.helper.slog(f"Global refresh too recent. Next refresh in {refresh_interval - (current_time - int(float(last_refresh)))} seconds")
            self.clear_lock("refresh_all_athletes")
            return

        try:
            for athlete in self.athletes:
                athlete_last_refresh = self.valkey.get(f"{self.intervals_prefix}_{athlete}_last_refresh")
                if not athlete_last_refresh:
                    athlete_last_refresh = str(current_time - 7*24*3600)  # 7 days ago

                if current_time - int(float(athlete_last_refresh)) < refresh_interval:
                    self.helper.slog(f"Skipping {self.users.id2u(athlete)} - refreshed too recently")
                    continue

                self.helper.slog(f"Refreshing data for {self.users.id2u(athlete)}")
                result = self._scrape_athlete(athlete)
                if result:
                    self.helper.slog(f"Refreshed data for {self.users.id2u(athlete)} total:{result.get('activities_added') + result.get('activities_changed')} new:{result.get('activities_added')} changed:{result.get('activities_changed')} & wellness total:{result.get('wellnesses_added') + result.get('wellnesses_changed')} new:{result.get('wellnesses_added')} changed:{result.get('wellnesses_changed')}")
                else:
                    self.helper.slog(f"Failed to refresh activities for {self.users.id2u(athlete)}")

        except Exception as e:
            self.helper.slog(f"Failed to refresh all activities: {str(e)}")
            self.clear_lock("refresh_all_athletes")
            return

        self.valkey.set(f"{self.intervals_prefix}_last_refresh", str(current_time))
        self.helper.slog("Refreshed all activities successfully")
        self.clear_lock("refresh_all_athletes")
