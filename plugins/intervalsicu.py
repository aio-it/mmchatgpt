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

class IntervalsIcu(PluginLoader):
    """IntervalsIcu plugin"""
    _INTERNAL_TIMER_LOOP = 300
    def __init__(self):
        super().__init__()

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
            activities = sorted(activities, key=lambda x: x.get("id"))
            for i in range(1, len(activities)):
                if activities[i].get("id") == activities[i-1].get("id"):
                    self.remove_activity(uid, activities[i])
        if wellness:
            wellness = sorted(wellness, key=lambda x: x.get("id"))
            for i in range(1, len(wellness)):
                if wellness[i].get("id") == wellness[i-1].get("id"):
                    self.helper.log(f"Removing duplicate wellness for user {self.users.id2u(uid)} - {wellness[i].get('id')}")
                    self.remove_wellness(uid, wellness[i])

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

    def add_activity(self, uid: str, activity: dict) -> str:
        # we need to account for updated activities
        # get the id of the activity
        activity_id = activity.get("id")
        activities = self.get_activities(uid)
        if activities:
            for i, act in enumerate(activities):
                if act.get("id") == activity_id:
                    # compare the whole object as json
                    if json.dumps(act) == json.dumps(activity):
                        return "alreadyexists"
                    # remove the old activity
                    self.remove_activity(uid, act)
                    # add the new activity
                    self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_activities", json.dumps(activity))
                    return "changed"
        # check if the list exists
        if self.valkey.exists(f"{self.intervals_prefix}_athlete_{uid}_activities"):                
            # check if activity already exists
            #self.helper.slog(self.return_pretty_activities([activity]))
            if json.dumps(activity) in self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, -1):
                return "alreadyexists"

        self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_activities", json.dumps(activity))
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

    def get_activities(self, uid: str, oldest: str | None = None, newest: str | None = None):
        activities = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_activities", 0, -1)
        # if activities:
        #     for activity in activities:
        #         activity = json.loads(activity)
        #         start_date = activity.get("start_date")
        #         id = activity.get("id")
        #         self.helper.slog(f"{uid} - activity: {start_date} {id} len: {len(json.dumps(activity))}")
        # decode the json
        if activities:
            # sort activities by start_date
            activities = sorted(activities, key=lambda x: json.loads(x).get("start_date"))
            if oldest and newest:
                return [json.loads(activity) for activity in activities if parser.parse(oldest) <= parser.parse(json.loads(activity).get("start_date")) <= parser.parse(newest)]
            return [json.loads(activity) for activity in activities]
        return []

    def add_wellness(self, uid: str, wellness: dict) -> str:
        """add wellness"""
        # we need to account for updated wellness since wellness's id is the date we cant and we need to compare the whole object
        # get the id of the wellness
        wellness_id = wellness.get("id")
        wellnesses = self.get_wellnesses(uid)
        if wellnesses:
            for i, well in enumerate(wellnesses):
                if well.get("id") == wellness_id:
                    # compare the whole object as json
                    if json.dumps(well) == json.dumps(wellness):
                        return "alreadyexists"
                    # remove the old wellness
                    self.remove_wellness(uid, well)
                    # add the new wellness
                    self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_wellness", json.dumps(wellness))
                    return "changed"
        # check if the list exists
        if self.valkey.exists(f"{self.intervals_prefix}_athlete_{uid}_wellness"):
            # check if wellness already exists
            if json.dumps(wellness) in self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1):
                return "alreadyexists"
        self.valkey.lpush(f"{self.intervals_prefix}_athlete_{uid}_wellness", json.dumps(wellness))
        return "added"

    def remove_wellness(self, uid: str, wellness: dict):
        """remove wellness"""
        self.valkey.lrem(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, json.dumps(wellness))

    def get_wellnesses(self, uid: str, oldest: str | None = None, newest: str | None = None):
        """get wellness"""
        wellnesses = self.valkey.lrange(f"{self.intervals_prefix}_athlete_{uid}_wellness", 0, -1)
        # decode the json
        if wellnesses:
            # sort wellness by id (date)
            wellnesses = sorted(wellnesses, key=lambda x: json.loads(x).get("id"))
            # for wellness in wellnesses:
            #     wellness = json.loads(wellness)
            #     id = wellness.get("id")
            #     self.helper.slog(f"{uid} - wellness: {id} len: {len(json.dumps(wellness))}")
            if oldest and newest:
                return [json.loads(wellness) for wellness in wellnesses if parser.parse(oldest) <= parser.parse(json.loads(wellness).get("id")) <= parser.parse(newest)]
            return [json.loads(wellness) for wellness in wellnesses]
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
        # date format is YYYY-MM-DD
        # oldest set it to the previous month
        # newest set it to the current month and day + 1
        today = datetime.datetime.now()
        newest = (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        # first lets try and get the oldest activity from the user
        activities = self.get_activities(uid)
        wellness = self.get_wellnesses(uid)
        wellnesses_added = 0
        activities_added = 0
        wellnesses_changed = 0
        activities_changed = 0
        if activities:
            oldest_activity = parser.parse(activities[-1].get("start_date")).strftime("%Y-%m-%d")
            # substract 3 days from the oldest activity
            oldest_activity = (parser.parse(oldest_activity) - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        else:
            oldest_activity = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        if wellness:
            oldest_wellness = parser.parse(wellness[-1].get("id")).strftime("%Y-%m-%d")
            # substract 3 days from the oldest wellness
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
                activities = response.json()
                for activity in activities:
                    self.helper.slog(f"Got activity: {self.users.id2u(uid)} - {activity.get('start_date')} - {activity.get('id')}")
                    result = self.add_activity(uid, activity)
                    if result == "added":
                        activities_added += 1
                    elif result == "changed":
                        activities_changed += 1
            else:
                self.helper.slog("Failed to get activities")
                self.helper.slog(response.status_code)
            # update last refresh time for the athlete using Unix timestamp

            # get wellness
            self.helper.slog(f"Getting wellness from intervals {oldest_wellness} to {newest}")
            response = self._request("wellness", "GET", uid=uid, data=params_wellness)
            if response.status_code == 200:
                wellness = response.json()
                for wellness in wellness:
                    self.helper.slog(f"Got wellness: {self.users.id2u(uid)} - {wellness.get('id')}")
                    result = self.add_wellness(uid, wellness)
                    if result == "added":
                        wellnesses_added += 1
                    elif result == "changed":
                        wellnesses_changed += 1
            else:
                self.helper.slog("Failed to get wellness")
                self.helper.slog(response.status_code)

            # update last refresh time for the athlete using Unix timestamp
            self.valkey.set(f"{self.intervals_prefix}_{uid}_last_refresh", str(int(datetime.datetime.now().timestamp())))
        except Exception:
            return False
        return {"activities_added": activities_added, "activities_changed": activities_changed, "wellnesses_added": wellnesses_added, "wellnesses_changed": wellnesses_changed}

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
            # sort activities by date
            activities = sorted(activities, key=lambda x: x.get("start_date"))
            activities_str = "\n".join(self.return_pretty_activities(activities))
            self.driver.reply_to(message, activities_str)
        else:
            self.driver.reply_to(message, "No activities found try .intervals refresh data")
    @listen_to(r"^.intervals refresh data force")
    async def refresh_force(self, message: Message):
        """force refresh activities"""
        uid = message.user_id
        result = self._scrape_athlete(uid, force_all=True)
        # count the number of activities and wellness
        wellness_count_new = len(self.get_wellnesses(uid))
        activities_count_new = len(self.get_activities(uid))
        if result:
            self.driver.reply_to(message, f"Refreshed activities newly total:{activities_count_new} new:{result.get('activities_added')} changed:{result.get('activities_changed')} & wellness total:{wellness_count_new} new:{result.get('wellnesses_added')} changed:{result.get('wellnesses_changed')}")
        else:
            self.driver.reply_to(message, "No new activities & wellness found")
    @listen_to(r"^\.intervals refresh data$")
    async def refresh(self, message: Message):
        """refresh activities"""
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
    @listen_to(r"^\.intervals reset data")
    async def reset(self, message: Message):
        """reset activities"""
        uid = message.user_id
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_activities")
        self.valkey.delete(f"{self.intervals_prefix}_athlete_{uid}_wellness")
        self.driver.reply_to(message, "Activities & Wellness reset")
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
    @listen_to(r"^\.intervals profile")
    async def profile(self, message: Message):
        """get profile"""
        uid = message.user_id
        # valkey stored profile
        profile = self.valkey.hgetall(f"{self.intervals_prefix}_profiles", uid)
        if profile:
            self.driver.reply_to(message, profile)
            return
    @listen_to(r"^\.intervals profile set ([\s\S]*) ([\s\S]*)")
    async def profile_set(self, message: Message, key: str, value: str):
        """set profile key value"""
        uid = message.user_id
        self.valkey.hset(f"{self.intervals_prefix}_profiles", uid, {key: value})
        self.driver.reply_to(message, f"Set {key} to {value}")
    @listen_to(r"^\.intervals admin set auto_refresh ([\s\S]*)")
    async def set_auto_refresh(self, message: Message, value: str):
        """set auto refresh"""
        if not self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, "You need to be an admin to use this command")
            return
        self.valkey.set(f"{self.intervals_prefix}_auto_refresh", value)
        self.driver.reply_to(message, f"Set auto refresh to {value}")
    @listen_to(r"^\.intervals admin set refresh_interval ([\s\S]*)")
    async def set_refresh_interval(self, message: Message, value: str):
        """set refresh interval"""
        if not self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, "You need to be an admin to use this command")
            return
        self.valkey.set(f"{self.intervals_prefix}_refresh_interval", value)
        self.driver.reply_to(message, f"Set refresh interval to {value}")
    @listen_to(r"^\.intervals admin refresh all")
    async def refresh_all(self, message: Message):
        """refresh all data"""
        if not self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, "You need to be an admin to use this command")
            return
        self.refresh_all_athletes()
        self.driver.reply_to(message, "Refreshed all activities")
    async def get_athlete_metrics(self, uid: str, table: str, metric: str|list, date_from: str, date_to: str)->list[dict]:
        """get athlete metrics"""
        # check if we are doing wellness or activities
        if type(metric) == str:
            metric = [metric]
        if table == "wellness":
            data = self.get_wellnesses(uid, date_from, date_to)
            date_field = "id"
        elif table == "activities":
            data = self.get_activities(uid)
            date_field = "start_date"
        if not data:
            return []
        # get the metric and return the date and metric
        metrics_rows = []
        for entry in data:
            metrics_vals = {}
            metrics_vals["date"] = entry.get(date_field)
            for m in metric:
                if m in entry:
                    val = entry.get(m)
                    if val is not None:
                        metrics_vals[m] = entry.get(m)
            # check if we have any values exluding the date
            if len(metrics_vals) > 1:
                metrics_rows.append(metrics_vals)
        return metrics_rows
    def parse_period(self, period: str):
        """parse period returns start_date and end_date"""
        """takes in one or more digits + [d, w, m, y]"""
        """d - day, w - week, m - month, y - year"""
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
    @listen_to(r"^\.intervals (steps|weight|distance|hr) ([0-9]+[ymdw])")
    async def get_user_metrics(self, message: Message, metric: str, period: str):
        """get steps"""
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
            msg += "\n\nData (Limited to showing only the latest {limit} entries calculations are performed in the entire period):\n"
            msg += self.get_template_for_metrics(metrics, limit=limit)
            self.driver.reply_to(message, msg)
        else:
            self.driver.reply_to(message, f"No {metric} found")
    @listen_to(r"^\.intervals help")
    async def help(self, message: Message):
        """help"""
        help_str = """
        Login commands:
        .intervals login [api_key] - login
        .intervals opt-in - opt in to public usage
        .intervals opt-out - opt out of public usage
        .intervals logout - logout
        .intervals verify - verify the api key

        Personal Information commands:
        .intervals profile - get profile
        .intervals profile set [profile_key] [value] - set profile key value

        Personal Activity & wellness commands:
        .intervals activities - get activities
        .intervals refresh data force - force refresh activities & wellness (use with caution)
        .intervals refresh data - refresh activities & wellness
        .intervals reset data - reset activities & wellness
        .intervals (steps|weight|distance|hr) [period] - get metrics for the specified period (e.g., 7d, 1m, 1y)

        Public commands (opt-in required):
        .intervals participants - get participants (athletes who opted in)

        Help:
        .intervals help - get help

           * MEANS NOT IMPLEMENTED YET (and might not be implemented let me know if you need it)

        Parameters:
        [metric] - distance, duration, calories, steps, count, weight
        [goal] - number
        [enddate] - YYYY-MM-DD
        [startdate] - YYYY-MM-DD
        [profile_key] - height, weight(only for starting reference will be used for goals)
        [recurring_period] - daily, weekly, monthly, yearly
        [name] - string
        [username] - mattermost username
     
        Admin only commands:
        .intervals admin athletes - get athletes (admin only)
        .intervals admin refresh all - refresh all data (admin only)
        .intervals admin set auto_refresh [true/false] - set auto refresh (admin only)
        .intervals admin set refresh_interval [interval in seconds] - set refresh interval (admin only)
        """
        self.driver.reply_to(message, help_str)
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
