"""shared functions and variables for the project"""

import inspect
import json
import redis
import urllib
import requests
import logging
import os
import dns.resolver
import validators
from duckduckgo_search import DDGS
import ipaddress
import re
from environs import Env
from mmpy_bot.wrappers import Message

env = Env()


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
    REDIS_DB = env.int("REDIS_DB",0)
    """helper functions"""
    REDIS = redis.Redis(host=REDIS_HOST, port=6379, db=REDIS_DB, decode_responses=True)

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

    def create_tmp_filename(self, extension: str, prefix: str = None) -> str:
        """create a tmp filename"""
        import tempfile
        # create a tmp file using tempfile
        if extension.startswith("."):
            extension = extension[1:]
        if prefix is not None:
            return tempfile.mktemp(suffix="."+extension, prefix=prefix)
        return tempfile.mktemp(suffix="."+extension)


    def download_file(self, url: str, filename: str) -> str:
        """download file from url using requests and return the filename/location"""
        request = requests.get(url, allow_redirects=True)
        with open(filename, "wb") as file:
            file.write(request.content)
        return filename

    def download_file_to_tmp(self, url: str, extension: str, prefix: str = None) -> str:
        """download file using requests and return the filename/location"""

        filename = self.create_tmp_filename(extension, prefix=prefix)
        return self.download_file(url, filename)

    def save_content_to_tmp_file(self, content, extension: str, prefix: str = None, binary: bool = False) -> str:
        """save content to a tmp file"""    
        filename = self.create_tmp_filename(extension, prefix=prefix)
        mode = 'wb' if binary else 'w'
        # If it's already bytes, write directly
        if isinstance(content, bytes):
            with open(filename, 'wb') as file:
                file.write(content)
        # If it's string but binary mode, encode it
        elif binary and isinstance(content, str):
            with open(filename, 'wb') as file:
                file.write(content.encode('utf-8'))
        # Otherwise write as text
        else:
            with open(filename, mode) as file:
                file.write(content)
        return filename
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
                    return {"error": f"no dns records found for {input}"}
                # loop over answers6 and answers and check if any of them are private ips
                for answer in [answersc, answers6, answers]:
                    for rdata in answer:
                        # if CNAME record then validate the cname
                        if answer.rdtype == dns.rdatatype.CNAME:
                            result = self.validate_input(
                                str(rdata.target).rstrip("."), ["domain"], count=count
                            )
                            # check if dict
                            if type(result) is dict:
                                if "error" in result:
                                    return {"error": f"cname: {result['error']}"}
                            continue
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

    async def download_webpage(self, url):
        """download a webpage and return the content"""
        self.exit_after_loop = False
        # await self.log(f"downloading webpage {url}")
        validate_result = self.validate_input(url, "url")
        if validate_result != True:
            await self.log(f"Error: {validate_result}")
            return validate_result, None

        max_content_size = 10 * 1024 * 1024  # 10 MB
        # follow redirects
        response = requests.get(
            url,
            headers=self.headers,
            timeout=10,
            verify=True,
            allow_redirects=True,
            stream=True,
        )
        # check the content length before downloading
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_content_size:
            await self.log(
                f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"
            )
            return f"Error: content size exceeds the maximum limit ({max_content_size} bytes)", None

        # download the content in chunks
        content = b""
        total_bytes_read = 0
        chunk_size = 1024  # adjust the chunk size as needed
        for chunk in response.iter_content(chunk_size=chunk_size):
            content += chunk
            total_bytes_read += len(chunk)
            if total_bytes_read > max_content_size:
                await self.log(
                    f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"
                )
                return f"Error: content size exceeds the maximum limit ({max_content_size} bytes)", None
        response_text = content.decode("utf-8")
        # find the file extension from the content type
        content_types = {
            # text types use txt for html since we are extracting text
            "html": { "text/html": "txt" },
            "text": { "application/xml": "xml", "application/json": "json", "text/plain": "txt" },
            "video": { "video/mp4": "mp4", "video/webm": "webm", "video/ogg": "ogg" },
            "image": { "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/svg+xml": "svg" },
            "audio": { "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav" },
            "documents": { "application/pdf": "pdf", "application/msword": "doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx", "application/vnd.ms-excel": "xls" },
            "compressed": { "application/zip": "zip", "application/x-rar-compressed": "rar", "application/x-tar": "tar", "application/x-7z-compressed": "7z" },
        }
        # save response_text to a tmp fil
        blacklisted_tags = ["script", "style", "head", "title", "noscript"]
        # debug response
        # await self.debug(f"response: {pformat(response.text[:500])}")
        # mattermost limit is 4000 characters
        def get_content_type_and_ext(content_type):
            """find the type and extension of the content"""
            for type, types in content_types.items():
                if ";" in content_type:
                    if content_type.split(";")[0] in types:
                        return type, types[content_type.split(";")[0]]
                else:
                    if content_type in types:
                        return type, types[content_type]
            return "unknown", "unknown"
        try:
            if response.status_code == 200:
                # check what type of content we got
                content_type , ext = get_content_type_and_ext(response.headers.get("content-type"))
                # await self.log(f"content_type: {url} {content_type}")
                # html
                if "html" in content_type:
                    # extract all text from the webpage
                    import bs4

                    soup = bs4.BeautifulSoup(response_text, "html.parser")
                    # check if the soup could parse anything
                    try:
                        if soup.find():
                            # soup parsed something lets extract the text
                            # remove all blacklisted tags
                            for tag in blacklisted_tags:
                                for match in soup.find_all(tag):
                                    match.decompose()
                            # get all links and links text from the webpage
                            links = []
                            for link in soup.find_all("a"):
                                links.append(f"{link.get('href')} {link.text}")
                            links = " | ".join(links)
                            # check if title exists and set it to a variable
                            title = soup.title.string if soup.title else ""
                            # extract all text from the body
                            text = soup.body.get_text(separator=" ", strip=True)
                            text_full = soup.body.get_text()
                            # trim all newlines to 2 spaces
                            text = text.replace("\n", "  ")

                            # remove all newlines and replace them with spaces
                            # text = text.replace("\n", " ")
                            # remove all double spaces
                            # save the text to a file
                            text_to_return = f"links:{links}|title:{title}|body:{text}".strip()
                            text_to_save = f"Url: {url}\nTitle: {title}\nLinks: {links}\nBody:\n{text_full}".strip()
                            filename = self.save_content_to_tmp_file(text_to_save, ext)
                            return text_to_return, filename

                    except Exception as e:  # pylint: disable=bare-except
                        await self.log(
                            f"Error: could not parse webpage (Exception) {e}"
                        )
                        return f"Error: could not parse webpage (Exception) {e}", None
                elif content_type == "text":
                    # save the text to a file
                    filename = self.save_content_to_tmp_file(response_text, ext)
                    # text content
                    return response_text, filename
                else:
                    # unknown content type
                    await self.log(
                        f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text[:500]}"
                    )
                    return f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text}", None
            else:
                await self.log(
                    f"Error: could not download webpage (status code {response.status_code})"
                )
                return f"Error: could not download webpage (status code {response.status_code})", None
        except requests.exceptions.Timeout:
            await self.log("Error: could not download webpage (Timeout)")
            return "Error: could not download webpage (Timeout)", None
        except requests.exceptions.TooManyRedirects:
            await self.log(
                "Error: could not download webpage (TooManyRedirects)"
            )
            return "Error: could not download webpage (TooManyRedirects)", None
        except requests.exceptions.RequestException as e:
            await self.log(
                f"Error: could not download webpage (RequestException) {e}"
            )
            return "Error: could not download webpage (RequestException) " + str(e), None
        except Exception as e: # pylint: disable=bare-except
            await self.log(f"Error: could not download webpage (Exception) {e}")
            return "Error: could not download webpage (Exception) " + str(e), None


    async def web_search_and_download(self, searchterm):
        """run the search and download top 2 results from duckduckgo"""
        self.exit_after_loop = False
        downloaded=[]
        localfiles=[]
        await self.log(f"searching the web for {searchterm}")
        results, results_filename = await self.web_search(searchterm)
        if results_filename:
            localfiles.append(results_filename)
        i = 0
        # loop through the results and download the top 2 searches
        for result in results:
            # only download 2 results
            # try all of them in line and stop after 2. zero indexed
            if i >= 2:
                break
            # await self.log(f"downloading webpage {result}")
            try:
                # download the webpage and add the content to the result object
                if "href" not in result:
                    return "Error: href not in result", None
                content, localfile = await self.download_webpage(result.get("href"))
                if localfile:
                    localfiles.append(localfile)
                # await self.log(f"webpage content: {content[:500]}")
                i = i + 1
            except Exception as e:
                await self.log(f"Error: {e}")
                content = None
            if content:
                result["content"] = content
                downloaded.append(result)
            else:
                result["content"] = f"Error: could not download webpage {result.get('href')}"
                downloaded.append(result)
        # await self.log(f"search results: {results}")
        # return the downloaded webpages as json
        return json.dumps(downloaded), localfiles

    async def web_search(self, searchterm):
        """search the web using duckduckgo"""
        self.exit_after_loop = False
        await self.log(f"searching the web using backend=api")

        try:
            results = DDGS().text(keywords=searchterm, backend="api", max_results=10)
            # save to file
            filename = self.save_content_to_tmp_file(json.dumps(results, indent=4), "json")
            return results, filename
        except Exception as e:
            await self.log(f"Error: falling back to html backend")
        await self.log(f"searching the web using backend=html")
        try:
            results = DDGS().text(keywords=searchterm, backend="html", max_results=10)
            # save to file
            filename = self.save_content_to_tmp_file(json.dumps(results, indent=4), "json")
            return results, filename
        except Exception as e:
            await self.log(f"Error: {e}")
            return f"Error: {e}", None
