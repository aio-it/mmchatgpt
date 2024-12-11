"""ChatGPT plugin for mmpy_bot"""

import requests
import time
import json
from environs import Env
env = Env()

import openai
from openai import AsyncOpenAI
from re import DOTALL as re_DOTALL

aclient = AsyncOpenAI(api_key=env.str("OPENAI_API_KEY"))
import aiohttp.client_exceptions as aiohttp_client_exceptions

import base64
from .base import PluginLoader

from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from redis_rate_limit import RateLimit, TooManyRequests
from pprint import pformat
# import tools and tools manager
from .tools import ToolsManager, Tool

MODEL = "gpt-4-1106-preview"
REDIS_PREPEND = "thread_"

# Custom Exceptions

# exception for missing api key


class MissingApiKey(Exception):
    """Missing API key exception"""


class ChatGPT(PluginLoader):
    """mmypy chatgpt plugin"""
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
    # MODEL = "gpt-3.5-turbo-0301"
    DEFAULT_MODEL = "gpt-4o"
    ALLOWED_MODELS = [
        "gpt-3.5-turbo-0125",
        "gpt-3.5-turbo",
        "gpt-4",
        "gpt-4o",
        "gpt-4-32k",
        "gpt-4-1106-preview",
        "gpt-4-vision-preview",
        "gpt-4-turbo-preview",
        "gpt-4-vision",
        "gpt-4-turbo",
        "gpt-4-0125-preview",
    ]
    MAX_TOKENS_PER_MODEL = {
        "gpt-3.5-turbo-0301": 3000,
        "gpt-3.5-turbo": 3000,
        "gpt-4": 7000,
        "gpt-4o": 7000,
        "gpt-4-32k": 7000,
        "gpt-4-1106-preview": 7000,
        "gpt-4-vision-preview": 7000,
        "gpt-4-turbo-preview": 7000,
        "gpt-4-vision": 7000,
        "gpt-4-turbo": 7000,
        "gpt-4-0125-preview": 7000,
    }
    ChatGPT_DEFAULTS = {
        "temperature": 1.0,
        "system": """You're a helpful assistant.""",
        "top_p": 1.0,
        "moderation": "false",
        "stream": "true",
        "stream_update_delay_ms": 200,
    }
    SETTINGS_KEY = "chatgpt_settings"

    def __init__(self):
        super().__init__()
        self.name = "ChatGPT"
        self.names = ["chatgpt", "@gpt4", "@gpt3", "@gpt"]
        self.openai_api_key = env.str("OPENAI_API_KEY")

    def initialize(
        self,
        driver: Driver,
        plugin_manager: PluginManager,
        settings: Settings,
    ):
        super().initialize(driver, plugin_manager, settings)
        # Apply default model to redis if not set and set self.model
        self.model = self.redis.hget(self.SETTINGS_KEY, "model")
        if self.model is None:
            self.redis.hset(self.SETTINGS_KEY, "model", self.DEFAULT_MODEL)
            self.model = self.DEFAULT_MODEL
        # Apply defaults to redis if not set
        for key, value in self.ChatGPT_DEFAULTS.items():
            if self.redis.hget(self.SETTINGS_KEY, key) is None:
                self.redis.hset(self.SETTINGS_KEY, key, value)
        # emulate a browser and set all the relevant headers
        self.headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.7,da;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        self.openai_errors = (
            openai.APIError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.APIStatusError,
            openai.InternalServerError,
            openai.NotFoundError,
            openai.APIResponseValidationError,
            openai.AuthenticationError,
            openai.BadRequestError,
            openai.ConflictError,
            openai.LengthFinishReasonError
        )
        self.update_allowed_models()
        print(f"Allowed models: {self.ALLOWED_MODELS}")
        # TODO: add ignore function for specific channels like town-square that is global for all users
        # chatgpt "function calling" so we define the tools here.
        # TODO: add more functions e.g. code_runnner, openai vision, dall-e3, etc
        #       define this elsewhere. we don't want to define this in the chat function
        # configure tools
        download_webpage_tool = Tool(
            name=self.download_webpage,
            description="Download and extract content from a specific webpage URL. Use this when the user provides a direct URL or when you need to fetch content from a known webpage.",
            parameters=[{"name": "url", "description": "URL of the webpage to download"}],
            privilege_level="user"
        )

        web_search_and_download_tool = Tool(
            name=self.web_search_and_download,
            description="Search the web AND download content from the best matching webpage. Use this when you need detailed information about a topic and want to provide accurate quotes and sources. IMPORTANT: Only use this when you need in-depth information, not for quick facts or simple searches.",
            parameters=["searchterm"],
            privilege_level="user"
        )

        web_search_tool = Tool(
            name=self.web_search,
            description="Quick web search that returns only titles and snippets of the top 10 results. Use this for general information, fact-checking, or when you need a broad overview of a topic. Does NOT download full webpage content.",
            parameters=["searchterm"],
            privilege_level="user"
        )
        generate_image_tool = Tool(
            name=self.generate_image,
            description="Generate an image from a text prompt using DALL-E-3. Use this to create visual representations of your ideas or to illustrate concepts. DO NOT CHANGE THE PROMPT from the user. The function returns an revised prompt that was used to generate the image. The assistant will not get to see the image but it will be returned by the program afterwards. so don't mistake the missing image as it not being generated. the only reason for it not being generated is if the revised prompt contains 'Error:' if it returns the revised prompt print it for the user as revised prompt: \{revised_prompt\}",
            parameters=[
                {"name": "prompt", "description": "The prompt to generate the image from. DO NOT CHANGE THE PROMPT from the user. maximum length is 4000 characters", "required": True},
                {"name": "size", "description": "the size of the image to generate. default is 1024x1024. Must be one of 1024x1024, 1792x1024, or 1024x1792, allow for the user to say landscape or portrait or sqaure and return the correct size accordingly as the value", "required": False},
                {"name": "style", "description": "the style of the image to generate. default is vivid. Must be one of vivid or natural", "required": False},
                {"name": "quality", "description": "the quality of the image to generate. default is hd. Must be one of hd or standard", "required": False},
            ],
            privilege_level="user"
        )
        assistant_to_the_regional_manager_tool = Tool(
            name=self.assistant_to_the_regional_manager,
            description="You can use this function to ask the assistant to solve something for you. The assistant will try to solve the problem and return the solution to you. The assistant will not be able to solve all problems but it will try its best to solve the problem. If the assistant is unable to solve the problem it will return an error message. only send what what context you feel absolutely necessary for the assistant to solve the problem.",
            parameters=["prompt","context"],
            privilege_level="user"
        )
        self.tools_manager = ToolsManager()
        self.tools_manager.add_tool(download_webpage_tool)
        self.tools_manager.add_tool(web_search_and_download_tool)
        self.tools_manager.add_tool(web_search_tool)
        self.tools_manager.add_tool(generate_image_tool)
        #manager.add_tool(assistant_to_the_regional_manager_tool)
        self.user_tools = self.tools_manager.get_tools("user")
        self.admin_tools = self.tools_manager.get_tools("admin")
        self.helper.slog(f"User tools: {self.user_tools}")
        self.helper.slog(f"Admin tools: {self.admin_tools}")

    def update_allowed_models(self):
        """update allowed models"""
        response = openai.models.list()
        available_models = []
        models_msg = "Available Models:\n"
        for model in response.data:
            available_models.append(model)
        if len(available_models) > 0:
            self.ALLOWED_MODELS = [model.id for model in available_models]
        else:
            available_models = self.ALLOWED_MODELS
            self.helper.slog(f"Could not update allowed models. Using default models: {available_models}")
        # sort the models on the created key
        available_models.sort(key=lambda x: x.created, reverse=True)
        for model in available_models:
            # convert unix to human readable date
            model.created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(model.created))
            models_msg += f"- {model.id}\n ({model.created})\n"
        self.helper.slog(models_msg)
        return available_models

    def return_last_x_messages(self, messages, max_length_in_tokens = 7000):
        """return last x messages from list of messages limited by max_length_in_tokens"""
        # fuck this bs
        return messages

    @listen_to(r"^\.gpt model available")
    async def get_available_models(self, message: Message):
        """get available models"""
        available_models = self.update_allowed_models()
        models_msg = "Available Models:\n"
        for model in available_models:
            models_msg += f"- {model.id} ({model.created})\n"        
        self.driver.reply_to(message, models_msg)

    @listen_to(r"^\.gpt model set ([a-zA-Z0-9_-]+)")
    async def model_set(self, message: Message, model: str):
        """set the model"""
        if self.users.is_admin(message.sender_name):
            if model in self.ALLOWED_MODELS:
                self.redis.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Set model to {model}")
            else:
                self.driver.reply_to(
                    message, f"Model not allowed. Allowed models: {self.ALLOWED_MODELS}"
                )

    @listen_to(r"^\.gpt model get")
    async def model_get(self, message: Message):
        """get the model"""
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {self.model}")

    @listen_to(r"^\.(?:mk)?i[mn]g ([\s\S]*)")
    async def mkimg_deprecated_just_ask(self, message: Message, args: str):
        """send a message to the user that this is deprecated and they should just ask for an image instead"""
        self.driver.reply_to(message, "This function is deprecated. i have asked my assistant to generate an image for you. Please ask for an image instead next time without the .mkimg command.")
        message.text = "this user asked for an image and described it as follows: " + args
        await self.chat(message)

    async def generate_image(self, prompt, size=None, style=None, quality=None):
        """use the openai module to get an image from a prompt"""
        self.helper.slog(f"generate_image: {prompt}")
        # validate size
        if size not in ["1024x1024", "1792x1024", "1024x1792"]:
            size = "1024x1024"
        # validate style
        if style not in ["vivid", "natural"]:
            style = "vivid"
        # validate quality
        if quality not in ["hd", "standard"]:
            quality = "hd"
        try:
            response = await aclient.images.generate(
                prompt=prompt,
                n=1,
                size=size,
                model="dall-e-3",
                style=style,
                response_format="url",
                quality=quality,
            )
            image_url = response.data[0].url
            self.helper.slog(f"image_url: {image_url}")
            revised_prompt = response.data[0].revised_prompt
            self.helper.slog(f"revised_prompt: {revised_prompt}")
            filename = self.helper.download_file_to_tmp(image_url, "png")
            self.helper.slog(f"filename: {filename}")
            return f"revised prompt: {revised_prompt}", filename
        except Exception as e:
            self.helper.slog(f"Error: {e}")
            return f"Error: {e}", None
    @listen_to(r"^\.gpt set ([a-zA-Z0-9_-]+) (.*)")
    async def set_chatgpt(self, message: Message, key: str, value: str):
        """set the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"set_chatgpt {key} {value}")
        if self.users.is_admin(message.sender_name):
            self.redis.hset(settings_key, key, value)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.gpt reset ([a-zA-Z0-9_-]+)")
    async def reset_chatgpt(self, message: Message, key: str):
        """reset the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        if self.users.is_admin(message.sender_name) and key in self.ChatGPT_DEFAULTS:
            value = self.ChatGPT_DEFAULTS[key]
            await self.helper.debug(f"reset_chatgpt {key} {value}")
            self.redis.hset(settings_key, key, self.ChatGPT_DEFAULTS[key])
            self.redis.hdel(settings_key, key)
            self.driver.reply_to(message, f"Reset {key} to {value}")

    @listen_to(r"^\.gpt get ([a-zA-Z0-9_-])")
    async def get_chatgpt(self, message: Message, key: str):
        """get the chatgpt key"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug(f"get_chatgpt {key}")
        if self.users.is_admin(message.sender_name):
            value = self.redis.hget(settings_key, key)
            self.driver.reply_to(message, f"Set {key} to {value}")

    @listen_to(r"^\.gpt get")
    async def get_chatgpt_all(self, message: Message):
        """get all the chatgpt keys"""
        settings_key = self.SETTINGS_KEY
        await self.helper.debug("get_chatgpt_all")
        if self.users.is_admin(message.sender_name):
            for key in self.redis.hkeys(settings_key):
                if key in self.ChatGPT_DEFAULTS:
                    self.driver.reply_to(
                        message, f"{key}: {self.redis.hget(settings_key, key)}"
                    )
                else:
                    # key not in defaults, delete it. unsupported key
                    self.redis.hdel(settings_key, key)

    def get_chatgpt_setting(self, key: str):
        """get the chatgpt key setting"""
        settings_key = self.SETTINGS_KEY
        value = self.redis.hget(settings_key, key)
        if value is None and key in self.ChatGPT_DEFAULTS:
            value = self.ChatGPT_DEFAULTS[key]
        return value
    def extract_file_details(self, message: Message):
        """Extract file details from a post and return a list of objects with their filename, type, and content."""
        data = message.body["data"]
        post = data["post"]
        files = []

        # Check if message contains files and metadata
        if "file_ids" in post and "metadata" in post:
            file_ids = post["file_ids"]
            files_metadata = post["metadata"]["files"]
            self.helper.slog(f"files_metadata: {files_metadata}")
            self.helper.slog(f"file_ids: {file_ids}")
            import magic
            for i, metadata in enumerate(files_metadata):
                # Get file extension and name
                self.helper.slog(f"i: {i}")
                self.helper.slog(f"metadata: {metadata}")
                extension = metadata.get("extension")
                filename = metadata.get("name", f"file_{i}.{extension}")
                self.helper.slog(f"filename: {filename}. extension: {extension}")
                # Get the file content
                get_file_response = self.driver.files.get_file(file_ids[i])
                if get_file_response.status_code != 200:
                    continue

                file_content = get_file_response.content
                extension_types = {
                    "image": ["png", "jpg", "jpeg"],
                    "text": ["txt"],
                    "pdf": ["pdf"],
                    "doc": ["doc", "docx"],
                    "xls": ["xls", "xlsx"],
                    "ppt": ["ppt", "pptx"],
                    "audio": ["mp3", "wav", "ogg"],
                    "video": ["mp4", "webm", "ogg"],
                    "archive": ["zip", "rar", "tar", "7z"],
                    "code": ["py", "js", "html", "css", "java", "c", "cpp", "h", "hpp", "cs", "php", "rb", "sh"],
                }
                mime = magic.Magic(mime=True)
                mime_type = mime.from_buffer(file_content)
                self.helper.slog(f"mime_type: {mime_type}")

                # Determine file type and content format
                if extension in extension_types["image"]:
                    # Encode image content to base64
                    content_base64 = base64.b64encode(file_content).decode("utf-8")
                    files.append({
                        "filename": filename,
                        "type": "image",
                        "content": content_base64
                    })
                elif extension in extension_types["text"] or extension in extension_types["code"]:
                    # Decode text content
                    # find the encoding
                    encoding = metadata.get("encoding")
                    text_content = file_content.decode(encoding) if encoding else file_content.decode("utf-8")
                    files.append({
                        "filename": filename,
                        "type": "text",
                        "content": text_content
                    })
                elif extension in extension_types["audio"]:
                    # Encode audio content to base64
                    content_base64 = base64.b64encode(file_content).decode("utf-8")
                    files.append({
                        "filename": filename,
                        "type": "audio",
                        "content": content_base64
                    })
                elif extension in extension_types["video"]:
                    # Encode video content to base64
                    content_base64 = base64.b64encode(file_content).decode("utf-8")
                    files.append({
                        "filename": filename,
                        "type": "video",
                        "content": content_base64
                    })               
                else:
                    # Other unsupported file types can be ignored or handled differently
                    continue

        return files

    async def web_search_and_download(self, searchterm):
        """run the search and download top 2 results from duckduckgo"""
        self.exit_after_loop = False
        downloaded=[]
        localfiles=[]
        await self.helper.log(f"searching the web for {searchterm}")
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
            #await self.helper.log(f"downloading webpage {result}")
            try:
                # download the webpage and add the content to the result object
                if "href" not in result:
                    return "Error: href not in result", None
                content, localfile = await self.download_webpage(result.get("href"))
                if localfile:
                    localfiles.append(localfile)
                #await self.helper.log(f"webpage content: {content[:500]}")
                i = i + 1
            except Exception as e:
                await self.helper.log(f"Error: {e}")
                content = None
            if content:
                result["content"] = content
                downloaded.append(result)
            else:
                result["content"] = f"Error: could not download webpage {result.get('href')}"
                downloaded.append(result)
        #await self.helper.log(f"search results: {results}")
        # return the downloaded webpages as json
        return json.dumps(downloaded), localfiles

    async def web_search(self, searchterm):
        """search the web using duckduckgo"""
        self.exit_after_loop = False
        await self.helper.log(f"searching the web using backend=api")
        from duckduckgo_search import DDGS
        try:
            results = DDGS().text(keywords=searchterm, backend="api", max_results=10)
            # save to file
            filename = self.helper.save_content_to_tmp_file(json.dumps(results, indent=4), "json")
            return results, filename
        except Exception as e:
            await self.helper.log(f"Error: falling back to html backend")
        await self.helper.log(f"searching the web using backend=html")
        try:
            from duckduckgo_search import DDGS
            results = DDGS().text(keywords=searchterm, backend="html", max_results=10)
            # save to file
            filename = self.helper.save_content_to_tmp_file(json.dumps(results, indent=4), "json")
            return results, filename
        except Exception as e:
            await self.helper.log(f"Error: {e}")
            return f"Error: {e}", None

    async def download_webpage(self, url):
        """download a webpage and return the content"""
        self.exit_after_loop = False
        await self.helper.log(f"downloading webpage {url}")
        validate_result = self.helper.validate_input(url, "url")
        if validate_result != True:
            await self.helper.log(f"Error: {validate_result}")
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
            await self.helper.log(
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
                await self.helper.log(
                    f"Error: content size exceeds the maximum limit ({max_content_size} bytes)"
                )
                return f"Error: content size exceeds the maximum limit ({max_content_size} bytes)", None
        # decode the content
        # check the encoding type so we can decode if it is compressed
        #encoding = response.headers.get("Content-Encoding")
        #if encoding == "gzip":
        #    import gzip
        #    response_text = gzip.decompress(content).decode("utf-8")
        #elif encoding == "deflate":
        #    import zlib
        #    response_text = zlib.decompress(content).decode("utf-8")
        #elif encoding == "br":
        #    import brotli
        #    response_text = brotli.decompress(content).decode("utf-8")
        #else:
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
        # await self.helper.debug(f"response: {pformat(response.text[:500])}")
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
                # await self.helper.log(f"content_type: {url} {content_type}")
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
                            filename = self.helper.save_content_to_tmp_file(text_to_save, ext)
                            return text_to_return, filename

                    except Exception as e:  # pylint: disable=bare-except
                        await self.helper.log(
                            f"Error: could not parse webpage (Exception) {e}"
                        )
                        return f"Error: could not parse webpage (Exception) {e}", None
                elif content_type == "text":
                    # save the text to a file
                    filename = self.helper.save_content_to_tmp_file(response_text, ext)
                    # text content
                    return response_text, filename
                else:
                    # unknown content type
                    await self.helper.log(
                        f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text[:500]}"
                    )
                    return f"Error: unknown content type {content_type} for {url} (status code {response.status_code}) returned: {response_text}", None
            else:
                await self.helper.log(
                    f"Error: could not download webpage (status code {response.status_code})"
                )
                return f"Error: could not download webpage (status code {response.status_code})", None
        except requests.exceptions.Timeout:
            await self.helper.log("Error: could not download webpage (Timeout)")
            return "Error: could not download webpage (Timeout)", None
        except requests.exceptions.TooManyRedirects:
            await self.helper.log(
                "Error: could not download webpage (TooManyRedirects)"
            )
            return "Error: could not download webpage (TooManyRedirects)", None
        except requests.exceptions.RequestException as e:
            await self.helper.log(
                f"Error: could not download webpage (RequestException) {e}"
            )
            return "Error: could not download webpage (RequestException) " + str(e), None
        except Exception as e: # pylint: disable=bare-except
            await self.helper.log(f"Error: could not download webpage (Exception) {e}")
            return "Error: could not download webpage (Exception) " + str(e), None

    def thread_append(self, thread_id, message) -> None:
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.helper.redis_serialize_json(message))

    def get_thread_messages(self, thread_id: str, force_fetch: bool = False):
        """get the message thread from the thread_id"""
        messages = []
        thread_key = REDIS_PREPEND + thread_id
        if not force_fetch and self.redis.exists(thread_key):
            # the thread exists in redis and we are running a tool.
            messages = self.get_thread_messages_from_redis(thread_id)
        else:
            # thread does not exist, fetch all posts in thread
            thread = self.driver.get_post_thread(thread_id)
            i = 0
            thread_post_count = len(thread["posts"])
            for thread_index in thread["order"]:
                i += 1
                #skip the last post
                if i == thread_post_count:
                    continue
                thread_post = thread["posts"][thread_index]
                # turn the thread post into a Message object
                thread_post = Message.create_message(thread_post)

                # remove mentions of self
                thread_post.text = self.helper.strip_self_username(thread_post.text)
                # remove mentions of self from self.names
                for name in self.names:
                    thread_post.text = thread_post.text.replace(f"{name} ", "")
                    thread_post.text = thread_post.text.replace(f"{name}", "")

                # if post is from self, set role to assistant
                if thread_post.is_from_self(self.driver):
                    role = "assistant"
                else:
                    # post is from user, set role to user
                    role = "user"
                # create message object and append it to messages and redis
                message = {"role": role, "content": thread_post.text}
                messages.append(message)
                self.thread_append(thread_id, message)
        #messages = self.get_formatted_messages(messages)
        return messages
    def get_formatted_messages(self,messages):
        current_tool_call = None
        formatted_messages = []
        return messages
        self.helper.slog(f"messages: {messages}")
        for msg in messages:
            if isinstance(msg, dict):
                # Handle tool calls
                if 'tool_calls' in msg:
                    current_tool_call = msg
                    formatted_messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": msg['tool_calls']
                    })
                # Handle tool responses
                elif msg.get('role') == 'tool':
                    if current_tool_call:
                        formatted_messages.append({
                            "role": "tool",
                            "content": msg.get('content', ''),
                            "tool_call_id": msg.get('tool_call_id'),
                            "name": msg.get('name')
                        })
                # Handle regular messages
                elif 'role' in msg and 'content' in msg:
                    formatted_messages.append(msg)
                elif 'content' in msg:
                    formatted_messages.append({
                        "role": "user",
                        "content": msg['content']
                    })
            elif isinstance(msg, str):
                formatted_messages.append({
                    "role": "user",
                    "content": msg
                })
            self.helper.slog(f"formatted_messages: {formatted_messages}")
            return formatted_messages
    async def assistant_to_the_regional_manager(self,prompt,context=None, model=None):
        """a tool function that chatgpt can call as a tool with whatever context it deems necessary"""
        # check if model is set
        if model is None:
            model = self.DEFAULT_MODEL
        # check if context is set
        if context:
            prompt = f"context: {context}\nprompt: {prompt}"
        # call the assistant to the regional manager
        messages = [
            {"role": "system", "content": "you're an agent running for your superior model. your task is to follow it's instructions and return what is asked of you. You are not talking with a human but with another ai"},
            {"role": "user", "content": prompt}
        ]
        try:
            request_object = {
                "model": model,
                "messages": messages,
            }
            completions = await aclient.chat.completions.create(**request_object)
            return completions.choices[0].message.content
        except self.openai_errors as error:
            # update the message
            self.helper.slog(f"Error: {error}")
            return f"Error: {error}"

    # function that debugs a chat thread
    @listen_to(r"^\.gpt debugchat")
    async def debug_chat_thread(self, message: Message):
        """debug a chat thread"""
        # check if user is admin
        if not self.users.is_admin(message.sender_name):
            return
        # set to root_id if set else use reply_id
        thread_id = message.root_id if message.root_id else message.reply_id
        # thread_key = REDIS_PREPEND + thread_id
        messages = self.get_thread_messages_from_redis(thread_id)
        # save messages to a file.
        filename = self.helper.save_content_to_tmp_file(json.dumps(messages, indent=4), "json")
        self.driver.reply_to(message, f"debugging thread {thread_id}", file_paths=[filename])
        self.helper.delete_downloaded_file(filename)

    # soon to be deprecated
    # @listen_to(".+", needs_mention=True)
    # async def chat_moved(self, message: Message):
    #    """listen to everything and respond when mentioned"""
    #    # reply to the message with the new callsign @gpt
    #    self.driver.reply_to(
    #        message, f"#NOTICE\nchanged trigger from @{self.driver.username} to @gpt"
    #    )
    #    await self.chat(message)
    async def chat(self, message: Message, model: str = None):
        """listen to everything and respond when mentioned"""
        # set some variables
        max_message_length = 14000
        files = []
        if model is None:
            model = self.model
        stream = True  # disabled the non-streaming mode for simplicity
        # this is to check if the message is from a tool or not
        tool_run = False
        if hasattr(message, "tool_run") and message.tool_run == True:
            tool_run = True
            msg = ""
        else:
            msg = message.text
        # if message is not from a user, ignore
        if not self.users.is_user(message.sender_name):
            return

        # check if the user is and admin and set tools accordingly
        if self.users.is_admin(message.sender_name):
            self.tools = self.admin_tools
        else:
            self.tools = self.user_tools

        # message text exceptions. bail if message starts with any of these
        skips = [".", "!", "ollama", "@claude", "@opus", "@sonnet"]
        for skip in skips:
            if message.text.lower().startswith(skip):
                return

        # This function checks if the thread exists in redis and if not, fetches all posts in the thread and adds them to redis
        thread_id = message.reply_id
        # keep a log of all status messages ( for tools )
        status_msgs = []
        messages = []
        messages = self.get_thread_messages(thread_id)
        if True or not tool_run and len(messages) != 1:
            # we don't need to append if length = 1 because then it is already fetched via the mattermost api so we don't need to append it to the thread
            # append message to threads
            user_text = message.text
            message_files = self.extract_file_details(message)
            # log the type and filename of the files
            for file in message_files:
                await self.helper.log(f"file: {file.get('filename')} type: {file.get('type')}")
            m = {"role": "user"}
            if message_files:
                # we have files lets add them to the message to be sent to the model
                txt_files = [file for file in message_files if file["type"] == "text"]
                img_files = [file for file in message_files if file["type"] == "image"]
                for file in img_files:
                    await self.helper.log(f"img file: {file}")
                    m = {"role": "user"}
                    # if the file is an image, add it to the message
                    m["content"] = [
                        { "type": "text", "text": user_text },
                        {
                            "type": "image_url",
                            "image_url": { "url": f"data:image/jpeg;base64,{file['content']}"}
                        }
                    ]
                    messages.append(m)
                    self.thread_append(thread_id, m)
                context_from_text_files = ""
                for file in txt_files:
                    context_from_text_files += file["filename"] + ": " + file["content"] + "\n"
                if context_from_text_files:
                    m["content"] = user_text + "\n" + context_from_text_files
                    messages.append(m)
                    self.thread_append(thread_id, m)
            else:
                m["content"] = user_text
                # append to messages and redis
                messages.append(m)
                self.thread_append(thread_id, m)

        # add system message
        current_date = time.strftime("%Y-%m-%d %H:%M:%S")
        date_template_string = "<date>"
        # model o1-preview does not support system messages
        if not model.startswith("o1"):
            if self.get_chatgpt_setting("system") != "":
                system_message = self.get_chatgpt_setting("system")
            else:
                system_message = f"You're a helpful assistant. Current Date: {date_template_string}"
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": system_message.replace(date_template_string, current_date),
                },
            )
        
        # add thought balloon to show assistant is thinking
        self.driver.react_to(message, "thought_balloon")
        # set the full message to empty string so we can append to it later
        full_message = ""
        # post_prefix is so we can add the sender name to the message to prevent confusion as to who the reply is to
        post_prefix = f"({model}) @{message.sender_name}: "

        # if we are running a tool, we need to reply to the original message and not create a new message.
        # if we are not running a tool, we need to create a new message
        if not tool_run:
            reply_msg_id = self.driver.reply_to(message, full_message)["id"]
        else:
            reply_msg_id = message.reply_msg_id

        # fetch the previous messages in the thread
        messages = self.return_last_x_messages(messages)
        temperature = float(self.get_chatgpt_setting("temperature"))
        top_p = float(self.get_chatgpt_setting("top_p"))

        try:
            request_object = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "top_p": top_p,
                "stream": stream,
            }
            if not model.startswith("o1"):
                # we are not using o1 so add the tools to the request object
                request_object["tools"] = self.tools
                request_object["tool_choice"] = "auto"
            response = await aclient.chat.completions.create(**request_object)
        except self.openai_errors as error:
            # update the message
            self.driver.posts.patch_post(reply_msg_id, {"message": f"Error: {error}"})
            self.driver.reactions.delete_reaction(
                self.driver.user_id, message.id, "thought_balloon"
            )
            self.driver.react_to(message, "x")
            return

        # get current time and set that as last_update_time
        last_update_time = time.time()
        # get the setting for how often to update the message
        stream_update_delay_ms = float(self.get_chatgpt_setting("stream_update_delay_ms"))
        i = 0
        try:
            functions_to_call = {}
            async for chunk in response:
                if "error" in chunk:
                    if "message" in chunk:
                        self.driver.reply_to(message, f"Error: {response['message']}")
                    else:
                        self.driver.reply_to(message, "Error")
                    # remove thought balloon
                    self.driver.reactions.delete_reaction(
                        self.driver.user_id, message.id, "thought_balloon"
                    )
                    # add x reaction to the message that failed to show error
                    self.driver.react_to(message, "x")
                    return

                chunk_message = chunk.choices[0].delta
                await self.helper.debug(chunk)

                if chunk_message.content:
                    full_message += chunk_message.content
                    # if full message begins with ``` or any other mattermost markdown append a \
                    # newline to the post_prefix so it renders correctly
                    markdown = [">", "*", "_", "-", "+", "1", "~", "!", "`", "|", "#", "@", "•"]
                    if i == 0 and post_prefix[-1] != "\n" and full_message[0] in markdown:
                        post_prefix += "\n"
                        i += 1

                    if (time.time() - last_update_time) * 1000 > stream_update_delay_ms:
                        self.driver.posts.patch_post(
                            reply_msg_id,
                            {"message": f"{post_prefix}{full_message}"},
                        )
                        last_update_time = time.time()

                if chunk_message.tool_calls and chunk_message.content is None:
                    index = 0
                    for tool_call in chunk_message.tool_calls:
                        if tool_call.index is not None:
                            index = tool_call.index
                        if tool_call.function.name is not None:
                            function_name = tool_call.function.name
                        if index not in functions_to_call.keys():
                            functions_to_call[index] = {
                                "tool_call_id": "",
                                "arguments": "",
                            }
                            if function_name is not None:
                                functions_to_call[index]["function_name"] = function_name
                            if tool_call.id:
                                functions_to_call[index]["tool_call_id"] = tool_call.id
                            functions_to_call[index]["tool_call_message"] = self.custom_serializer(chunk_message)

                        functions_to_call[index]["arguments"] += tool_call.function.arguments

            # Process all tool calls and collect results
            if functions_to_call:

                def update_status(status_msg):
                    status_msgs.append(status_msg)
                    # update the thread with the status messages so the user can see the progress
                    self.driver.posts.patch_post(
                        reply_msg_id,
                        {"message": "```\n" + '\n'.join(status_msgs) + "\n```\n"},
                    )
                call_key = f"{REDIS_PREPEND}_call_{thread_id}"
                tool_results = []

                for index, tool_function in functions_to_call.items():
                    if self.redis.hexists(call_key, tool_function["tool_call_id"]):
                        continue
                    function_name = tool_function["function_name"]
                    tool_call_id = tool_function["tool_call_id"]
                    self.helper.slog(f"function_name: {function_name}")
                    # get function name from the tool manager
                    tool = self.tools_manager.get_tool(function_name)
                    if tool:
                        try:
                            function = getattr(self, function_name)
                        except AttributeError:
                            await self.helper.log(f"Error: function not found: {function_name}")
                            continue
                    else:
                        await self.helper.log(f"Error: function not found: {function_name}")
                        continue
                    # format the arguments as a pretty string for the status msg it is an dict with a arg and value pair
                    # format it as key: value
                    status_args = json.loads(tool_function["arguments"])
                    status_args = " | ".join([f"{k}:{v}" for k, v in status_args.items()])
                    status_msg = f"Running tool: {function_name}: {status_args}"
                    update_status(status_msg)

                    try:
                        arguments = json.loads(tool_function["arguments"])
                    except json.JSONDecodeError as e:
                        await self.helper.log(f"Error parsing arguments: {tool_function['arguments']}")
                        arguments = {}

                    # Execute the function
                    function_result, filename = await function(**arguments)
                    if isinstance(filename, list):
                        for file in filename:
                            files.append(file)
                    if isinstance(filename, str):
                        files.append(filename)

                    if function_result is None:
                        function_result = "Error: function returned None"
                        update_status(f"Error: {function_result}")
                    elif not isinstance(function_result, str):
                        try:
                            function_result = json.dumps(function_result)
                        except json.JSONDecodeError:
                            function_result = "Error: could not serialize function result"
                            update_status(f"Error: {function_result}")

                    function_result = function_result[:20000]

                    # Store tool result
                    tool_result = {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_result,
                    }
                    tool_results.append(tool_result)
                    # append role to tool_function tool call message
                    tool_function["tool_call_message"]["role"] = "assistant"
                    # Update thread with tool call and result
                    #await self.helper.log(f"tool_result: {tool_function['tool_call_message']}")
                    self.append_thread_and_get_messages(thread_id, tool_function["tool_call_message"])
                    self.append_thread_and_get_messages(thread_id, tool_result)
                    self.redis.hset(call_key, tool_call_id, "true")

                    status_msg = f"Completed: {function_name}"
                    update_status(status_msg)

                # Make final call with all results
                if tool_results:
                    messages = self.get_thread_messages(thread_id)
                    # Ensure all messages have the required 'role' field and proper tool call structure
                    formatted_messages = self.get_formatted_messages(messages)

                    # insert system if needed:
                    if not model.startswith("o1"):
                        formatted_messages.insert(0,{
                            "role": "system",
                            "content": system_message.replace(date_template_string, current_date),
                        })

                    try:
                        # Debug log to see the formatted messages
                        #await self.helper.log(f"Formatted messages: {json.dumps(formatted_messages, indent=2)}")
                        
                        final_response = await aclient.chat.completions.create(
                            model=model,
                            messages=formatted_messages,
                            temperature=temperature,
                            top_p=top_p,
                            stream=stream
                        )

                        full_message = ""
                        status_str = ""
                        if status_msgs:
                            status_str = "```" + "\n".join(status_msgs) + "\n```\n"
                        have_notified_user_about_long_message = False
                        async for chunk in final_response:
                            if chunk.choices[0].delta.content:
                                full_message += chunk.choices[0].delta.content
                                message_length = len(full_message)
                                if message_length < max_message_length:
                                    if (time.time() - last_update_time) * 1000 > stream_update_delay_ms:
                                        self.driver.posts.patch_post(
                                            reply_msg_id,
                                            {"message": f"{status_str}{post_prefix}{full_message[:max_message_length]}"},
                                        )
                                        last_update_time = time.time()
                                else:
                                    # message to long so save the message to a file and add to files
                                    if not have_notified_user_about_long_message:
                                        self.driver.posts.patch_post(
                                            reply_msg_id,
                                            {"message": f"{status_str}{post_prefix}{full_message[:13000]}\n\n# Warning Message too long, i'll attach a file with the full response when done receiving it."},
                                        )
                                        have_notified_user_about_long_message = True
                        # Store final response
                        if full_message:
                            self.thread_append(thread_id, {"role": "assistant", "content": full_message})

                    except Exception as e:
                        # if "Invalid Message." the message is to long so trim the message and save the full result to a files and add to files
                        if "Invalid Message." in str(e):
                            filename = self.helper.save_content_to_tmp_file(full_message, "txt")
                            files.append(filename)
                            self.driver.posts.patch_post(
                                reply_msg_id,
                                {"message": f"{post_prefix}{full_message[:14000]}\nMessage too long, see attached file"},
                            )
                            self.driver.reply_to(message, f"Files: {files}", file_paths=files)
                            for file in files:
                                self.helper.delete_downloaded_file(file)
                            await self.helper.log(f"Error in final response: {e}")
                            await self.helper.log(f"Last formatted messages: {json.dumps(formatted_messages[-3:], indent=2)}")
                            return
                        await self.helper.log(f"Error in final response: {e}")
                        await self.helper.log(f"Last formatted messages: {json.dumps(formatted_messages[-3:], indent=2)}")
                        self.driver.posts.patch_post(
                            reply_msg_id,
                            {"message": f"{post_prefix}Error processing tool results: {str(e)}"}
                        )
                        return
            elif full_message:  # No tools were called, store the regular response
                self.thread_append(thread_id, {"role": "assistant", "content": full_message})

            # Final message update
            # if status_msgs are set then update the message with the status messages prepended to the final message
            status_str = ""
            if status_msgs:
                status_str = "```\n"+ "\n".join(status_msgs) + "\n```\n"
            final_message = f"{status_str}{post_prefix}{full_message}"
            if len(final_message) > max_message_length:
                # save the full message to a file and add to files
                filename = self.helper.save_content_to_tmp_file(final_message, "txt")
                files.append(filename)
                final_message = final_message[:max_message_length] + "\nMessage too long, see attached file"
            self.driver.posts.patch_post(
                reply_msg_id,
                {"message": final_message [:max_message_length]},
            )
            if files and len(files) > 0:
                self.driver.reply_to(message, f"Files:", file_paths=files)
                for file in files:
                    self.helper.delete_downloaded_file(file)

        except aiohttp_client_exceptions.ClientPayloadError as error:
            self.driver.reply_to(message, f"Error: {error}")
            self.driver.reactions.delete_reaction(
                self.driver.user_id, message.id, "thought_balloon"
            )
            self.driver.react_to(message, "x")
            return

        # remove thought balloon after successful response
        self.driver.reactions.delete_reaction(
            self.driver.user_id, message.id, "thought_balloon"
        )

        await self.helper.log(f"User: {message.sender_name} used {model}")

    @listen_to(r"^@o1[ \n]+.+", regexp_flag=re_DOTALL)
    async def chat_o1(self, message: Message):
        """listen to everything and respond when mentioned"""
        await self.helper.log(f"User: {message.sender_name} used o1 keyword")
        await self.chat(message, model="o1-preview")

    @listen_to(r"^@o1mini[ \n]+.+", regexp_flag=re_DOTALL)
    async def chat_o1_mini(self, message: Message):
        """listen to everything and respond when mentioned"""
        await self.helper.log(f"User: {message.sender_name} used o1 keyword")
        await self.chat(message, model="o1-mini")

    @listen_to(r"^@gpt3[ \n]+.+", regexp_flag=re_DOTALL)
    async def chat_gpt3(self, message: Message):
        """listen to everything and respond when mentioned"""
        await self.helper.log(f"User: {message.sender_name} used gpt3 keyword")
        await self.chat(message, model="gpt-3.5-turbo")

    @listen_to(r"^@gpt4{0,1}[ \n]+.+", regexp_flag=re_DOTALL)
    async def chat_gpt4(self, message: Message):
        """listen to everything and respond when mentioned"""
        if "4" not in self.model:
            await self.chat(message, "gpt-4o")
        else:
            await self.chat(message)

    @listen_to(r".+", needs_mention=True)
    async def chat_gpt4_mention(self, message: Message):
        """listen to everything and respond when mentioned"""
        # if direct and starting with names bail
        if message.is_direct_message and message.text.startswith("@"):
            await self.helper.log(f"ignoring private message starting with @ from function chat_gpt4_mention")
            return
        for name in self.names:
            if message.text.startswith(name):
                return
        await self.chat(message)

    def serialize_choice_delta(self, choice_delta):
        # This function will create a JSON-serializable representation of ChoiceDelta and its nested objects.
        tool_calls = []
        for tool_call in choice_delta.tool_calls:
            tool_calls.append({
                #'index': tool_call.index,
                'id': tool_call.id,
                'function': {
                    'arguments': tool_call.function.arguments,
                    'name': tool_call.function.name
                },
                'type': tool_call.type
            })
        return_object = {}
        if choice_delta.content is not None:
            return_object['content'] = choice_delta.content
        if choice_delta.function_call is not None:
            return_object['function_call'] = choice_delta.function_call
        if choice_delta.role is not None:
            return_object['role'] = choice_delta.role
        if tool_calls:
            return_object['tool_calls'] = tool_calls

        return return_object

    def custom_serializer(self, obj):
        # This function is a custom serializer for objects that are not JSON serializable by default.
        if obj.__class__.__name__ == 'ChoiceDelta':
            return self.serialize_choice_delta(obj)
        raise TypeError(f'Object of type {obj.__class__.__name__} is not JSON serializable')

    @listen_to(r"^\.help")
    async def help_function(self, message):
        """help function that returns a list of commands"""
        commands = [
            "### Commands:",
            "---",
            "**.help** - returns this list of commands and usage",
            f"**@{self.driver.client.username} <text>** - returns a response from the chatgpt model (reply to a message to use the context of that thread)",
            "**.vision <text>** - Parse an image while providing it with a question or text (attach image to the message)",
            "**.mkimg <text>** - text to image using DALL-E3; returns an hd image",
            "**.mkstdimg <text>** - text to image using DALL-E3; returns an standard image",
            "**.drtts <text>** - text to speech using DR TTS; returns an audio file",
            "**.tts <text>** - text to speech using pyttsx3; returns an audio file",
            "**.pushups** - pushups help",
            "**.gif <text>** - text to gif using GIPHY; returns a gif",
            "**.decode <encoding> <text>** - decode text using an encoding",
            "**.encode <encoding> <text>** - encode text using an encoding",
            "**.docker help** - returns a list of docker commands",
        ]

        commands_admin = [
            "### Admin commands",
            "---",
            "**.get chatgpt <setting>** - get a setting for chatgpt",
            "**.set chatgpt <setting> <value>** - set a setting for chatgpt",
            "**.model get** - get the model to use for chatgpt",
            "**.model set <model>** - set the model to use for chatgpt",
            "**.reset chatgpt <setting>** - reset a setting for chatgpt",
            "**.users list/add/remove [<username>]** - list/add/remove users",
            "**.admins list/add/remove [<username>]** - list/add/remove admins",
            "**.eval <code>** - run arbitrary python code and return the result to the chat",
            "**.exec <code>** - run arbitrary python code and return the result to the chat",
            "**.s2t <text>**: convert text to token - convert a string to a tokens (for debugging)",
            "**.shell <command>**: run a shell command and return the result to the chat",
            "**.redis search <key>**: search redis for a key",
            "**.redis get <key>**: get a key from redis",
            "**.redis set <key> <value>**: set a key in redis",
            "**.redis del <key>**: delete a key from redis",
            "**.ban <username>** - ban a user from using the bot (permanent)",
            "**.ban <username> <days>** - ban a user from using the bot (for x days)"
            "**.unban <username>** - unban a user from using the bot",
            "**.banlist** - list banned users",
            "#### Settings:",
        ]

        self.helper.add_reaction(message, "robot_face")
        txt = "\n".join(commands)
        self.driver.reply_to(message, f"## :robot_face: Help:\n{txt}\n\n")
        if self.users.is_admin(message.sender_name):
            settings_key = self.SETTINGS_KEY
            for key in self.redis.hkeys(settings_key):
                commands_admin.append(f" - {key}")
            txt = "\n".join(commands_admin)
            self.driver.reply_to(message, f"\n\n{txt}\n", direct=True)

    def append_thread_and_get_messages(self, thread_id, msg):
        """append a message to a chatlog"""
        # self.helper.slog(f"append_chatlog {thread_id} {msg}")
        expiry = 60 * 60 * 24 * 7
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.redis_serialize_json(msg))
        self.redis.expire(thread_key, expiry)
        messages = self.helper.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
        #messages = self.get_formatted_messages(messages)
        return messages

    def get_thread_messages_from_redis(self, thread_id):
        """get a chatlog"""
        thread_key = REDIS_PREPEND + thread_id
        messages = self.helper.redis_deserialize_json(self.redis.lrange(thread_key, 0, -1))
        #messages = self.get_formatted_messages(messages)
        return messages

    def redis_serialize_json(self,msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""
        # return json.dumps(msg)
        return self.redis_serialize_jsonpickle(msg)

    def redis_deserialize_json(self, msg):
        """deserialize a message from json"""
        return self.redis_deserialize_jsonpickle(msg)

    def redis_serialize_jsonpickle(self,msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""
        import jsonpickle
        return jsonpickle.encode(msg, unpicklable=False)

    def redis_deserialize_jsonpickle(self, msg):
        """deserialize a message from json"""
        import jsonpickle
        if isinstance(msg, list):
            return [jsonpickle.decode(m) for m in msg]
        return jsonpickle.decode(msg)


if __name__ == "__main__":
    ChatGPT()
