# mmchatgpt

mmchatgpt is a Mattermost chatbot built with the mmpy_bot framework. It integrates multiple plugins to extend its functionality, and its primary entry point is bot.py.

## Features

mmchatgpt includes 18+ specialized plugins that extend its capabilities:

- **ChatGPT**: Primary AI interface with OpenAI's models, image generation, and tool integration
- **Anthropic**: Alternative AI interface using Claude models for diverse conversational styles
- **XAI**: X.AI Grok integration for creative and humorous AI interactions
- **Ollama**: Local AI model hosting for privacy and self-hosted deployments
- **Calc**: Mathematical calculations with advanced expression support via MathJS
- **Giphy**: GIF search and sharing integration
- **HIBP**: Security breach checking via Have I Been Pwned API
- **Jira**: Project management and issue tracking integration
- **NTP**: Network time protocol testing and synchronization diagnostics
- **Pushups**: Fitness tracking with gamification and leaderboards
- **TTS**: Text-to-speech conversion with multiple engine support
- **Shell Commands**: Secure network diagnostics and system administration tools
- **ValkeyTool**: Direct database key management for debugging and administration
- **Users**: Comprehensive user and permission management system
- **VectorDb**: Vector database integration for RAG (Retrieval-Augmented Generation)
- **IntervalsIcu**: Fitness and wellness tracking via Intervals.icu integration
- **LogManager**: Automated log cleanup and maintenance
- **Version**: Bot version and source information display

For detailed documentation including commands, configuration, and usage examples, see **[PLUGINS.md](PLUGINS.md)**.

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

## Documentation

- **README.md** (this file) - Overview, setup, and basic usage
- **[PLUGINS.md](PLUGINS.md)** - Comprehensive plugin documentation including:
  - All available commands with examples
  - Configuration requirements and environment variables
  - Permission levels and security considerations
  - Usage tips and troubleshooting notes

## Running the Bot

Start the bot with:

   python bot.py

Alternatively, use Docker with the provided Dockerfile and docker-compose files:

   docker-compose up

## Additional Resources

- **[PLUGINS.md](PLUGINS.md)** - Comprehensive plugin documentation with commands and configuration
- Mattermost API Documentation: https://api.mattermost.com/#tag/introduction
- mmpy-bot Documentation: https://mmpy-bot.readthedocs.io/en/latest/index.html
- OpenAI Python Client: https://github.com/openai/openai-python
- Additional References:
  - https://embl-bio-it.github.io/python-mattermost-autodriver/index.html
  - https://github.com/attzonko/mmpy_bot/tree/main
