"""shared functions and variables for the project"""

import inspect
import ipaddress
import json
import logging
import mimetypes
import os
import re
import tempfile
import urllib

import bs4
import dns.resolver
import magic
import requests
import validators
import valkey
from googlesearch import search as googlesearch
from environs import Env
from mmpy_bot.wrappers import Message

env = Env()

# logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


# Monkey patch message class to extend it.
# this is so dirty, i love it.
def message_from_thread_post(post) -> Message:
    """create a message from a thread post"""
    return Message({"data": {"post": post}})


def is_from_self(self, driver) -> bool:
    """check if the message is from the bot"""
    return self.user_id == driver.user_id


Message.create_message = staticmethod(message_from_thread_post)
Message.is_from_self = is_from_self


class Helper:
    """helper class for the bot"""
    VALKEY_HOST = env.str("VALKEY_HOST", "localhost")
    VALKEY_DB = env.int("VALKEY_DB", 0)
    REDIS_HOST = env.str("REDIS_HOST", "localhost")
    REDIS_DB = env.int("REDIS_DB", 0)

    def __init__(self, driver, log_channel=None):
        self.driver = driver
        # fallback to REDIS instead of valkey if VALKEY_HOST is not set
        if self.VALKEY_HOST == "localhost" and self.REDIS_HOST != "localhost":
            self.VALKEY_HOST = self.REDIS_HOST
            self.VALKEY_DB = self.REDIS_DB
        self.valkey = valkey.Valkey(host=self.VALKEY_HOST, port=6379,
                        db=self.VALKEY_DB, decode_responses=True, protocol=3)
        self.valkey_pool = self.valkey.connection_pool
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
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"

        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.7,da;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def valkey_serialize_json(self, msg):
        """serialize a message to json"""
        return json.dumps(msg)

    def valkey_deserialize_json(self, msg):
        """deserialize a message from json"""
        if isinstance(msg, list):
            return [json.loads(m) for m in msg]
        return json.loads(msg)

    def print_to_console(self, message: Message):
        """print to console"""
        log.info("INFO: %s", message)

    async def wall(self, message):
        """send message to all admins"""
        for admin_uid in self.valkey.smembers("admins"):
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
            log.info("LOG: %s", msg)
        elif level == "DEBUG":
            log.debug("LOG: %s", msg)
        if (
            self.log_to_channel and level == "INFO"
        ):  # only log to channel if level is info
            self.driver.create_post(self.log_channel, msg[:4000])

    def slog(self, message: str):
        """sync log"""
        callerclass, callerfunc = self.get_caller_info()
        msg = f"[{callerclass}.{callerfunc}] {message}"
        log.info("LOG: %s", msg)
        if self.log_to_channel:
            self.driver.create_post(self.log_channel, msg[:4000])
    def console(self, message: str):
        """log to console"""
        callerclass, callerfunc = self.get_caller_info()
        message = f"[{callerclass}.{callerfunc}] {message}"
        log.info("CONSOLE: %s", message)
    def console_debug(self, message: str):
        """log to console"""
        callerclass, callerfunc = self.get_caller_info()
        message = f"[{callerclass}.{callerfunc}] {message}"
        log.debug("CONSOLE: %s", message)
    def console_error(self, message: str):
        """log to console"""
        callerclass, callerfunc = self.get_caller_info()
        message = f"[{callerclass}.{callerfunc}] {message}"
        log.error("CONSOLE: %s", message)
    async def debug(self, message: str, private: bool = False):
        """send debug message to log channel. if private is true send to all admins"""
        log.debug("DEBUG: %s", message)
        if self.log_to_channel and not private:
            await self.log(f"DEBUG: {message}", level="DEBUG")

    def add_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by adding a reaction to the thread"""
        self.driver.react_to(message, reaction)

    def remove_reaction(self, message: Message, reaction: str = "thought_balloon"):
        """set the thread to in progress by removing the reaction from the thread"""
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, reaction)

    def urlencode_text(self, text: str) -> str:
        """urlencode the text"""

        return urllib.parse.quote_plus(text)

    def create_tmp_filename(self, extension: str, prefix: str = None) -> str:
        """create a tmp filename"""

        # create a tmp file using tempfile
        if extension.startswith("."):
            extension = extension[1:]
        if prefix is not None:
            return tempfile.mktemp(suffix="." + extension, prefix=prefix)
        return tempfile.mktemp(suffix="." + extension)

    def download_file(self, url: str, filename: str) -> str:
        """download file from url using requests and return the filename/location"""
        request = requests.get(url, allow_redirects=True, timeout=90)
        with open(filename, "wb") as file:
            file.write(request.content)
        return filename

    def download_file_to_tmp(self, url: str, extension: str, prefix: str = None) -> str:
        """download file using requests and return the filename/location"""

        filename = self.create_tmp_filename(extension, prefix=prefix)
        return self.download_file(url, filename)

    def save_content_to_tmp_file(
        self, content, extension: str, prefix: str = None, binary: bool = False
    ) -> str:
        """save content to a tmp file"""
        filename = self.create_tmp_filename(extension, prefix=prefix)
        mode = "wb" if binary else "w"
        # If it's already bytes, write directly
        if isinstance(content, bytes):
            with open(filename, "wb") as file:
                file.write(content)
        # If it's string but binary mode, encode it
        elif binary and isinstance(content, str):
            with open(filename, "wb") as file:
                file.write(content.encode("utf-8"))
        # Otherwise write as text
        else:
            with open(filename, mode, encoding="utf-8") as file:
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

    def validate_input(self, input_val, types=None, allowed_args=None, count=0):
        """function that takes a string and validates that it matches against one or more of the types given in the list"""
        if allowed_args is None:
            allowed_args = []
        if types is None:
            types = ["domain", "ip"]
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
        if types and not isinstance(types, list):
            types = [types]
        if len(types) == 0:
            return {"error": "no arguments allowed"}
        # check if any of the bad chars exist in input
        for char in bad_chars:
            if char in input_val:
                return {"error": f"bad char: {char}"}

        for ctype in types:
            if ctype not in valid_types:
                return {"error": f"invalid type: {ctype}"}
        if "domain" in types:
            if validators.domain(input_val):
                # verify that the ip returned from a dns lookup is not a private ip
                try:
                    answers = dns.resolver.resolve(input_val, "A")
                except dns.resolver.NoAnswer:
                    answers = []
                # pylint: disable=broad-except
                except Exception as error:
                    return {"error": f"error resolving domain: {error}"}
                try:
                    answers6 = dns.resolver.resolve(input_val, "AAAA")
                except dns.resolver.NoAnswer:
                    answers6 = []
                # pylint: disable=broad-except
                except Exception as error:
                    return {"error": f"error resolving domain: {error}"}
                try:
                    answersc = dns.resolver.resolve(input_val, "CNAME")
                except dns.resolver.NoAnswer:
                    answersc = []
                # pylint: disable=broad-except
                except Exception as error:
                    return {"error": f"error resolving domain: {error}"}
                if len(answers) == 0 and len(answers6) == 0 and len(answersc) == 0:
                    return {"error": f"no dns records found for {input_val}"}
                # loop over answers6 and answers and check if any of them are private ips
                for answer in [answersc, answers6, answers]:
                    for rdata in answer:
                        # if CNAME record then validate the cname
                        if answer.rdtype == dns.rdatatype.CNAME:
                            result = self.validate_input(
                                str(rdata.target).rstrip("."), ["domain"], count=count
                            )
                            # check if dict
                            if isinstance(result, dict):
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
            if validators.ipv4(input_val):
                # verify that it is not a private ip
                if ipaddress.ip_address(input_val).is_reserved:
                    return {"error": "reserved ip"}
                if ipaddress.ip_address(input_val).is_multicast:
                    return {"error": "multicast ip"}
                if ipaddress.ip_address(input_val).is_unspecified:
                    return {"error": "unspecified ip"}
                if ipaddress.ip_address(input_val).is_loopback:
                    return {"error": "loopback ip"}
                if ipaddress.ip_address(input_val).is_private:
                    return {"error": "private ip"}
                return True
        if "ipv6" in types or "ip" in types:
            if validators.ipv6(input_val):
                # verify that it is not a private ip
                if ipaddress.ip_address(input_val).is_reserved:
                    return {"error": "reserved ip"}
                if ipaddress.ip_address(input_val).is_multicast:
                    return {"error": "multicast ip"}
                if ipaddress.ip_address(input_val).is_unspecified:
                    return {"error": "unspecified ip"}
                if ipaddress.ip_address(input_val).is_loopback:
                    return {"error": "loopback ip"}
                if ipaddress.ip_address(input_val).is_link_local:
                    return {"error": "link local ip"}
                if ipaddress.ip_address(input_val).is_private:
                    return {"error": "private ip"}
                if ipaddress.ip_address(input_val).sixtofour is not None:
                    # verify the ipv4 address inside the ipv6 address is not private
                    if ipaddress.ip_address(
                        ipaddress.ip_address(input_val).sixtofour
                    ).is_private:
                        return {"error": "private ip (nice try though)"}
                return True
        if "url" in types:
            if validators.url(input_val):
                # fetch the url to verify all urls in the redirect chain
                try:
                    # get domain from url and validate it as a domain so we can check if it is a private ip
                    domain = urllib.parse.urlparse(input_val).netloc
                    if domain == input_val:
                        # no domain found in url
                        return {"error": "no domain found in url (or localhost)"}
                    # call validateinput again with domain
                    result = self.validate_input(
                        domain, ["domain"], count=count)
                    # check if dict
                    if isinstance(result, dict):
                        if "error" in result:
                            return {"error": f"domain: {result['error']}"}
                    response = requests.head(
                        input_val, timeout=10, allow_redirects=True, verify=False
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
                        if isinstance(result, dict):
                            if "error" in result:
                                return {"error": f"redirect: {result['error']}"}
                except requests.exceptions.RequestException as error:
                    return {"error": f"error fetching url: {error}"}
                return True
        if "asn" in types:
            if re.match(r"(AS|as)[0-9]+", input_val):
                return True
        if "string" in types:
            if re.match(r"[a-zA-Z0-9_-]+", input_val):
                return True
        if "port" in types:
            if re.match(r"[0-9]+", input_val):
                if int(input_val) > 65535:
                    return {"error": "port can not be higher than 65535"}
                if int(input_val) < 1:
                    return {"error": "port can not be lower than 1"}
                return True
        if "argument" in types:
            if input_val in allowed_args:
                return True
        return {
            "error": f"invalid input: {input_val} (no matches) for types {', '.join(types)}"
        }

    def get_content_type_and_ext(self, content_type):
        """Find the type and extension of the content using mimetypes and magic"""
        # Get the base content type without parameters
        if ';' in content_type:
            content_type = content_type.split(';', 1)[0].strip()

        # Get the main type and subtype
        main_type = content_type.split('/', 1)[0].lower() if '/' in content_type else 'unknown'

        # Get extension from mimetype
        ext = mimetypes.guess_extension(content_type, strict=False)
        if ext:
            # Remove the leading dot
            ext = ext[1:]
        else:
            ext = 'unknown'

        # Special cases first
        if content_type.lower() == 'text/html':
            return 'html', 'txt'
        if content_type.lower() in ['application/json', 'application/xml']:
            return 'text', ext

        # Map main types to our categories
        type_mapping = {
            'text': 'text',
            'video': 'video',
            'image': 'image',
            'audio': 'audio',
            'application': 'documents'
        }

        return type_mapping.get(main_type, 'unknown'), ext

    async def download_webpage(self, url):
        """download a webpage and return the content"""
        # pylint: disable=attribute-defined-outside-init
        self.exit_after_loop = False
        # await self.log(f"downloading webpage {url}")
        validate_result = self.validate_input(url, "url")
        if validate_result is not True:
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
            return (
                f"Error: content size exceeds the maximum limit ({max_content_size} bytes)",
                None,
            )

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
                return (
                    f"Error: content size exceeds the maximum limit ({max_content_size} bytes)",
                    None,
                )
        response_text = content.decode("utf-8")
        # save response_text to a tmp fil
        blacklisted_tags = ["script", "style", "noscript"]

        try:
            if response.status_code == 200:
                # Detect content type from headers, falling back to magic if needed
                content_type = response.headers.get('content-type', '')
                if not content_type:
                    # Use python-magic to detect content type from the content
                    content_type = magic.from_buffer(content[:1024], mime=True)

                await self.log(f"content type header: {url} {content_type}")
                content_type, ext = self.get_content_type_and_ext(content_type)
                await self.log(f"content_type: {url} {content_type}")
                # html
                if "html" in content_type:
                    # extract all text from the webpage

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
                            text = "Error getting body text from webpage"
                            if soup.body:
                                text = soup.body.get_text(
                                    separator=" ", strip=True)
                            text_full = soup.body.get_text()
                            # trim all newlines to 2 spaces
                            text = text.replace("\n", "  ")

                            # remove all newlines and replace them with spaces
                            # text = text.replace("\n", " ")
                            # remove all double spaces
                            # save the text to a file
                            text_to_return = (
                                f"links:{links}|title:{title}|body:{text}".strip()
                            )
                            text_to_save = f"Url: {url}\nTitle: {title}\nLinks: {links}\nBody:\n{text_full}".strip(
                            )
                            filename = self.save_content_to_tmp_file(
                                text_to_save, ext)
                            return text_to_return, filename
                    # pylint: disable=broad-except
                    except Exception as e:
                        await self.log(
                            f"Error: could not parse webpage (Exception) {e}"
                        )
                        return f"Error: could not parse webpage (Exception) {e}", None
                elif content_type == "text":
                    # save the text to a file
                    filename = self.save_content_to_tmp_file(
                        response_text, ext)
                    # text content
                    return response_text, filename
                else:
                    # unknown content type
                    await self.log(
                        f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text[:500]}"
                    )
                    return (
                        f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text}",
                        None,
                    )
            else:
                await self.log(
                    f"Error: could not download webpage (status code {response.status_code})"
                )
                return (
                    f"Error: could not download webpage (status code {response.status_code})",
                    None,
                )
        except requests.exceptions.Timeout:
            await self.log("Error: could not download webpage (Timeout)")
            return "Error: could not download webpage (Timeout)", None
        except requests.exceptions.TooManyRedirects:
            await self.log("Error: could not download webpage (TooManyRedirects)")
            return "Error: could not download webpage (TooManyRedirects)", None
        except requests.exceptions.RequestException as e:
            await self.log(f"Error: could not download webpage (RequestException) {e}")
            return (
                "Error: could not download webpage (RequestException) " +
                str(e),
                None,
            )
        # pylint: disable=broad-except
        except Exception as e:  # pylint: disable=broad-except
            await self.log(f"Error: could not download webpage (Exception) {e}")
            return "Error: could not download webpage (Exception) " + str(e), None

    async def web_search_and_download(self, searchterm):
        """run the search and download top 2 results from duckduckgo"""
        # pylint: disable=attribute-defined-outside-init
        self.exit_after_loop = False
        downloaded = []
        localfiles = []
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
            # pylint: disable=broad-except
            except Exception as e:
                await self.log(f"Error: {e}")
                content = None
            if content:
                result["content"] = content
                downloaded.append(result)
            else:
                result["content"] = (
                    f"Error: could not download webpage {result.get('href')}"
                )
                downloaded.append(result)
        # await self.log(f"search results: {results}")
        # return the downloaded webpages as json
        return json.dumps(downloaded), localfiles

    async def web_search(self, searchterm):
        """search the web using google and return the results"""
        # pylint: disable=attribute-defined-outside-init
        self.exit_after_loop = False

        await self.log("searching the web")
        try:
            results = googlesearch(searchterm, advanced=True, num_results=50)

            # class SearchResult:
            # def __init__(self, url, title, description):
            #    self.url = url
            #    self.title = title
            #    self.description = description
            # convert results to dict
            results = [
                {"href": result.url, "title": result.title, "description": result.description.strip()} for result in results
            ]
            # filter out any with an url that contains the href https://www.google.com/search
            results = [result for result in results if "google.com/search" not in result.get("href")]
            # save to file
            filename = self.save_content_to_tmp_file(
                json.dumps(results, indent=4), "json"
            )
            return results, filename
        # pylint: disable=broad-exception-caught
        except Exception:
            return "Search failed", None
    def str2bool(self, string: str | None):
        if type(string) == bool:
            return string
        if type(string) == int:
            return bool(string)
        if string is None:
            return False
        if string.lower() == "true" or string.lower() == "t" or string.lower() == "1" or string.lower() == "yes" or string.lower() == "y":
            return True
        return False
