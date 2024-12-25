from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
from jira import JIRA
# https://jira.readthedocs.io/api.html
from textwrap import dedent


class Jira(PluginLoader):
    def __init__(self):
        super().__init__()
        self.jira_sessions = {}

    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)

    def get_jira_session(self, uid=None):
        if uid is not None:
            try:
                server, username, token = self.get_jira_creds(uid)
                self.jira_sessions[uid] = JIRA(
                    server=server, basic_auth=(username, token))
            except Exception as e:
                raise e
        return self.jira_sessions[uid]

    def delete_jira_session(self, uid):
        if uid in self.jira_sessions:
            del self.jira_sessions[uid]

    def get_jira_creds(self, uid):
        """get jira creds from valkey"""
        creds = self.valkey.hgetall(f"jira:{uid}:creds")
        if len(creds) == 0:
            raise Exception("not logged in")
        server = creds.get("server")
        username = creds.get("username")
        token = creds.get("token")
        return server, username, token

    def jira_get_issues(
        self,
        jira,
        status=None,
        max_results=None,
        sort_asc=None,
        issue_type=None,
        sort_field=None,
        include_reporter=True,
        assignee=None,
    ):
        """get issues"""
        if include_reporter:
            reporter_jql = "OR reporter = currentUser()"
        else:
            reporter_jql = ""
        if assignee == None:
            assignee = "currentUser()"
        else:
            assignee = f"'{assignee}'"
        if sort_field == None:
            sort_field = "created"
        if issue_type == None:
            issue_type = "Story"
        if sort_asc == None:
            sort_asc = False
        else:
            sort_asc = False
        if max_results == None:
            max_results = 100
        if status == None:
            status = "Backlog"

        jql = f"(assignee = {assignee} {reporter_jql})"
        if status and type(status) == str:
            jql += f" AND status = {status}"
        if type(status) == list:
            status_list = ",".join([f"'{i}'" for i in status])
            jql += f" AND status in ({status_list})"
        if issue_type and type(issue_type) == str:
            jql += f" AND issueType = {issue_type}"
        if type(issue_type) == list:
            issue_type_list = ",".join([f"'{i}'" for i in issue_type])
            jql += f" AND issueType in ({issue_type_list})"
        jql += f" ORDER BY {sort_field}"
        if sort_asc:
            jql += " ASC"
        else:
            jql += " DESC"
        return jira.search_issues(
            jql,
            maxResults=max_results,
        )

    @listen_to(r"^\.jira help$")
    async def jira_help(self, message: Message):
        """help text for jira module"""
        if self.users.is_user(message.sender_name):
            messagetxt = (
                f".jira login <server> <username> <password> - login to jira\n"
            )
            messagetxt += f".jira logout - logout from jira\n"
            messagetxt += f".jira issue <issue_id> - get issue details\n"
            messagetxt += f".jira search <query> - search issues\n"
            messagetxt += f".jira assign <issue_id> <assignee> - assign issue\n"
            messagetxt += f".jira comment <issue_id> <comment> - add comment to issue\n"
            messagetxt += f".jira create <project> <summary> <description> - create issue\n"
            messagetxt += f".jira assigned - get assigned issues\n"
            self.driver.reply_to(message, messagetxt)

    @listen_to(r"^\.jira login$")
    async def jira_login_help(self, message: Message):
        """help text for jira login"""
        if self.users.is_user(message.sender_name):
            self.driver.reply_to(
                message, f".jira login <server> <username> <token>")

    @listen_to(r"^\.jira login ([\s\S]*) ([\s\S]*) ([\s\S]*)")
    async def jira_login(self, message: Message, server: str, username: str, token: str):
        """login to jira"""
        if self.users.is_user(message.sender_name):
            # save token to valkey
            uid = self.users.get_uid(message.sender_name)
            self.valkey.hset(f"jira:{uid}:creds", "server", server)
            self.valkey.hset(f"jira:{uid}:creds", "username", username)
            self.valkey.hset(f"jira:{uid}:creds", "token", token)
            # init jira
            try:
                jira = self.get_jira_session(uid)
            except Exception as e:
                self.driver.reply_to(message, f"login failed: {e}")
                return
            try:
                if jira.myself() is not None:
                    self.driver.reply_to(
                        message, f"logged in to {server} as {username}")
                else:
                    self.driver.reply_to(message, f"login failed")
            except Exception as e:
                self.driver.reply_to(message, f"login failed: {e}")

    @listen_to(r"^\.jira logout$")
    async def jira_logout(self, message: Message):
        """logout from jira"""
        if self.users.is_user(message.sender_name):
            uid = self.users.get_uid(message.sender_name)
            self.delete_jira_session(uid)
            self.driver.reply_to(message, f"logged out")

    @listen_to(r"^\.jira assigned$")
    async def jira_assigned(self, message: Message):
        """get assigned issues"""
        if self.users.is_user(message.sender_name):
            uid = self.users.get_uid(message.sender_name)
            try:
                jira = self.get_jira_session(uid)
            except Exception as e:
                self.driver.reply_to(message, f"login first: {e}")
                return
            try:
                issues = self.jira_get_issues(
                    jira, sort_field="updated", sort_asc=True)
                if len(issues) == 0:
                    self.driver.reply_to(message, f"no assigned issues")
                else:
                    for issue in issues:
                        self.driver.reply_to(message, dedent(
                            f"{issue.key} - {issue.fields.summary} - {issue.fields.status} - {issue.fields.created}/{issue.fields.updated}\n{issue.fields.description}"))
            except Exception as e:
                self.driver.reply_to(message, f"error: {e}")
