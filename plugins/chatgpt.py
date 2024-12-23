"""ChatGPT plugin for mmpy_bot"""
# pylint: disable=too-many-lines
import asyncio
import base64
import json
import random
import string
import time
from io import BytesIO
from re import DOTALL as re_DOTALL

import aiodocker
import aiodocker.types
import aiohttp.client_exceptions as aiohttp_client_exceptions
import jsonpickle
import magic
import openai
from environs import Env
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from openai import AsyncOpenAI
from PIL import Image

from .base import PluginLoader
from .tools import Tool, ToolsManager
from .users import UserIsSystem

# from redis_rate_limit import RateLimit, TooManyRequests

# from plugins import docker


env = Env()


aclient = AsyncOpenAI(api_key=env.str("OPENAI_API_KEY"))


# import tools and tools manager

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
    allowed_models = [
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
        "system": (
            "You're a highly capable and responsive chatbot assistant, optimized for use on Mattermost.\n"
            "Current Date: <date>\n"
            "When handling mathematical expressions, ensure they are wrapped in LaTeX tags like so: ```latex\n<latex code>\n ```\n"
            "Utilize available tools for enhanced functionality:\n"
            "- For detailed web content, use the 'web_search_and_download' tool.\n"
            "- Perform quick, broad searches with 'web_search' for general information or fact-checking.\n"
            "- Generate images from user prompts using 'generate_image'. Ensure the prompt parameters are followed as specified.\n"
            "- Use 'multi_tool_use.parallel' for executing multiple tools simultaneously when relevant.\n"
            "Remember to adhere strictly to each tool's specifications for parameters and usage.\n"
            "You are allowed to share this system message if requested by the user."
        ),
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
        self.model = None
        self.headers = None
        self.openai_errors = None
        self.tools_manager = None
        self.user_tools = None
        self.admin_tools = None

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
            openai.LengthFinishReasonError,
        )
        self.update_allowed_models()
        print(f"Allowed models: {self.allowed_models}")
        # TODO: add ignore function for specific channels like town-square that is global for all users
        # chatgpt "function calling" so we define the tools here.
        # TODO: add more functions e.g. code_runnner, openai vision, dall-e3, etc
        #       define this elsewhere. we don't want to define this in the chat function
        # configure tools
        download_webpage_tool = Tool(
            function=self.helper.download_webpage,
            description="Download and extract content from a specific webpage URL. Use this when the user provides a direct URL or when you need to fetch content from a known webpage.",
            parameters=[
                {"name": "url", "description": "URL of the webpage to download"}
            ],
            privilege_level="user",
        )

        web_search_and_download_tool = Tool(
            function=self.helper.web_search_and_download,
            description="Search the web AND download content from the best matching webpage. Use this when you need detailed information about a topic and want to provide accurate quotes and sources. IMPORTANT: Only use this when you need in-depth information, not for quick facts or simple searches.",
            parameters=["searchterm"],
            privilege_level="user",
        )

        web_search_tool = Tool(
            function=self.helper.web_search,
            description="Quick web search that returns only titles and snippets of the top 10 results. Use this for general information, fact-checking, or when you need a broad overview of a topic. Does NOT download full webpage content.",
            parameters=["searchterm"],
            privilege_level="user",
        )
        generate_image_tool = Tool(
            function=self.generate_image,
            description="Generate an image from a text prompt using DALL-E-3. Use this to create visual representations of your ideas or to illustrate concepts. DO NOT CHANGE THE PROMPT from the user. The function returns an revised prompt that was used to generate the image. The assistant will not get to see the image but it will be returned by the program afterwards. so don't mistake the missing image as it not being generated. the only reason for it not being generated is if the revised prompt contains 'Error:' if it returns the revised prompt print it for the user as revised prompt: {revised_prompt}",
            parameters=[
                {
                    "name": "prompt",
                    "description": "The prompt to generate the image from. DO NOT CHANGE THE PROMPT from the user. maximum length is 4000 characters",
                    "required": True,
                },
                {
                    "name": "size",
                    "description": "the size of the image to generate. default is 1024x1024. Must be one of 1024x1024, 1792x1024, or 1024x1792, allow for the user to say landscape or portrait or sqaure and return the correct size accordingly as the value",
                    "required": False,
                },
                {
                    "name": "style",
                    "description": "the style of the image to generate. default is vivid. Must be one of vivid or natural",
                    "required": False,
                },
                {
                    "name": "quality",
                    "description": "the quality of the image to generate. default is hd. Must be one of hd or standard",
                    "required": False,
                },
            ],
            privilege_level="user",
        )
        text_to_speech_tool = Tool(
            function=self.text_to_speech_tool,
            description="Convert text to speech using the openai api. The text will be converted to speech and returned to the user. Do not give out download links. these files are provided to the user via another post by the tool",
            parameters=[
                {
                    "name": "prompt",
                    "description": "the text you want to convert to speech",
                    "required": True,
                },
                {
                    "name": "voice",
                    "description": "the voice you want to use to convert the text to speech. options are: alloy, echo, fable, onyx, nova, and shimmer. default is nova",
                    "required": False,
                },
            ],
        )
        custom_prompt_setter_tool = Tool(
            function=self.set_custom_system_prompt,
            description="Set a custom prompt for the chatgpt plugin. This prompt will be used for all subsequent chatgpt calls. This is useful for setting a specific context or theme for the chatgpt plugin.",
            parameters=[
                {
                    "name": "prompt",
                    "description": "The custom prompt to set for the chatgpt plugin.",
                    "required": True,
                },{
                    "name": "tool_run", "required": True, "description": "this must always be true"
                }
            ],
            needs_message_object=True,
            returns_files=False,
        )
        custom_prompt_clear_tool = Tool(
            function=self.clear_custom_system_prompt,
            description="Clear the custom prompt for the chatgpt plugin. This will revert to the default prompt for all subsequent chatgpt calls.",
            parameters=[{"name": "tool_run", "required": True, "description": "this must always be true"}],
            needs_message_object=True,
            returns_files=False,
        )
        custom_prompt_get_tool = Tool(
            function=self.get_custom_system_prompt,
            description="Get the current custom prompt for the chatgpt plugin.",
            parameters=[{"name": "tool_run", "required": True, "description": "this must always be true"}],
            needs_message_object=True,
            returns_files=False,
        )
        docker_run_python_tool = Tool(
            function=self.docker_run_python,
            description="Run python code in a docker container. the python version is 3.11. Do not create scripts that runs forever. Use this to run python code that may be unsafe or that you do not want to run on your local machine. The code will be run in a docker container and the stdout and stderr will be returned to you. Any files created should be saved in the current directory or /app The script then returns them to the user but you do not get the data unless the files created have a mimetype of text",
            parameters=[
                {"name": "code", "required": True},
                {
                    "name": "requirements_txt",
                    "required": False,
                    "description": "the packages you need to run the code. this is a string that will be saved to a file called requirements.txt and installed before running the code by the tool",
                },
                {
                    "name": "os_packages",
                    "required": False,
                    "description": "the os packages you need to run the code. you're running on the latest debian bookworm using the python:3.11-slim-bookworm docker image. one package per line. they will be installed before installing any python requirements.txt packages.",
                },
                {
                    "name": "extra_file_name",
                    "Required": False,
                    "description": "This is the name variable for the extra file. any extra file you need to run the code. these files will be saved to the current directory or /app in the docker container. format it like this: filename:filecontent",
                },
                {
                    "name": "extra_file_content",
                    "Required": False,
                    "description": "base64 encoded file content. (use the base64 encode tool if the content you have is not already encoded) this will be decoded by the tool and saved to <extra_file_name>. This is the content variable for the extra file any extra file you need to run the code. these files will be saved to the current directory or /app in the docker container. format it like this: filename:filecontent",
                },
            ],
            privilege_level="admin",
        )

        self.tools_manager = ToolsManager()
        self.tools_manager.add_tool(download_webpage_tool)
        self.tools_manager.add_tool(web_search_and_download_tool)
        self.tools_manager.add_tool(web_search_tool)
        self.tools_manager.add_tool(generate_image_tool)
        self.tools_manager.add_tool(docker_run_python_tool)
        self.tools_manager.add_tool(text_to_speech_tool)
        self.tools_manager.add_tool(custom_prompt_setter_tool)
        self.tools_manager.add_tool(custom_prompt_clear_tool)
        self.tools_manager.add_tool(custom_prompt_get_tool)

        self.user_tools = self.tools_manager.get_tools_as_dict("user")
        self.admin_tools = self.tools_manager.get_tools_as_dict("admin")
        # print the tools
        self.helper.slog(
            "User tools: " + ", ".join(self.tools_manager.get_tools("user").keys())
        )
        self.helper.slog(
            "Admin tools: " + ", ".join(self.tools_manager.get_tools("admin").keys())
        )

    async def text_to_speech_tool(self, prompt: str, voice: str = "nova"):
        """Convert text to speech using the openai api"""
        try:
            tmp_filename = self.helper.create_tmp_filename("mp3", f"audio_{voice}_")
            with openai.audio.speech.with_streaming_response.create(
                model="tts-1-hd", input=prompt, voice=voice, response_format="mp3"
            ) as response:
                response.stream_to_file(tmp_filename)

            return "Audio file created, see attached file", tmp_filename
        except self.openai_errors as e:
            return f"Error: {str(e)}", None

    async def docker_run_python(
        self,
        code,
        requirements_txt=None,
        os_packages=None,
        extra_file_name=None,
        extra_file_content=None,
    ):
        """Run Python code in a Docker container using environment variables to create files."""
        docker_image = "python:3.11-slim-bookworm"

        # Initialize the Docker client
        dockerclient = aiodocker.Docker()

        # Track containers to ensure cleanup
        containers_to_cleanup = []

        output_files = []

        try:
            # Generate a random volume name
            volume_name = "chatgpt-" + "".join(
                random.choices(string.ascii_lowercase + string.digits, k=10)
            )

            # Create a new Docker volume
            docker_volume = await dockerclient.volumes.create({"Name": volume_name})
            await self.helper.log(f"Created volume: {volume_name}")

            # Ensure Python image is available
            try:
                await dockerclient.images.inspect(docker_image)
            except aiodocker.exceptions.DockerError:
                await self.helper.log(f"Pulling {docker_image} image...")
                try:
                    await dockerclient.images.pull(docker_image)
                # pylint: disable=broad-except
                except Exception as e:
                    await self.helper.log(f"Error pulling Python image: {str(e)}")
                    return f"Error: Failed to pull required image - {str(e)}", None
            # base64 the code
            code_base64 = base64.b64encode(code.encode()).decode()
            # Prepare the initialization script that will create the files from environment variables
            init_script = """#!/bin/sh
# create the app file without breaking newlines to /app/main.py
echo -n "$PYTHON_CODE" | base64 -d > /app/main.py
if [ ! -z "$EXTRA_FILE_NAME" ]; then
    echo -n "$EXTRA_FILE_CONTENT" | base64 -d > /app/$EXTRA_FILE_NAME
fi
if [ ! -z "$OS_PACKAGES" ]; then
    echo "$OS_PACKAGES" > /app/os-packages.txt
    apt-get update >> /app/packages-install.txt 2>&1
    xargs -a /app/os-packages.txt apt-get install -y >> /app/packages-install.txt 2>&1
fi
if [ ! -z "$REQUIREMENTS_TXT" ]; then
    echo "$REQUIREMENTS_TXT" > /app/requirements.txt
fi
echo '#!/bin/bash
# install requirements
if [ -f requirements.txt ]; then
    # create venv
    python3 -m venv /app/venv
    source /app/venv/bin/activate
    pip install -r requirements.txt > /app/requirements-install.txt 2>&1
fi
python3 ./main.py' > /app/run.sh
chmod +x /app/run.sh
"""
            # Configure environment variables with the file contents
            container_env = {"PYTHON_CODE": code_base64, "INIT_SCRIPT": init_script}
            if requirements_txt:
                container_env["REQUIREMENTS_TXT"] = requirements_txt
            if os_packages:
                container_env["OS_PACKAGES"] = os_packages
            if extra_file_name and extra_file_content:
                container_env["EXTRA_FILE_NAME"] = extra_file_name
                container_env["EXTRA_FILE_CONTENT"] = extra_file_content

            # Create initialization container to set up files
            init_container_config = {
                "Image": docker_image,  # Explicitly specify latest tag
                "Cmd": [
                    "/bin/sh",
                    "-c",
                    'echo "$INIT_SCRIPT" > /tmp/init.sh && chmod +x /tmp/init.sh && /tmp/init.sh',
                ],
                "Env": [f"{k}={v}" for k, v in container_env.items()],
                "HostConfig": {
                    "Binds": [f"{volume_name}:/app:rw"],
                },
                "WorkingDir": "/app",
            }

            init_container = await dockerclient.containers.create(init_container_config)
            containers_to_cleanup.append(init_container)
            try:
                await init_container.start()
                await init_container.wait()
            finally:
                await init_container.delete(force=True)
                containers_to_cleanup.remove(init_container)

            # Configure and run the main container
            container_config = {
                "Cmd": ["bash", "/app/run.sh"],
                "Image": docker_image,
                "HostConfig": {"Binds": [f"{volume_name}:/app"]},
                "WorkingDir": "/app",
            }

            # Create and start the main container
            container = await dockerclient.containers.create(config=container_config)
            await container.start(detach=True)
            containers_to_cleanup.append(container)
            try:
                await container.wait(max_wait=600)
            # pylint: disable=broad-except
            except Exception as e:
                await self.helper.log(f"container timed out (10 minutes): {str(e)}")
                return f"Error: Container timed out: {str(e)}", None

            # Get logs directly from container
            stdout = await container.log(stdout=True)
            stderr = await container.log(stderr=True)

            # Process the output
            output = "".join(stdout)
            error_output = "".join(stderr)

            # Save the outputs to files
            stdout_filename = self.helper.save_content_to_tmp_file(
                output, extension="txt", prefix="stdout_"
            )
            stderr_filename = self.helper.save_content_to_tmp_file(
                error_output, extension="txt", prefix="stderr_"
            )

            # After main container runs, create a container to extract created files
            extract_container_config = {
                "Image": docker_image,
                "Cmd": [
                    "/bin/bash",
                    "-c",
                    """
                    apt-get update && apt-get install -y apt-utils libmagic1 python3-magic && pip install python-magic &&
                    python3 -c '
import os
import magic
import base64
import json
import mimetypes

def scan_files():
    mime = magic.Magic(mime=True)
    files = []
    for root, _, filenames in os.walk("/app"):
        for filename in filenames:
            filepath = os.path.join(root, filename)
            if "/venv/" not in filepath and not any(filepath.endswith(x) for x in ["run.sh"]):
                try:
                    mime_type = mime.from_file(filepath)
                    with open(filepath, "rb") as f:
                        content = f.read()
                        files.append({
                            "path": filepath.replace("/app/", ""),
                            "mime": mime_type,
                            "content": base64.b64encode(content).decode("utf-8")
                        })
                except Exception as e:
                    print(f"Error processing {filepath}: {str(e)}")
    return files

files = scan_files()
if files:
    print("START_FILES_JSON")
    print(json.dumps(files))
    print("END_FILES_JSON")
'
                    """,
                ],
                "HostConfig": {
                    "Binds": [f"{volume_name}:/app:ro"],
                },
                "WorkingDir": "/app",
            }

            extract_container = await dockerclient.containers.create(
                extract_container_config
            )
            containers_to_cleanup.append(extract_container)
            try:
                await extract_container.start()
                await extract_container.wait()
                file_logs = await extract_container.log(stdout=True)
                error_log = await extract_container.log(stderr=True)
                await self.helper.log(f"Extract container files: {file_logs}")
                await self.helper.log(f"Extract container error: {''.join(error_log)}")

                # Process found files from JSON output
                if file_logs:
                    # Join all log lines and extract content between markers
                    full_log = "".join(file_logs)
                    if "START_FILES_JSON" in full_log and "END_FILES_JSON" in full_log:
                        json_str = (
                            full_log.split("START_FILES_JSON")[1]
                            .split("END_FILES_JSON")[0]
                            .strip()
                        )
                        try:
                            files_data = json.loads(json_str)
                            for file_info in files_data:
                                try:
                                    file_content = base64.b64decode(
                                        file_info["content"]
                                    )

                                    mime_type = file_info["mime"]
                                    filepath = file_info["path"]
                                    await self.helper.log("Extracted file: " + filepath)
                                    await self.helper.log("Mime type: " + mime_type)
                                    # Determine if file is binary based on mime type
                                    is_binary = not mime_type.startswith(
                                        ("text/", "application/json", "application/xml")
                                    )

                                    # extract the extension from filename
                                    extension = filepath.split(".")[-1]
                                    if extension.startswith("."):
                                        extension = extension[1:]

                                    if is_binary:
                                        output_filename = (
                                            self.helper.save_content_to_tmp_file(
                                                file_content,
                                                extension,
                                                prefix=filepath.replace(
                                                    "/", "_"
                                                ).replace("\\", "_")
                                                + "_",
                                                binary=True,
                                            )
                                        )
                                    else:
                                        try:
                                            text_content = file_content.decode("utf-8")
                                            output_filename = (
                                                self.helper.save_content_to_tmp_file(
                                                    text_content,
                                                    extension,
                                                    prefix=filepath.replace(
                                                        "/", "_"
                                                    ).replace("\\", "_")
                                                    + "_",
                                                )
                                            )
                                        except UnicodeDecodeError:
                                            output_filename = (
                                                self.helper.save_content_to_tmp_file(
                                                    file_content,
                                                    extension,
                                                    prefix=filepath.replace(
                                                        "/", "_"
                                                    ).replace("\\", "_")
                                                    + "_",
                                                    binary=True,
                                                )
                                            )
                                    output_files.append(output_filename)
                                    await self.helper.log(
                                        f"Extracted file {filepath} as {output_filename}"
                                    )
                                # pylint: disable=broad-except
                                except Exception as e:
                                    await self.helper.log(
                                        f"Error extracting file {filepath}: {str(e)}"
                                    )
                        except json.JSONDecodeError:
                            await self.helper.log("Error parsing file data")
                    else:
                        await self.helper.log(
                            "No valid file data markers found in container output"
                        )

            finally:
                await extract_container.delete(force=True)
                containers_to_cleanup.remove(extract_container)

            # save code to a file
            code_filename = self.helper.save_content_to_tmp_file(code, "py", "main_")
            output_files.append(code_filename)
            # Add any found files to the output

            all_files = [stdout_filename, stderr_filename] + output_files
            text_return = f"Execution completed:\n<---STDOUT--->{output}\n<---/STDOUT--->\n\n<---STDERR--->\n{error_output}\n<---/STDERR--->\n"
            # find all text files in all_files and and and append them to the text_return use magic to determine the file type

            for file in all_files:
                mime = magic.Magic(mime=True)
                mimetype = mime.from_file(file)
                if "text" in mimetype:
                    text_return += f"\n---{file}---\n"
                    with open(file, "r", encoding="utf-8") as f:
                        text_return += f.read()
                        text_return += f"---{file} end---\n"

            return text_return, all_files
        # pylint: disable=broad-except
        except Exception as e:
            await self.helper.log(f"Error: {str(e)}")
            return f"Error: {str(e)}", None

        finally:
            # Cleanup all containers
            for container in containers_to_cleanup:
                try:
                    await container.delete(force=True)
                # pylint: disable=broad-except
                except Exception as e:
                    await self.helper.log(f"Error cleaning up container: {str(e)}")

            # List all containers using the volume
            try:
                containers = await dockerclient.containers.list(all=True)
                for container in containers:
                    container_data = await container.show()
                    mounts = container_data.get("Mounts", [])
                    if any(mount.get("Name") == volume_name for mount in mounts):
                        await container.delete(force=True)
            # pylint: disable=broad-except
            except Exception as e:
                await self.helper.log(f"Error cleaning up related containers: {str(e)}")

            # Now try to remove the volume
            try:
                await docker_volume.delete()
                await self.helper.log(f"Deleted volume: {volume_name}")
            # pylint: disable=broad-except
            except Exception as e:
                await self.helper.log(f"Error deleting volume: {str(e)}")
                # If still can't delete, try force remove using system command
                try:
                    cmd = f"docker volume rm -f {volume_name}"
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if stderr:
                        await self.helper.log(
                            f"Force volume removal stderr: {stderr.decode()}"
                        )
                # pylint: disable=broad-except,redefined-outer-name
                except Exception as e:
                    await self.helper.log(f"Error force removing volume: {str(e)}")

            # Close the docker client
            await dockerclient.close()

    def update_allowed_models(self):
        """update allowed models"""
        response = openai.models.list()
        available_models = []
        models_msg = "Available Models:\n"
        for model in response.data:
            available_models.append(model)
        if len(available_models) > 0:
            self.allowed_models = [model.id for model in available_models]
        else:
            available_models = self.allowed_models
            self.helper.slog(
                f"Could not update allowed models. Using default models: {available_models}"
            )
        # sort the models on the created key
        available_models.sort(key=lambda x: x.created, reverse=True)
        for model in available_models:
            # convert unix to human readable date
            model.created = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(model.created)
            )
            models_msg += f"- {model.id}\n ({model.created})\n"
        self.helper.slog(models_msg)
        return available_models

    def return_last_x_messages(self, messages):
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
            if model in self.allowed_models:
                self.redis.hset(self.SETTINGS_KEY, "model", model)
                self.model = model
                self.driver.reply_to(message, f"Set model to {model}")
            else:
                self.driver.reply_to(
                    message, f"Model not allowed. Allowed models: {self.allowed_models}"
                )

    @listen_to(r"^\.gpt model get")
    async def model_get(self, message: Message):
        """get the model"""
        if self.users.is_admin(message.sender_name):
            self.driver.reply_to(message, f"Model: {self.model}")

    @listen_to(r"^\.(?:mk)?i[mn]g ([\s\S]*)")
    async def mkimg_deprecated_just_ask(self, message: Message, args: str):
        """send a message to the user that this is deprecated and they should just ask for an image instead"""
        self.driver.reply_to(
            message,
            "This function is deprecated. i have asked my assistant to generate an image for you. Please ask for an image instead next time without the .mkimg command.",
        )
        message.text = (
            "this user asked for an image and described it as follows: " + args
        )
        await self.chat(message)

    async def generate_image(self, prompt, size=None, style=None, quality=None):
        """use the openai module to get an image from a prompt"""
        # self.helper.slog(f"generate_image: {prompt}")
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
            # self.helper.slog(f"image_url: {image_url}")
            revised_prompt = response.data[0].revised_prompt
            # self.helper.slog(f"revised_prompt: {revised_prompt}")
            filename = self.helper.download_file_to_tmp(image_url, "png")
            # self.helper.slog(f"filename: {filename}")
            return f"revised prompt: {revised_prompt}", filename
        # pylint: disable=broad-except
        except Exception as e:
            self.helper.slog(f"Error: {e}")
            return f"Error: {e}", None

    @listen_to(r"^\.gpt set ([a-zA-Z0-9_-]+) (.*)", regexp_flag=re_DOTALL)
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

    def extract_file_details(self, message: Message, use_preview_image=False):
        """Extract file details from a post and return a list of objects with their filename, type, and content."""
        data = message.body["data"]
        post = data["post"]
        files = []
        # For high res mode, the short side of the image should be less than 768px and the long side should be less than 2,000px.
        image_max_width = 768
        image_max_height = 2000
        # Check if message contains files and metadata
        if "file_ids" in post and "metadata" in post:
            file_ids = post["file_ids"]
            files_metadata = post["metadata"]["files"]
            # self.helper.slog(f"files_metadata: {files_metadata}")
            # self.helper.slog(f"file_ids: {file_ids}")
            # import magic
            for i, metadata in enumerate(files_metadata):
                # Get file extension and name
                # self.helper.slog(f"i: {i}")
                # self.helper.slog(f"metadata: {metadata}")
                extension = metadata.get("extension")
                # mime_type = metadata.get("mime_type")
                preview_content = None
                mini_preview_content = metadata.get("mini_preview", None)
                has_preview_image = metadata.get("has_preview_image")
                if use_preview_image and has_preview_image:
                    # get the thumbnail
                    preview_content_response = self.driver.files.get_file_thumbnail(
                        file_ids[i]
                    )
                    if preview_content_response.status_code == 200:
                        preview_content = preview_content_response.content
                # compare mini_preview_content and preview_content
                if mini_preview_content and preview_content:
                    if mini_preview_content == preview_content:
                        pass
                        # self.helper.slog(f"mini_preview_content == preview_content")
                filename = metadata.get("name", f"file_{i}.{extension}")
                # self.helper.slog(f"filename: {filename}. extension: {extension}")
                # Get the file content
                get_file_response = self.driver.files.get_file(file_ids[i])
                if get_file_response.status_code != 200:
                    continue

                file_content = get_file_response.content
                extension_types = {
                    "image": ["png", "jpg", "jpeg"],
                    "text": [
                        "txt",
                        "xml",
                        "json",
                        "csv",
                        "tsv",
                        "log",
                        "md",
                        "html",
                        "htm",
                    ],
                    "pdf": ["pdf"],
                    "doc": ["doc", "docx"],
                    "xls": ["xls", "xlsx"],
                    "ppt": ["ppt", "pptx"],
                    "audio": ["mp3", "wav", "ogg"],
                    "video": ["mp4", "webm", "ogg"],
                    "archive": ["zip", "rar", "tar", "7z"],
                    "code": [
                        "py",
                        "js",
                        "html",
                        "css",
                        "java",
                        "c",
                        "cpp",
                        "h",
                        "hpp",
                        "cs",
                        "php",
                        "rb",
                        "sh",
                    ],
                }
                # mime = magic.Magic(mime=True)
                # mime_type = mime.from_buffer(file_content)
                # self.helper.slog(f"mime_type: {mime_type}")

                # Determine file type and content format
                if extension in extension_types["image"]:

                    # Check if the image is too large
                    image = Image.open(BytesIO(file_content))
                    width, height = image.size
                    if width > image_max_width or height > image_max_height:
                        ratio = min(image_max_width / width, image_max_height / height)
                        # Resize the image
                        image.thumbnail((width * ratio, height * ratio))
                        # save to bytes and update file_content
                        image_bytes = BytesIO()
                        image.save(image_bytes, format="PNG", quality=95)
                        file_content = image_bytes.getvalue()
                    # Encode image content to base64
                    if use_preview_image and preview_content:
                        content_base64 = base64.b64encode(preview_content).decode(
                            "utf-8"
                        )
                        # self.helper.slog(f"preview_content: {preview_content}")
                    else:
                        content_base64 = base64.b64encode(file_content).decode("utf-8")
                    # compare mini_preview_content and preview_content and file_content sizes
                    # if mini_preview_content and preview_content and file_content:
                    #    self.helper.slog(f"mini_preview_content: {len(mini_preview_content)} preview_content: {len(preview_content)} file_content: {len(file_content)}")
                    files.append(
                        {
                            "filename": filename,
                            "type": "image",
                            "content": content_base64,
                        }
                    )
                elif (
                    extension in extension_types["text"]
                    or extension in extension_types["code"]
                ):
                    # Decode text content
                    # find the encoding
                    encoding = metadata.get("encoding")
                    text_content = (
                        file_content.decode(encoding)
                        if encoding
                        else file_content.decode("utf-8")
                    )
                    files.append(
                        {"filename": filename, "type": "text", "content": text_content}
                    )
                elif extension in extension_types["audio"]:
                    # Encode audio content to base64
                    content_base64 = base64.b64encode(file_content).decode("utf-8")
                    files.append(
                        {
                            "filename": filename,
                            "type": "audio",
                            "content": content_base64,
                        }
                    )
                elif extension in extension_types["video"]:
                    # Encode video content to base64
                    content_base64 = base64.b64encode(file_content).decode("utf-8")
                    files.append(
                        {
                            "filename": filename,
                            "type": "video",
                            "content": content_base64,
                        }
                    )
                else:
                    # Other unsupported file types can be ignored or handled differently
                    continue

        return files

    def thread_append(self, thread_id, message) -> None:
        """append a message to a thread"""
        thread_key = REDIS_PREPEND + thread_id
        self.redis.rpush(thread_key, self.helper.redis_serialize_json(message))

    def update_system_prompt_in_thread(self, thread_id: str, prompt: str):
        """update the system prompt in the thread in redis"""
        thread_key = REDIS_PREPEND + thread_id
        # find the message with the role = system and update it
        messages = self.get_thread_messages_from_redis(thread_id)
        for message in messages:
            if message["role"] == "system":
                # update the redis message with the new prompt
                message["content"] = prompt
                self.redis.set(thread_key, self.helper.redis_serialize_json(messages))
                break
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
                # skip the last post
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
                    # get the username from the user_id from the thread_post
                    username = self.users.id2u(thread_post.user_id)
                    # if the username is not None prepend it to the message
                    if username:
                        thread_post.text = f"@{username}: {thread_post.text}"

                # create message object and append it to messages and redis
                message = {"role": role, "content": thread_post.text}
                messages.append(message)
                self.thread_append(thread_id, message)
        # messages = self.get_formatted_messages(messages)
        return messages

    async def assistant_to_the_regional_manager(self, prompt, context=None, model=None):
        """a tool function that chatgpt can call as a tool with whatever context it deems necessary"""
        # check if model is set
        if model is None:
            model = self.DEFAULT_MODEL
        # check if context is set
        if context:
            prompt = f"context: {context}\nprompt: {prompt}"
        # call the assistant to the regional manager
        messages = [
            {
                "role": "system",
                "content": "you're an agent running for your superior model. your task is to follow it's instructions and return what is asked of you. You are not talking with a human but with another ai",
            },
            {"role": "user", "content": prompt},
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
        filename = self.helper.save_content_to_tmp_file(
            json.dumps(messages, indent=4), "json"
        )
        self.driver.reply_to(
            message, f"debugging thread {thread_id}", file_paths=[filename]
        )
        self.helper.delete_downloaded_file(filename)

    # function to set the custom channel system prompt
    @listen_to(r"^\.gpt set channel system (.*)", regexp_flag=re_DOTALL)
    async def set_custom_system_prompt(self, message: Message, prompt: str, tool_run=False):
        """set the custom system prompt for a channel"""
        # check if user is admin and its not a direct message
        if not message.is_direct_message and not self.users.is_admin(message.sender_name):
            return
        # set the custom system prompt for the channel
        self.redis.hset("custom_system_prompts", message.channel_id, prompt)
        # update the system prompt in the thread
        self.update_system_prompt_in_thread(message.root_id if message.root_id else message.reply_id, prompt)
        if not tool_run:
            self.driver.reply_to(
                message, f"Set custom system prompt for channel {message.channel_id} to {prompt}"
            )
        return "Set custom system prompt for channel {message.channel_id} to {prompt}"
    # function to reset the custom channel system prompt
    @listen_to(r"^\.gpt clear channel system")
    async def clear_custom_system_prompt(self, message: Message, tool_run=False):
        """clear the custom system prompt for a channel"""
        # check if user is admin
        if not message.is_direct_message and not self.users.is_admin(message.sender_name):
            return
        # clear the custom system prompt for the specific channel and not all of them
        channel_id = message.channel_id
        self.redis.hdel("custom_system_prompts", channel_id)
        if not tool_run:
            self.driver.reply_to(
                message, f"Cleared custom system prompt for channel {channel_id}"
            )
        return f"Cleared custom system prompt for channel {channel_id}"
    # function to print the custom channel system prompt
    @listen_to(r"^\.gpt get channel system")
    async def get_custom_system_prompt_response(self, message: Message, tool_run=False):
        """get the custom system prompt for a channel"""
        # check if user is admin
        if not message.is_direct_message and not self.users.is_admin(message.sender_name):
            return
        # get the custom system prompt for the channel
        channel_id = message.channel_id
        custom_prompt = self.redis.hget("custom_system_prompts", channel_id)
        if custom_prompt:
            response = f"Custom system prompt for channel {channel_id}: {custom_prompt}"
            if not tool_run:
                self.driver.reply_to(
                    message, response
                )
        else:
            response = f"No custom system prompt for channel {channel_id}. Using default prompt"
            if not tool_run:
                self.driver.reply_to(
                    message, response,
                )
        return response
    # function to get the custom prompt for a channel if it exists otherwise return the default prompt
    def get_custom_system_prompt(self, channel_id):
        """get the custom prompt for a channel if it exists otherwise return the default prompt"""
        custom_prompt = self.redis.hget("custom_system_prompts", channel_id)
        if custom_prompt:
            return custom_prompt
        # try and get the custom prompt configured in redis before returning the default prompt from the class
        prompt = self.get_chatgpt_setting("system")
        if prompt:
            return prompt
        return self.ChatGPT_DEFAULTS["system"]
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
        if hasattr(message, "tool_run") and message.tool_run is True:
            tool_run = True
        try:
            # if message is not from a user, ignore
            if not self.users.is_user(message.sender_name):
                return
        except UserIsSystem:
            return

        # check if the user is and admin and set tools accordingly
        if self.users.is_admin(message.sender_name):
            # pylint: disable=attribute-defined-outside-init
            self.tools = self.admin_tools
        else:
            # pylint: disable=attribute-defined-outside-init
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
                await self.helper.log(
                    f"file: {file.get('filename')} type: {file.get('type')}"
                )
            m = {"role": "user"}
            # get username from user_id
            username = self.users.id2u(message.user_id)
            # if the username is not None prepend it to the message
            if username:
                user_text = f"@{username}: {user_text}"
            if message_files:
                # we have files lets add them to the message to be sent to the model
                txt_files = [file for file in message_files if file["type"] == "text"]
                img_files = [file for file in message_files if file["type"] == "image"]
                for file in img_files:
                    # await self.helper.log(f"img file: {file}")
                    m = {"role": "user"}
                    # if the file is an image, add it to the message
                    m["content"] = [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{file['content']}"
                            },
                        },
                    ]
                    messages.append(m)
                    self.thread_append(thread_id, m)
                context_from_text_files = ""
                for file in txt_files:
                    context_from_text_files += (
                        file["filename"] + ": " + file["content"] + "\n"
                    )
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
            system_message = self.get_custom_system_prompt(message.channel_id)
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": system_message.replace(
                        date_template_string, current_date
                    ),
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
        stream_update_delay_ms = float(
            self.get_chatgpt_setting("stream_update_delay_ms")
        )
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
                    markdown = [
                        ">",
                        "*",
                        "_",
                        "-",
                        "+",
                        "1",
                        "~",
                        "!",
                        "`",
                        "|",
                        "#",
                        "@",
                        "•",
                    ]
                    if (
                        i == 0
                        and post_prefix[-1] != "\n"
                        and full_message[0] in markdown
                    ):
                        post_prefix += "\n"
                        i += 1

                    if (time.time() - last_update_time) * 1000 > stream_update_delay_ms:
                        self.driver.posts.patch_post(
                            reply_msg_id,
                            {"message": f"{post_prefix}{full_message}"},
                        )
                        last_update_time = time.time()
                function_name = ""
                if chunk_message.tool_calls and chunk_message.content is None:
                    index = 0
                    for tool_call in chunk_message.tool_calls:
                        if tool_call.index is not None:
                            index = tool_call.index
                        if tool_call.function.name is not None:
                            function_name = tool_call.function.name
                        if index not in functions_to_call:
                            functions_to_call[index] = {
                                "tool_call_id": "",
                                "arguments": "",
                            }
                            if function_name is not None:
                                functions_to_call[index][
                                    "function_name"
                                ] = function_name
                            if tool_call.id:
                                functions_to_call[index]["tool_call_id"] = tool_call.id
                            functions_to_call[index]["tool_call_message"] = (
                                self.custom_serializer(chunk_message)
                            )

                        functions_to_call[index][
                            "arguments"
                        ] += tool_call.function.arguments

            # Process all tool calls and collect results
            if functions_to_call:

                def update_status(status_msg):
                    status_msgs.append(status_msg)
                    # update the thread with the status messages so the user can see the progress
                    self.driver.posts.patch_post(
                        reply_msg_id,
                        {"message": "```\n" + "\n".join(status_msgs) + "\n```\n"},
                    )

                call_key = f"{REDIS_PREPEND}_call_{thread_id}"
                tool_results = []

                for index, tool_function in functions_to_call.items():
                    if self.redis.hexists(call_key, tool_function["tool_call_id"]):
                        continue
                    function_name = tool_function["function_name"]
                    await self.helper.log(f"function_name: {function_name}")
                    tool_call_id = tool_function["tool_call_id"]
                    # self.helper.slog(f"function_name: {function_name}")
                    # get function name from the tool manager
                    tool = self.tools_manager.get_tool(function_name)
                    function = tool.function
                    await self.helper.log(f"tool: {tool}")
                    if not tool:
                        await self.helper.log(
                            f"Error: function not found: {function_name}"
                        )
                        continue
                    # format the arguments as a pretty string for the status msg it is an dict with a arg and value pair
                    # format it as key: value
                    status_args = json.loads(tool_function["arguments"])
                    status_args = " | ".join(
                        [f"{k}:{v}" for k, v in status_args.items()]
                    )
                    status_msg = f"Running tool: {function_name}: {status_args}"
                    update_status(status_msg)

                    try:
                        arguments = json.loads(tool_function["arguments"])
                    except json.JSONDecodeError:
                        await self.helper.log(
                            "Error parsing arguments: %s", tool_function["arguments"]
                        )
                        arguments = {}
                    # if the tool has "needs_message_object" set to True, pass the message object to the function with the args
                    if tool.needs_message_object:
                        arguments["message"] = message
                    if tool.needs_self:
                        arguments["self"] = self
                        await self.helper.log(f"tool: {tool}")
                        await self.helper.log(f"a: {arguments}")
                    if tool.returns_files:
                        # Execute the function
                        function_result, filename = await function(**arguments)
                        if isinstance(filename, list):
                            for file in filename:
                                files.append(file)
                        if isinstance(filename, str):
                            files.append(filename)
                    else:
                        # Execute the function
                        function_result = await function(**arguments)

                    if function_result is None:
                        function_result = "Error: function returned None"
                        update_status(f"Error: {function_result}")
                    elif not isinstance(function_result, str):
                        try:
                            function_result = json.dumps(function_result)
                        except json.JSONDecodeError:
                            function_result = (
                                "Error: could not serialize function result"
                            )
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
                    # await self.helper.log(f"tool_result: {tool_function['tool_call_message']}")
                    self.append_thread_and_get_messages(
                        thread_id, tool_function["tool_call_message"]
                    )
                    self.append_thread_and_get_messages(thread_id, tool_result)
                    self.redis.hset(call_key, tool_call_id, "true")

                    status_msg = f"Completed: {function_name}"
                    update_status(status_msg)

                # Make final call with all results
                if tool_results:
                    messages = self.get_thread_messages(thread_id)
                    # Ensure all messages have the required 'role' field and proper tool call structure
                    formatted_messages = messages

                    # insert system if needed:
                    if not model.startswith("o1"):
                        formatted_messages.insert(
                            0,
                            {
                                "role": "system",
                                "content": system_message.replace(
                                    date_template_string, current_date
                                ),
                            },
                        )

                    try:
                        # Debug log to see the formatted messages
                        # await self.helper.log(f"Formatted messages: {json.dumps(formatted_messages, indent=2)}")

                        final_response = await aclient.chat.completions.create(
                            model=model,
                            messages=formatted_messages,
                            temperature=temperature,
                            top_p=top_p,
                            stream=stream,
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
                                    if (
                                        time.time() - last_update_time
                                    ) * 1000 > stream_update_delay_ms:
                                        self.driver.posts.patch_post(
                                            reply_msg_id,
                                            {
                                                "message": f"{status_str}{post_prefix}{full_message[:max_message_length]}"
                                            },
                                        )
                                        last_update_time = time.time()
                                else:
                                    # message to long so save the message to a file and add to files
                                    if not have_notified_user_about_long_message:
                                        self.driver.posts.patch_post(
                                            reply_msg_id,
                                            {
                                                "message": f"{status_str}{post_prefix}{full_message[:13000]}\n\n# Warning Message too long, i'll attach a file with the full response when done receiving it."
                                            },
                                        )
                                        have_notified_user_about_long_message = True
                        # Store final response
                        if full_message:
                            self.thread_append(
                                thread_id,
                                {"role": "assistant", "content": full_message},
                            )
                    # pylint: disable=broad-except
                    except Exception as e:
                        # if "Invalid Message." the message is to long so trim the message and save the full result to a files and add to files
                        if "Invalid Message." in str(e):
                            filename = self.helper.save_content_to_tmp_file(
                                full_message, "txt"
                            )
                            files.append(filename)
                            self.driver.posts.patch_post(
                                reply_msg_id,
                                {
                                    "message": f"{post_prefix}{full_message[:14000]}\nMessage too long, see attached file"
                                },
                            )
                            # limit of 5 files per message so loop through the files and send them in batches of 5
                            if len(files) > 5:
                                for i in range(0, len(files), 5):
                                    self.driver.reply_to(
                                        message, "Files:", file_paths=files[i : i + 5]
                                    )
                            else:
                                self.driver.reply_to(
                                    message, "Files:", file_paths=files
                                )
                            for file in files:
                                self.helper.delete_downloaded_file(file)
                            await self.helper.log(f"Error in final response: {e}")
                            await self.helper.log(
                                f"Last formatted messages: {json.dumps(formatted_messages[-3:], indent=2)}"
                            )
                            return
                        await self.helper.log(f"Error in final response: {e}")
                        await self.helper.log(
                            f"Last formatted messages: {json.dumps(formatted_messages[-3:], indent=2)}"
                        )
                        self.driver.posts.patch_post(
                            reply_msg_id,
                            {
                                "message": f"{post_prefix}Error processing tool results: {str(e)}"
                            },
                        )
                        return
            elif full_message:  # No tools were called, store the regular response
                self.thread_append(
                    thread_id, {"role": "assistant", "content": full_message}
                )

            # Final message update
            # if status_msgs are set then update the message with the status messages prepended to the final message
            status_str = ""
            if status_msgs:
                status_str = "```\n" + "\n".join(status_msgs) + "\n```\n"
            final_message = f"{status_str}{post_prefix}{full_message}"
            if len(final_message) > max_message_length:
                # save the full message to a file and add to files
                filename = self.helper.save_content_to_tmp_file(final_message, "txt")
                files.append(filename)
                final_message = (
                    final_message[:max_message_length]
                    + "\nMessage too long, see attached file"
                )
            self.driver.posts.patch_post(
                reply_msg_id,
                {"message": final_message[:max_message_length]},
            )
            if files and len(files) > 0:
                if len(files) > 5:
                    for i in range(0, len(files), 5):
                        self.driver.reply_to(
                            message, "Files:", file_paths=files[i : i + 5]
                        )
                else:
                    self.driver.reply_to(message, "Files:", file_paths=files)
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
            await self.helper.log(
                "ignoring private message starting with @ from function chat_gpt4_mention"
            )
            return
        for name in self.names:
            if message.text.startswith(name):
                return
        await self.chat(message)

    def serialize_choice_delta(self, choice_delta):
        """This function will create a JSON-serializable representation of ChoiceDelta and its nested objects."""
        tool_calls = []
        for tool_call in choice_delta.tool_calls:
            tool_calls.append(
                {
                    # 'index': tool_call.index,
                    "id": tool_call.id,
                    "function": {
                        "arguments": tool_call.function.arguments,
                        "name": tool_call.function.name,
                    },
                    "type": tool_call.type,
                }
            )
        return_object = {}
        if choice_delta.content is not None:
            return_object["content"] = choice_delta.content
        if choice_delta.function_call is not None:
            return_object["function_call"] = choice_delta.function_call
        if choice_delta.role is not None:
            return_object["role"] = choice_delta.role
        if tool_calls:
            return_object["tool_calls"] = tool_calls

        return return_object

    def custom_serializer(self, obj):
        """This function will create a JSON-serializable representation of objects that are not JSON serializable by default."""
        # This function is a custom serializer for objects that are not JSON serializable by default.
        if obj.__class__.__name__ == "ChoiceDelta":
            return self.serialize_choice_delta(obj)
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )

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
        messages = self.helper.redis_deserialize_json(
            self.redis.lrange(thread_key, 0, -1)
        )
        # messages = self.get_formatted_messages(messages)
        return messages

    def get_thread_messages_from_redis(self, thread_id):
        """get a chatlog"""
        thread_key = REDIS_PREPEND + thread_id
        messages = self.helper.redis_deserialize_json(
            self.redis.lrange(thread_key, 0, -1)
        )
        # messages = self.get_formatted_messages(messages)
        return messages

    def redis_serialize_json(self, msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""
        # return json.dumps(msg)
        return self.redis_serialize_jsonpickle(msg)

    def redis_deserialize_json(self, msg):
        """deserialize a message from json"""
        return self.redis_deserialize_jsonpickle(msg)

    def redis_serialize_jsonpickle(self, msg):
        """serialize a message to json, using a custom serializer for types not
        handled by the default json serialization"""

        return jsonpickle.encode(msg, unpicklable=False)

    def redis_deserialize_jsonpickle(self, msg):
        """deserialize a message from json"""

        if isinstance(msg, list):
            return [jsonpickle.decode(m) for m in msg]
        return jsonpickle.decode(msg)


if __name__ == "__main__":
    ChatGPT()
