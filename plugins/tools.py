"""baseclass for openai tools"""

# should be inherited by all tools to ensure a consistent interface
from typing import Literal

class Tool:
    """Tool function class used for ai tools"""

    def __init__(
        self,
        function,
        description,
        parameters,
        privilege_level="user",
        tool_type="function",
        needs_message_object=False,
        direct_message_only=False,
        channel_message_only=False,
        returns_files=True,
        needs_self=False,
    ):
        self.validate_tool(
            function, description, parameters, privilege_level, tool_type
        )
        # if the type of the function is a MessageFunction then we need to set the name to the name of the function from the MessageFunction.func attribute
        # this is because the MessageFunction class is a wrapper around the actual function and the actual function is stored in the func attribute of the MessageFunction class
        self.needs_self = needs_self
        if hasattr(function, "function"):
            self.name = function.function.__name__
            self.function = function.function
            self.needs_self = True
        else:
            self.name = function.__name__
            self.function = function
        self.description = description
        self.parameters = self.format_parameters(parameters)
        self.privilege_level = privilege_level
        self.type = tool_type
        self.needs_message_object = needs_message_object
        self.direct_message_only = direct_message_only
        self.channel_message_only = channel_message_only
        self.returns_files = returns_files

    def as_dict(self):
        """Return the tool as a dictionary so it can be serialized"""
        return {
            "type": self.type,
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "privilege_level": self.privilege_level,
            },
        }

    @staticmethod
    def validate_tool(
        function, description, parameters, privilege_level, tool_type
    ) -> None:
        """Validate the tool"""
        if not callable(function):
            raise ValueError("Tool name must be callable")
        if not isinstance(description, str) or not description:
            raise ValueError("Tool description must be a non-empty string")
        if not isinstance(parameters, list):
            raise ValueError("Tool parameters must be a list")
        if privilege_level not in ["user", "admin"]:
            raise ValueError("Privilege level must be 'user' or 'admin'")
        if tool_type not in ["function"]:
            raise ValueError("Tool type must be 'function'")

    @staticmethod
    def format_parameters(parameters):
        """Format parameters for the tool"""
        formatted_parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        for param in parameters:
            if isinstance(param, str):
                formatted_parameters["properties"][param] = {
                    "type": "string",
                    "description": param,
                }
                formatted_parameters["required"].append(param)
            elif isinstance(param, dict) and "name" in param:
                formatted_parameters["properties"][param["name"]] = {
                    "type": "string",
                    "description": param.get("description", param["name"]),
                }
                if param.get("required", True):
                    formatted_parameters["required"].append(param["name"])
        return formatted_parameters


class ToolsManager:
    """Manager class for tools that is a collection of tools"""

    def __init__(self) -> None:
        self.tools = {}
        self.disabled_tools = {}

    def add_tool(self, tool: Tool) -> Literal[True]:
        """Add a tool to the tools manager"""
        self.tools[tool.name] = tool
        return True

    def get_tool(self, tool: Tool) -> Tool | None:
        """Get a tool from the tools manager"""
        return self.tools.get(tool, None)

    def disable_tool(self, tool: Tool) -> bool:
        """Disable a tool from the tools manager"""
        if tool.name in self.tools:
            self.disabled_tools[tool.name] = self.tools.pop(tool.name)
            return True
        return False

    def enable_tool(self, function_name: str) -> bool:
        """Enable a tool from the tools manager"""
        if function_name in self.disabled_tools:
            self.tools[function_name] = self.disabled_tools.pop(function_name)
            return True
        return False

    def get_tools(self, privilege_level="user", include_disabled=False) -> dict[Tool]:
        """Get all tools from the tools manager based on privilege level and include_disabled"""
        if privilege_level == "user":
            # filter out all the tools that are admin only
            tools = self.tools
            if include_disabled:
                tools = {**tools, **self.disabled_tools}
            tools = {k: v for k, v in self.tools.items() if v.privilege_level == "user"}
            return tools
        # return all tools if privilege_level is admin
        if privilege_level == "admin":
            return self.tools
        # return all tools except disabled tools
        if not include_disabled:
            return self.tools
        # return all tools including disabled tools
        return {**self.tools, **self.disabled_tools}

    def get_tools_as_dict(self, privilege_level="user", include_disabled=False):
        """Return all tools as json so they can be sent to the ai client"""
        tools: dict[Tool] = self.get_tools(privilege_level, include_disabled)
        return [tool.as_dict() for tool in tools.values()]
