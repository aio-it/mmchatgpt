# baseclass for openai tools
# should be inherited by all tools to ensure a consistent interface
"""
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "download_webpage",
                    "description": "download a webpage to import as context and respond to the users query about the content and snippets from the webpage.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "the url for the webpage",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },{
                "type": "function",
                "function": {
                    "name": "web_search_and_download",
                    "description": "use this function if you think that it might be benificial with additional context to the conversation. This searches the web using duckduckgo and download the webpage to get the content and return the content always show the source for any statements made about the things downloaded.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "searchterm": {
                                "type": "string",
                                "description": "search term",
                            }
                        },
                        "required": ["searchterm"],
                    },
                },
            },{
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "search the web using duckduckgo and return the top 10 results",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "searchterm": {
                                "type": "string",
                                "description": "search term",
                            }
                        },
                        "required": ["searchterm"],
                    },
                },
            }
        ]
"""

class Tool:
    def __init__(self, name, description, parameters, privilege_level="user", tool_type="function"):
        self.validate_tool(name, description, parameters, privilege_level, tool_type)
        self.name = name
        self.description = description
        self.parameters = self.format_parameters(parameters)
        self.privilege_level = privilege_level
        self.type = tool_type

    def get_tool_info(self):
        return {
            "type": self.type,
            "function": {
                "name": self.name.__name__,
                "description": self.description,
                "parameters": self.parameters,
                "privilege_level": self.privilege_level,
            }
        }

    @staticmethod
    def from_object(obj):
        Tool.validate_tool(
            name=obj["function"]["name"],
            description=obj["function"]["description"],
            parameters=obj["function"]["parameters"],
            privilege_level=obj.get("privilege_level", "user"),
            tool_type=obj["type"]
        )
        return Tool(
            name=obj["function"]["name"],
            description=obj["function"]["description"],
            parameters=obj["function"]["parameters"],
            privilege_level=obj.get("privilege_level", "user"),
            tool_type=obj["type"]
        )

    @staticmethod
    def validate_tool(name, description, parameters, privilege_level, tool_type):
        if not callable(name):
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
    def __init__(self):
        self.tools = []
        self.disabled_tools = []

    def add_tool(self, tool: Tool):
        self.tools.append(tool.get_tool_info())
    def get_tool(self, function_name: str):
        for tool in self.tools:
            if tool["function"]["name"] == function_name:
                return tool
        return None
    def disable_tool(self, function_name: str) -> bool:
        for i, tool in enumerate(self.tools):
            if tool["function"]["name"] == function_name:
                self.disabled_tools.append(self.tools.pop(i))
                return True
        return False

    def enable_tool(self, function_name: str) -> bool:
        for i, tool in enumerate(self.disabled_tools):
            if tool["function"]["name"] == function_name:
                self.tools.append(self.disabled_tools.pop(i))
                return True
        return False

    def get_tools(self, privilege_level="user", include_disabled=False):
        if include_disabled:
            all_tools = self.tools + self.disabled_tools
            if privilege_level == "admin":
                return all_tools
            return [tool for tool in all_tools if tool["function"]["privilege_level"] == "user"]
        
        if privilege_level == "admin":
            return self.tools
        return [tool for tool in self.tools if tool["function"]["privilege_level"] == "user"]