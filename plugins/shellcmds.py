from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from plugins.base import PluginLoader
import validators
import re
import dns.resolver
import ipaddress
import urllib.parse
import subprocess
import shlex
import asyncio
SHELL_COMMANDS = {
    "ping": {"validators": ["ipv4", "domain"], "command": "ping", "args": "-c 4 -W 1"},
    "ping6": {
        "validators": ["ipv6", "domain"],
        "command": "ping6",
        "args": "-c 4 -W 1",
    },
    "dig": {"validators": ["ip", "domain"], "command": "dig", "args": "+short"},
    "traceroute": {
        "validators": ["ipv4", "domain"],
        "command": "traceroute",
        "args": "-w 1",
    },
    "traceroute6": {
        "validators": ["ipv6", "domain"],
        "command": "traceroute6",
        "args": "-w 1",
    },
    "whois": {"validators": ["ip", "domain", "asn"], "command": "whois", "args": ""},
    "head": {
        "validators": ["url", "domain"],
        "command": "curl",
        "args": "-I -L",
        "allowed_args": ["-I", "-L", "-k"],
    },
    "get": {
        "validators": ["url", "domain"],
        "command": "curl",
        "args": "-L",
        "allowed_args": ["-k"],
    },
    "date": {"validators": [], "command": "date", "args": ""},
    "uptime": {"validators": [], "command": "uptime", "args": ""},
    "ptr": {"validators": ["ip"], "command": "dig", "args": "+short -x"},
    "aaaa": {"validators": ["domain"], "command": "dig", "args": "+short -t AAAA"},
    "cname": {"validators": ["domain"], "command": "dig", "args": "+short -t CNAME"},
    "mx": {"validators": ["domain"], "command": "dig", "args": "+short -t MX"},
    "ns": {"validators": ["domain"], "command": "dig", "args": "+short -t NS"},
    "soa": {"validators": ["domain"], "command": "dig", "args": "+short -t SOA"},
    "txt": {"validators": ["domain"], "command": "dig", "args": "+short -t TXT"},
    "nmap": {
        "validators": ["ip", "domain"],
        "command": "nmap",
        "args": "-T4",
        "allowed_args": [
            "-6",
            "-Pn",
            "-sC",
            "-PN",
            "-sO",
            "-O",
            "-T4",
            "-p-",
            "--open",
            "-sV",
            "-n",
            "-sS",
            "-sU",
            "-sT",
            "-sA",
        ],
    },
    "tcpportcheck": {
        "validators": ["ip", "domain", "port"],
        "command": "nc",
        "args": "-vz",
        "allowed_args": ["-vz"],
    },
}


class ShellCmds(PluginLoader):

    def validatecommand(self, command):
        """check if commands is in a list of commands allowed"""
        if command in SHELL_COMMANDS:
            return SHELL_COMMANDS[command]
        else:
            return False
            # return { "error": f"invalid command. supported commands: {' '.join(list(SHELL_COMMANDS.keys()))}" }

    def validateinput(self, input, types=["domain", "ip"], allowed_args=[]):
        """function that takes a string and validates that it matches against one or more of the types given in the list"""
        self.helper.validate_input(input, types, allowed_args)

    @listen_to(r"^!(.*)")
    async def run_command(self, message: Message, command):
        """ runs a command after validating the command and the input"""
        # check if user is user (lol)
        if not self.users.is_user(message.sender_name):
            self.driver.reply_to(
                message, f"Error: {message.sender_name} is not a user")
            return
        await self.helper.log(f"{message.sender_name} tried to run command: !{command}")
        # split command into command and input
        command = command.split(" ", 1)
        if len(command) == 1:
            command = command[0]
            input = ""
        else:
            command, input = command
        if command not in SHELL_COMMANDS.keys():
            return
        if command == "help":
            # send a list of commands from SHELL_COMMANDS
            messagetxt = f"Allowed commands:\n"
            messagetxt += f"!help\n"
            for command in SHELL_COMMANDS.keys():
                argstxt = ""
                valtxt = ""
                if "allowed_args" in SHELL_COMMANDS[command]:
                    argstxt = f"[{' / '.join(SHELL_COMMANDS[command]['allowed_args'])}]"
                if "validators" in SHELL_COMMANDS[command] and len(SHELL_COMMANDS[command]['validators']) > 0:
                    valtxt = f"<{' / '.join(SHELL_COMMANDS[command]['validators'])}>"
                messagetxt += f"!{command} {argstxt} {valtxt}\n"
            self.driver.reply_to(message, messagetxt)
            return
        validators = []
        args = ""
        valid_commands = self.validatecommand(command)
        if not valid_commands:
            return
        if "error" in valid_commands:
            self.driver.reply_to(message, f"Error: {valid_commands['error']}")
            await self.helper.log(f"Error: {valid_commands['error']}")
            return
        else:
            validators = valid_commands["validators"]
            command = valid_commands["command"]
            args = valid_commands["args"]
            if "allowed_args" in valid_commands:
                allowed_args = valid_commands["allowed_args"]
                validators.append("argument")
            else:
                allowed_args = []
            # validate input for each word in input
            if input != "":
                inputs = input.split(" ")
                for word in inputs:
                    valid_input = self.validateinput(
                        word, validators, allowed_args)
                    # check if dict
                    if type(valid_input) is dict:
                        if "error" in valid_input:
                            self.driver.reply_to(
                                message, f"Error: {valid_input['error']}")
                            await self.helper.log(f"Error: {valid_input['error']}")
                            return False
                    if valid_input is False:
                        self.driver.reply_to(
                            message, f"Error: {word} is not a valid input to {command}")
                        await self.helper.log(f"Error: {word} is not a valid input to {command}")
                        return False
                    # run command
            self.helper.add_reaction(message, "hourglass")
            await self.helper.log(f"{message.sender_name} is running command: {command} {args} {input}")
            cmd = shlex.split(f"{command} {args} {input}")
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            timeout = False
            try:
                output, error = process.communicate(timeout=10)
                output = output.decode("utf-8")
                error = error.decode("utf-8")
            except subprocess.TimeoutExpired:
                process.kill()
                output, error = process.communicate()
                if output:
                    output = output.decode("utf-8")
                if error:
                    error = error.decode("utf-8")
                timeout = True
            self.helper.remove_reaction(message, "hourglass")
            self.driver.reply_to(
                message, f"{command} {args} {input}\nResult:\n```\n{output}\n```")
            if error:
                self.driver.reply_to(message, f"Error:\n```\n{error}\n```")
            if timeout:
                self.driver.reply_to(message, f"Timed out: 10 seconds")
            await self.helper.log(f"{message.sender_name} ran command: {command} {args} {input}")

    @listen_to(r"^\.exec (.*)")
    async def admin_exec_function(self, message, code):
        """exec function that allows admins to run arbitrary python code and return the result to the chat"""
        reply = ""
        if self.users.is_admin(message.sender_name):
            try:
                resp = exec(code)  # pylint: disable=exec-used
                reply = f"Executed: {code} \nResult: {resp}"
            except Exception as error_message:  # pylint: disable=broad-except
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)

    @listen_to(r"^\.shell (.*)")
    async def admin_shell_function(self, message, code):
        """shell function that allows admins to run arbitrary shell commands and return the result to the chat"""
        reply = ""
        shellescaped_code = shlex.quote(code)
        shell_part = f"docker run lbr/ubuntu:utils /bin/bash -c "
        shellcode = (
            f'docker run lbr/ubuntu:utils /bin/bash -c "{shellescaped_code}"'
        )
        command = f"{shell_part} {shellcode}"
        command_parts = shlex.split(command)
        c = command_parts[0]
        c_rest = command_parts[1:]
        if self.users.is_admin(message.sender_name):
            try:
                self.driver.react_to(message, "runner")
                proc = await asyncio.create_subprocess_exec(
                    c,
                    *command_parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                stdout = stdout.decode("utf-8")
                stderr = stderr.decode("utf-8")
                reply = f"Executed: {code}\t\n{shellcode} \nResult: {proc.returncode} \nOutput:\n{stdout}"
                if proc.returncode != 0:
                    reply += f"\nError:\n{stderr}"
                    self.driver.react_to(message, "x")
                else:
                    self.driver.react_to(message, "white_check_mark")
            except asyncio.TimeoutError as error_message:
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)
            # remove thought balloon
            self.driver.reactions.delete_reaction(
                self.driver.user_id, message.id, "runner"
            )
    # restart bot

    @listen_to(r"^\.restart$")
    async def restart(self, message: Message):
        """restarts the bot"""
        if self.users.is_admin(message.sender_name):
            await self.helper.log(f"{message.sender_name} is restarting the bot")
            self.driver.reply_to(message, "Restarting...")
            import sys
            sys.exit(1)
    # eval function that allows admins to run arbitrary python code and return the result to the chat

    @listen_to(r"^\.eval (.*)")
    async def admin_eval_function(self, message, code):
        """eval function that allows admins to run arbitrary python code and return the result to the chat"""
        reply = ""
        if self.users.is_admin(message.sender_name):
            try:
                resp = eval(code)  # pylint: disable=eval-used
                reply = f"Evaluated: {code} \nResult: {resp}"
            except Exception as error_message:  # pylint: disable=broad-except
                reply = f"Error: {error_message}"
            self.driver.reply_to(message, reply)

    @listen_to(r"^.(de|en)code ([a-zA-Z0-9]+) (.*)")
    async def decode(self, message: Message, method: str, encoding: str, text: str):
        """decode text using a model"""
        supported_encodings = ["base64", "b64", "url"]
        encode = True if method == "en" else False
        decode = True if method == "de" else False
        if self.users.is_user(message.sender_name):
            if text == "" or encoding == "" or encoding == "help":
                # print help message
                messagetxt = (
                    f".encode <encoding> <text> - encode text using an encoding\n"
                )
                messagetxt += (
                    f".decode <encoding> <text> - decode text using an encoding\n"
                )
                messagetxt += f"Supported encodings: {' '.join(supported_encodings)}\n"
                self.driver.reply_to(message, messagetxt)
                return
            # check if encoding is supported
            if encoding not in supported_encodings:
                self.driver.reply_to(
                    message,
                    f"Error: {encoding} not supported. only {supported_encodings} is supported",
                )
                return
            if encoding == "base64" or encoding == "b64":
                try:
                    import base64

                    if decode:
                        text = base64.b64decode(text).decode("utf-8")
                    if encode:
                        text = base64.b64encode(
                            text.encode("utf-8")).decode("utf-8")
                except Exception as error:
                    self.driver.reply_to(message, f"Error: {error}")
                    return
            if encoding == "url":
                try:
                    import urllib.parse

                    if decode:
                        text = urllib.parse.unquote(text)
                    if encode:
                        text = urllib.parse.quote(text)
                except Exception as error:
                    self.driver.reply_to(message, f"Error: {error}")
                    return
            self.driver.reply_to(message, f"Result:\n{text}")
