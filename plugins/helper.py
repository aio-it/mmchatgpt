"""shared functions and variables for the project"""

from mmpy_bot.wrappers import Message
import inspect
import json
import redis
import urllib
import requests
import logging
import uuid
import os
import dns.resolver
import validators
import ipaddress
import re
from environs import Env

env = Env()
import logging


# logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


# Monkey patch message class to extend it.
# this is so dirty, i love it.
def message_from_thread_post(post) -> Message:
    return Message({"data": {"post": post}})


def is_from_self(self, driver) -> bool:
    """check if the message is from the bot"""
    return self.user_id == driver.user_id


Message.create_message = staticmethod(message_from_thread_post)
Message.is_from_self = is_from_self


class Helper:
    REDIS_HOST = env.str("REDIS_HOST", "localhost")
    """helper functions"""
    REDIS = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

    def __init__(self, driver, rediss=None, log_channel=None):
        self.driver = driver
        self.redis = self.REDIS
        self.redis_pool = self.REDIS.connection_pool
        self.log_channel = log_channel
        env_log_channel = env.str("MM_BOT_LOG_CHANNEL", None)
        if self.log_channel is None and env_log_channel is None:
            self.log_to_channel = False
        elif env_log_channel is not None:
            self.log_to_channel = True
            self.log_channel = env_log_channel
        else:
            self.log_to_channel = True
            self.log_channel = self.log_channel

    def redis_serialize_json(self, msg):
        """serialize a message to json"""
        return json.dumps(msg)

    def redis_deserialize_json(self, msg):
        """deserialize a message from json"""
        if isinstance(msg, list):
            return [json.loads(m) for m in msg]
        return json.loads(msg)

    def print_to_console(self, message: Message):
        """print to console"""
        log.info(f"INFO: {message}")

    async def wall(self, message):
        """send message to all admins"""
        for admin_uid in self.redis.smembers("admins"):
            self.driver.direct_message(receiver_id=admin_uid, message=message)

    def get_caller_info(self):
        """get the caller info"""
        stack = inspect.stack()
        callerclass = stack[2][0].f_locals["self"].__class__.__name__
        callerfunc = stack[2][0].f_code.co_name
        return callerclass, callerfunc

    async def log(self, message: str, level="INFO"):
        """send message to log channel"""
        callerclass, callerfunc = self.get_caller_info()
        msg = f"[{callerclass}.{callerfunc}] {message}"
        level = level.upper()
        if level == "INFO":
            log.info(f"LOG: {msg}")
        elif level == "DEBUG":
            log.debug(f"LOG: {msg}")
        if (
            self.log_to_channel and level == "INFO"
        ):  # only log to channel if level is info
            self.driver.create_post(self.log_channel, msg[:4000])

    def slog(self, message: str):
        """sync log"""
        callerclass, callerfunc = self.get_caller_info()
        msg = f"[{callerclass}.{callerfunc}] {message}"
        log.info(f"LOG: {msg}")
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, msg[:4000])

    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        log.debug(f"DEBUG: {message}")
        if self.log_to_channel and not private:
            await self.log(f"DEBUG: {message}", level="DEBUG")

    def add_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by adding a reaction to the thread"""
        self.driver.react_to(message, reaction)

    def remove_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by removing the reaction from the thread"""
        self.driver.reactions.delete_reaction(self.driver.user_id, message.id, reaction)

    def urlencode_text(self, text: str) -> str:
        """urlencode the text"""

        return urllib.parse.quote_plus(text)

    def create_tmp_filename(self, extension: str) -> str:
        """create a tmp filename"""

        return f"/tmp/{uuid.uuid4()}.{extension}"

    def download_file(self, url: str, filename: str) -> str:
        """download file from url using requests and return the filename/location"""

        request = requests.get(url, allow_redirects=True)
        with open(filename, "wb") as file:
            file.write(request.content)
        return filename

    def download_file_to_tmp(self, url: str, extension: str) -> str:
        """download file using requests and return the filename/location"""

        filename = self.create_tmp_filename(extension)
        return self.download_file(url, filename)

    def delete_downloaded_file(self, filename: str):
        """delete the downloaded file"""

        if (
            os.path.exists(filename)
            and os.path.isfile(filename)
            and filename.startswith("/tmp")
        ):
            os.remove(filename)

    def strip_self_username(self, message: str) -> str:
        """remove self mention from the message"""

        return message.replace(f"@{self.driver.client.username}", "").strip()

    def validate_input(self, input, types=["domain", "ip"], allowed_args=[], count=0):
        """function that takes a string and validates that it matches against one or more of the types given in the list"""
        # keep a counter to prevent infinite recursion
        count += 1
        if count > 10:
            return {"error": "infinite recursion detected (10)"}
        bad_chars = [" ", "\n", "\t", "\r", ";", "#", "!"]
        valid_types = [
            "domain",
            "ip",
            "ipv4",
            "ipv6",
            "url",
            "asn",
            "string",
            "argument",
            "port",
        ]
        if types and type(types) is not list:
            types = [types]
        if len(types) == 0:
            return {"error": "no arguments allowed"}
        # check if any of the bad chars exist in input
        for char in bad_chars:
            if char in input:
                return {"error": f"bad char: {char}"}

        for ctype in types:
            if ctype not in valid_types:
                return {"error": f"invalid type: {ctype}"}
        if "domain" in types:
            if validators.domain(input):
                # verify that the ip returned from a dns lookup is not a private ip
                try:
                    answers = dns.resolver.resolve(input, "A")
                except dns.resolver.NoAnswer:
                    answers = []
                except Exception as error:
                    return {"error": f"error resolving domain: {error}"}
                try:
                    answers6 = dns.resolver.resolve(input, "AAAA")
                except dns.resolver.NoAnswer:
                    answers6 = []
                except Exception as error:
                    return {"error": f"error resolving domain: {error}"}
                try:
                    answersc = dns.resolver.resolve(input, "CNAME")
                except dns.resolver.NoAnswer:
                    answersc = []
                except Exception as error:
                    return {"error": f"error resolving domain: {error}"}
                if len(answers) == 0 and len(answers6) == 0 and len(answersc) == 0:
                    return {"error": f"no dns records found for {domain}"}
                # loop over answers6 and answers and check if any of them are private ips
                for a in [answersc, answers6, answers]:
                    for rdata in a:
                        ip = ipaddress.ip_address(rdata.address)
                        if ip.is_private:
                            return {"error": "private ip (resolved from dns)"}
                        if ip.is_reserved:
                            return {"error": "reserved ip (resolved from dns)"}
                        if ip.is_multicast:
                            return {"error": "multicast ip (resolved from dns)"}
                        if ip.is_unspecified:
                            return {"error": "unspecified ip (resolved from dns)"}
                        if ip.is_loopback:
                            return {"error": "loopback ip (resolved from dns)"}
                        if ip.is_link_local:
                            return {"error": "link local ip (resolved from dns)"}
                        # if ipv6
                        if ip.version == 6:
                            if ip.sixtofour is not None:
                                # verify the ipv4 address inside the ipv6 address is not private
                                sixtofour = ipaddress.ip_address(ip.sixtofour)
                                if sixtofour.is_private:
                                    return {"error": "private ip (nice try though)"}
                                if sixtofour.is_reserved:
                                    return {"error": "reserved ip (nice try though)"}
                                if sixtofour.is_multicast:
                                    return {"error": "multicast ip (nice try though)"}
                                if sixtofour.is_unspecified:
                                    return {"error": "unspecified ip (nice try though)"}
                                if sixtofour.is_loopback:
                                    return {"error": "loopback ip (nice try though)"}
                                if sixtofour.is_link_local:
                                    return {"error": "link local ip (nice try though)"}
                return True
        if "ipv4" in types or "ip" in types:
            if validators.ipv4(input):
                # verify that it is not a private ip
                if ipaddress.ip_address(input).is_reserved:
                    return {"error": "reserved ip"}
                if ipaddress.ip_address(input).is_multicast:
                    return {"error": "multicast ip"}
                if ipaddress.ip_address(input).is_unspecified:
                    return {"error": "unspecified ip"}
                if ipaddress.ip_address(input).is_loopback:
                    return {"error": "loopback ip"}
                if ipaddress.ip_address(input).is_private:
                    return {"error": "private ip"}
                return True
        if "ipv6" in types or "ip" in types:
            if validators.ipv6(input):
                # verify that it is not a private ip
                if ipaddress.ip_address(input).is_reserved:
                    return {"error": "reserved ip"}
                if ipaddress.ip_address(input).is_multicast:
                    return {"error": "multicast ip"}
                if ipaddress.ip_address(input).is_unspecified:
                    return {"error": "unspecified ip"}
                if ipaddress.ip_address(input).is_loopback:
                    return {"error": "loopback ip"}
                if ipaddress.ip_address(input).is_link_local:
                    return {"error": "link local ip"}
                if ipaddress.ip_address(input).is_private:
                    return {"error": "private ip"}
                if ipaddress.ip_address(input).sixtofour is not None:
                    # verify the ipv4 address inside the ipv6 address is not private
                    if ipaddress.ip_address(
                        ipaddress.ip_address(input).sixtofour
                    ).is_private:
                        return {"error": "private ip (nice try though)"}
                return True
        if "url" in types:
            if validators.url(input):
                # fetch the url to verify all urls in the redirect chain
                try:
                    # get domain from url and validate it as a domain so we can check if it is a private ip
                    domain = urllib.parse.urlparse(input).netloc
                    if domain == input:
                        # no domain found in url
                        return {"error": "no domain found in url (or localhost)"}
                    # call validateinput again with domain
                    result = self.validate_input(domain, ["domain"], count=count)
                    # check if dict
                    if type(result) is dict:
                        if "error" in result:
                            return {"error": f"domain: {result['error']}"}
                    response = requests.head(
                        input, timeout=10, allow_redirects=True, verify=False
                    )
                    urls = []
                    for r in response.history:
                        if r.is_redirect:
                            if r.status_code in [301, 302, 303, 307, 308]:
                                # call validateinput again with the redirect url
                                urls.append(r.url)
                    # uniq the list
                    urls = list(set(urls))
                    for url in urls:
                        result = self.validate_input(url, ["url"], count=count)
                        # check if dict
                        if type(result) is dict:
                            if "error" in result:
                                return {"error": f"redirect: {result['error']}"}
                except requests.exceptions.RequestException as error:
                    return {"error": f"error fetching url: {error}"}
                return True
        if "asn" in types:
            if re.match(r"(AS|as)[0-9]+", input):
                return True
        if "string" in types:
            if re.match(r"[a-zA-Z0-9_-]+", input):
                return True
        if "port" in types:
            if re.match(r"[0-9]+", input):
                if int(input) > 65535:
                    return {"error": "port can not be higher than 65535"}
                if int(input) < 1:
                    return {"error": "port can not be lower than 1"}
                return True
        if "argument" in types:
            if input in allowed_args:
                return True
        return {
            "error": f"invalid input: {input} (no matches) for types {', '.join(types)}"
        }
