from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader


class LogManager(PluginLoader):
    def __init__(self):
        super().__init__()
        self.log_to_channel = False
        self.log_channel = None

    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)
        self.log_to_channel = self.helper.log_to_channel
        self.log_channel = self.helper.log_channel
        self.my_user_id = self.driver.user_id
        

    @listen_to(r"^\.logs purge ([0-9]+) ([0-9]+)$")
    async def log_purge(self, message: Message, lines_to_keep: int, max_requests: int):
        if self.users.is_admin(message.sender_name):
            if self.log_to_channel:
                # get all messages from the channel
                posts_to_delete = []
                post_order = []
                page = 0
                per_page = 200
                lines_to_keep = int(lines_to_keep)
                if lines_to_keep < 0:
                    lines_to_keep = 0
                # unixtime in ms now - 1 day
                import time
                import datetime
                #delete_before = (time.time() * 1000) - (3 * 60 * 1000)
                #delete_before_dt = datetime.datetime.fromtimestamp(delete_before / 1000)
                request_count = 0
                if not max_requests:
                    max_requests = 0
                max_requests = int(max_requests)
                delete_immediately = False
                while True:
                    messages = self.driver.posts.get_posts_for_channel(channel_id=self.log_channel, params={"page": page, "per_page": per_page})
                    request_count += 1
                    posts = messages.get("posts", {})
                    post_order = messages.get("order", [])
                    for post_id in post_order:
                        # only delete messages from the bot
                        if posts[post_id]["user_id"] != self.my_user_id:
                            #self.helper.slog(f"Skipping message from {posts[post_id]['user_id']}")
                            continue
                        # if it is not type = "text" then continue
                        #if posts[post_id]["type"] != "text":
                        #    self.helper.slog(f"Skipping message type {posts[post_id]['type']}")
                        #    continue
                        # only delete messages older than 1 day
                        #if posts[post_id]["create_at"] > delete_before:
                        #    #self.helper.slog(f"Skipping message before {posts[post_id]['create_at']} > {delete_before}")
                        #    continue
                        # delete the post
                        #self.helper.slog(f"Deleting message {post_id}")
                        if delete_immediately:
                            self.driver.posts.delete_post(post_id)
                            request_count += 1
                        posts_to_delete.append(post_id)
                        if max_requests and request_count >= max_requests:
                            break
                    if len(post_order) < per_page or (max_requests and request_count >= max_requests):
                        break
                    page += 1

                if not delete_immediately:
                    # sort posts by id
                    posts_to_delete = sorted(posts_to_delete)
                    # keep the last 100
                    posts_to_delete = posts_to_delete[:-lines_to_keep]
                    for post_id in posts_to_delete:
                        self.driver.posts.delete_post(post_id)
                        request_count += 1

                if len(posts_to_delete):
                    self.driver.reply_to(message, f"Deleted {len(posts_to_delete)} messages from the log channel {self.log_channel} and made {request_count} (max: {max_requests}) requests.")
                else:
                    self.driver.reply_to(message, f"No messages found in the log channel {self.log_channel} and made {request_count} (max: {max_requests}) requests.")