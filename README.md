# mmchatgpt

mmchatgpt is a Mattermost chatbot built with the mmpy_bot framework. It integrates multiple plugins to extend its functionality, and its primary entry point is bot.py.

## Features

- ChatGPT: Leverage OpenAI's ChatGPT for conversational responses.
- Anthropic: Communicate using Anthropic's API for generating responses.
- Calculation: Perform mathematical operations directly through chat commands.
- Giphy: Search and send GIF images.
- HIPB: Check for compromised accounts via Have I Been Pwned integration.
- Jira: Interact with Jira for issue tracking and management.
- NTP: Provide network time protocol services.
- Pushups: Fun commands for pushup reminders.
- TTS: Convert text to speech for audio responses.
- Shell Commands: Execute shell commands remotely as needed.
- ValkeyTool: Validate keys and manage secure tokens.
- Users: Manage user information and permissions.
- VectorDb: Interface with vector databases as part of data queries.
- IntervalsIcu: Handle interval-based tasks and scheduling.
- Log Manager: Manage and review bot logs for debugging.
- Version: Display the current bot version from the version file.

## Setup

1. Install the dependencies using pip or Pipenv:
   pip install -r requirements.txt

2. Set the necessary environment variables in your environment or a .env file. Key variables include:
   - MM_URL: Mattermost server URL
   - MM_PORT: Mattermost port (default is 443)
   - MM_API_PATH: API path (typically "/api/v4")
   - MM_BOT_TOKEN: Bot authentication token
   - MM_BOT_TEAM: Mattermost team identifier
   - MM_BOT_LOG_CHANNEL: Channel for logging events
   - DEBUG: Set to true to enable debug logging (optional)

3. Ensure the version file contains the current version of the bot.

## Running the Bot

Start the bot with:

   python bot.py

Alternatively, use Docker with the provided Dockerfile and docker-compose files:

   docker-compose up

## Additional Resources

- Mattermost API Documentation: https://api.mattermost.com/#tag/introduction
- mmpy-bot Documentation: https://mmpy-bot.readthedocs.io/en/latest/index.html
- OpenAI Python Client: https://github.com/openai/openai-python
- Additional References:
  - https://embl-bio-it.github.io/python-mattermost-autodriver/index.html
  - https://github.com/attzonko/mmpy_bot/tree/main
