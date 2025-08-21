# Plugin Documentation

This document provides comprehensive documentation for all plugins available in the mmchatgpt bot. Each plugin extends the bot's functionality with specific commands and features.

## Table of Contents

- [ChatGPT](#chatgpt)
- [Anthropic](#anthropic)
- [XAI (X.AI Grok)](#xai-xai-grok)
- [Ollama](#ollama)
- [Calc](#calc)
- [Giphy](#giphy)
- [HIBP (Have I Been Pwned)](#hibp-have-i-been-pwned)
- [Jira](#jira)
- [NTP (Network Time Protocol)](#ntp-network-time-protocol)
- [Pushups](#pushups)
- [ValkeyTool](#valkeytool)
- [ShellCmds](#shellcmds)
- [TTS (Text to Speech)](#tts-text-to-speech)
- [Users](#users)
- [Version](#version)
- [VectorDb](#vectordb)
- [IntervalsIcu](#intervalsicu)
- [LogManager](#logmanager)

---

## ChatGPT

**Purpose**: Primary AI conversational interface using OpenAI's ChatGPT models with advanced tool integration.

### Commands

#### User Commands
- **`.help`** - Display all available commands and usage information
- **`@{botname} <text>`** - Chat with ChatGPT (reply to a message for context)
- **`@gpt <text>`** - Chat with ChatGPT (alternative format)
- **`@gpt4 <text>`** - Chat with ChatGPT using GPT-4 model
- **`@gpt3 <text>`** - Chat with ChatGPT using GPT-3 model
- **`@gpt4.5 <text>`** - Chat with ChatGPT using GPT-4.5 model
- **`.vision <text>`** - Parse images with questions (attach image to message)
- **`.mkimg <text>`** - Generate HD images using DALL-E3
- **`.img <text>`** - Generate images using DALL-E3 (alternative format)
- **`.ming <text>`** - Generate images using DALL-E3 (alternative format)
- **`.mkstdimg <text>`** - Generate standard quality images using DALL-E3
- **`.drtts <text>`** - Text-to-speech using DR TTS service
- **`.tts <text>`** - Text-to-speech using pyttsx3
- **`.pushups`** - Access pushups functionality
- **`.gif <text>`** - Search and post GIFs using GIPHY
- **`.decode <encoding> <text>`** - Decode text using specified encoding
- **`.encode <encoding> <text>`** - Encode text using specified encoding
- **`.docker help`** - Docker command help

#### Admin Commands
- **`.gpt get [<setting>]`** - Get ChatGPT configuration setting(s)
- **`.gpt set <setting> <value>`** - Set ChatGPT configuration setting
- **`.gpt reset <setting>`** - Reset ChatGPT setting to default
- **`.gpt model get`** - Get current ChatGPT model
- **`.gpt model set <model>`** - Set ChatGPT model
- **`.gpt model available`** - List available ChatGPT models
- **`.gpt debugchat`** - Debug conversation context
- **`.gpt set channel system <message>`** - Set channel-specific system message
- **`.gpt get channel system`** - Get channel-specific system message
- **`.gpt clear channel system`** - Clear channel-specific system message
- **`.gpt memories get`** - Get stored memories
- **`.gpt memories search <query>`** - Search memories
- **`.gpt memories save <text>`** - Save memory
- **`.gpt memories enable/disable <context>`** - Enable/disable memories for context (any/channel/direct)
- **`.users list/add/remove [<username>]`** - Manage authorized users
- **`.admins list/add/remove [<username>]`** - Manage administrators
- **`.eval <code>`** - Execute Python code and return results
- **`.exec <code>`** - Execute Python code and return results
- **`.s2t <text>`** - Convert text to tokens (debugging)
- **`.shell <command>`** - Execute shell commands
- **`.valkey search <key>`** - Search Valkey/Redis keys
- **`.valkey get <key>`** - Get Valkey/Redis key value
- **`.valkey set <key> <value>`** - Set Valkey/Redis key value
- **`.valkey del <key>`** - Delete Valkey/Redis key
- **`.ban <username> [<days>]`** - Ban user (permanent or temporary)
- **`.unban <username>`** - Unban user
- **`.banlist`** - List banned users

### Configuration

#### Environment Variables
- **`OPENAI_API_KEY`** - Required. OpenAI API key for ChatGPT access

#### Settings (configurable via commands)
- **`temperature`** - Response creativity (0.0-2.0)
- **`system`** - System message/persona
- **`model`** - ChatGPT model to use
- **`max_tokens`** - Maximum response length
- **`stream`** - Enable/disable streaming responses
- **`moderation`** - Enable content moderation

### Permissions
- Basic chat functionality: Requires user permission
- Image generation, TTS: Requires user permission  
- Admin commands: Requires admin permission
- Shell execution, code evaluation: Admin only

### Notes
- Supports thread context when replying to messages
- Built-in tools: web search, image generation, file operations, Docker execution
- Rate limiting applied to prevent abuse
- Conversation history stored temporarily in Valkey/Redis

---

## Anthropic

**Purpose**: Alternative AI conversational interface using Anthropic's Claude models.

### Commands

#### User Commands
- **`@claude <text>`** - Chat with Claude
- **`@sonnet <text>`** - Chat with Claude (Sonnet model)
- **`@s <text>`** - Chat with Claude (short alias)

#### Admin Commands
- **`.ant help`** - Display Anthropic plugin help
- **`.ant model get`** - Get current Claude model
- **`.ant model set <model>`** - Set Claude model
- **`.ant model available`** - List available models
- **`.ant get [<setting>]`** - Get configuration setting(s)
- **`.ant set <setting> <value>`** - Set configuration setting
- **`.ant reset <setting>`** - Reset setting to default
- **`.ant debugchat`** - Debug conversation context

### Configuration

#### Environment Variables
- **`ANTHROPIC_API_KEY`** - Required. Anthropic API key for Claude access

#### Available Models
- `claude-3-7-sonnet-20250219` (default)

#### Settings
- **`temperature`** - Response creativity (default: 1.0)
- **`system`** - System message (default: "You're a helpful assistant.")
- **`top_p`** - Nucleus sampling parameter (default: 1.0)
- **`moderation`** - Content moderation (default: false)
- **`stream`** - Streaming responses (default: true)
- **`stream_update_delay_ms`** - Stream update delay (default: 200ms)

### Permissions
- Basic chat: Requires user permission
- Configuration commands: Admin only

### Notes
- Supports streaming responses for real-time interaction
- Conversation context maintained per thread
- Models automatically fetched from Anthropic API on startup
- Thread history stored with 7-day expiry

---

## XAI (X.AI Grok)

**Purpose**: AI conversational interface using X.AI's Grok models for diverse and creative interactions.

### Commands

#### User Commands
- **`@grok <text>`** - Chat with Grok
- **`@xai <text>`** - Chat with Grok (alternative format)

#### Admin Commands
- **`.ant model get`** - Get current Grok model
- **`.ant model set <model>`** - Set Grok model
- **`.ant model available`** - List available models
- **`.ant get [<setting>]`** - Get configuration setting(s)
- **`.ant set <setting> <value>`** - Set configuration setting
- **`.ant reset <setting>`** - Reset setting to default
- **`.ant help`** - Display XAI plugin help
- **`.ant debugchat`** - Debug conversation context

### Configuration

#### Environment Variables
- **`XAI_API_KEY`** - Required. X.AI API key for Grok access

#### Available Models
- `grok-2-latest` (default)

#### Settings
- **`temperature`** - Response creativity (default: 1.0)
- **`system`** - System message (default: "You're a helpful assistant.")
- **`top_p`** - Nucleus sampling parameter (default: 1.0)
- **`moderation`** - Content moderation (default: false)
- **`stream`** - Streaming responses (default: true)
- **`stream_update_delay_ms`** - Stream update delay (default: 200ms)

### Permissions
- Basic chat: Requires user permission
- Configuration commands: Admin only

### Notes
- Similar functionality to Anthropic plugin but uses X.AI's Grok models
- Known for more creative and humorous responses
- Supports streaming responses for real-time interaction
- Thread history stored with 7-day expiry
- Configuration commands share namespace with Anthropic (`.ant`)

---

## Ollama

**Purpose**: Local AI model integration using Ollama for self-hosted language models.

### Commands

#### Configuration Commands (Admin Only)
- **`.ollama help`** - Display Ollama plugin help
- **`.ollama model list`** - List available local models
- **`.ollama model pull <model>`** - Download/pull a model
- **`.ollama model show <model>`** - Show model information
- **`.ollama stream enable`** - Enable streaming responses
- **`.ollama stream disable`** - Disable streaming responses
- **`.ollama stream delay set <milliseconds>`** - Set stream delay

### Configuration

#### Environment Variables
- **`OLLAMA_URL`** - Ollama server URL (default: "http://localhost:11434/api")

#### Default Settings
- **Model**: mistral (default)
- **Streaming**: enabled
- **Stream delay**: 100ms

### Permissions
- **All commands**: Admin only (model management is high-privilege)

### Features
- **Local model hosting**: Run AI models on your own infrastructure
- **Model management**: Download and manage different models
- **Streaming support**: Real-time response streaming
- **Configurable endpoints**: Support for remote Ollama instances

### Notes
- Requires Ollama server running locally or remotely
- Models must be pulled/downloaded before use
- Useful for privacy-sensitive environments
- Lower latency when running locally
- No external API dependencies once models are downloaded

---

## Calc

**Purpose**: Mathematical calculations using the MathJS API with support for complex expressions.

### Commands
- **`.calc`** - Display calculator help and syntax information
- **`.calc <expression>`** - Calculate mathematical expression

### Examples
```
.calc 2+2
.calc sqrt(16) + 5
.calc sin(pi/2)
.calc matrix([[1,2],[3,4]]) * 2
```

### Configuration

#### Environment Variables
None required.

#### External Dependencies
- MathJS API (https://api.mathjs.org/v4/)

### Permissions
- Requires user permission

### Features
- **Rate limiting**: 1 request per 5 seconds per user
- **Syntax**: Full MathJS expression syntax supported
- **Newline handling**: Newlines converted to semicolons for multi-line expressions

### Notes
- Supports advanced mathematical functions, matrices, units, and expressions
- See [MathJS syntax documentation](https://mathjs.org/docs/expressions/syntax.html) for full capabilities
- Visual feedback with abacus emoji during calculation

---

## Giphy

**Purpose**: Search and share GIF images using the GIPHY API.

### Commands
- **`.gif <search_terms>`** - Search for and post a GIF

### Examples
```
.gif happy cat
.gif excited dancing
.gif monday morning
```

### Configuration

#### Environment Variables
- **`GIPHY_API_KEY`** - Required. GIPHY API key for GIF search

### Permissions
- Requires user permission

### Features
- **Rate limiting**: 1 request per 5 seconds per user
- **Content filtering**: Only G-rated content
- **Language**: English search results
- **Results**: Returns single best match

### Notes
- If API key not configured, plugin will be disabled
- Visual feedback with picture frame emoji during search
- Automatic link formatting for Mattermost

---

## HIBP (Have I Been Pwned)

**Purpose**: Check if email addresses or passwords have been compromised in data breaches.

### Commands
- **`.hibp <email_or_password>`** - Check for breaches
- **`.haveibeenpwned <email_or_password>`** - Alternative command format

### Examples
```
.hibp user@example.com
.hibp mypassword123
```

### Configuration

#### Environment Variables
- **`HIBP_API_KEY`** - Required. Have I Been Pwned API key

### Permissions
- Requires user permission

### Features
- **Email breach checking**: Shows all breaches for an email address
- **Password checking**: Verifies if password appears in breach databases
- **Markdown formatting**: Converts HTML links to Mattermost markdown
- **Comprehensive reporting**: Details about each breach including date and description

### Notes
- Plugin disabled if API key not configured
- Results include breach names, dates, and descriptions
- Password checking uses secure k-anonymity model
- Links automatically formatted for Mattermost display

---

## Jira

**Purpose**: Interact with Jira for issue tracking, project management, and workflow operations.

### Commands
- **`.jira help`** - Display Jira plugin help
- **`.jira login`** - Interactive Jira login
- **`.jira login <server> <username> <token>`** - Direct login with credentials
- **`.jira logout`** - Logout from Jira
- **`.jira assigned`** - List issues assigned to you

### Configuration

#### Environment Variables
None required (credentials stored per user in Valkey/Redis).

#### Authentication
- **Server URL**: Your Jira instance URL
- **Username**: Jira username/email
- **Token**: Jira API token (not password)

### Permissions
- Requires user permission

### Features
- **Per-user authentication**: Individual Jira credentials stored securely
- **Session management**: Persistent login sessions
- **Issue filtering**: Filter by status, assignee, reporter, issue type
- **Flexible queries**: Support for custom JQL (Jira Query Language)

### Notes
- Credentials stored encrypted in Valkey/Redis
- Supports both interactive and direct login methods
- Session automatically manages authentication state
- Use Jira API tokens, not passwords, for security

---

## NTP (Network Time Protocol)

**Purpose**: Network time synchronization testing and time server analysis.

### Commands
- **`.ntptest <server>`** - Test NTP server response and accuracy
- **`.ntpcompare <server1> <server2>`** - Compare two NTP servers
- **`.ntplookup <hostname>`** - Lookup NTP servers for hostname/pool
- **`.ntpoffsethelper <server> <offset> <tolerance>`** - Check if server offset is within tolerance

### Examples
```
.ntptest pool.ntp.org
.ntpcompare time.google.com time.cloudflare.com
.ntplookup ubuntu.pool.ntp.org
.ntpoffsethelper time.nist.gov 0.1 0.5
```

### Configuration

#### Environment Variables
None required.

### Permissions
- Requires user permission

### Features
- **Automatic formatting**: Displays time differences in appropriate units (ns, μs, ms, s)
- **Multiple server support**: Query multiple servers from hostname pools
- **Comprehensive metrics**: Offset, delay, dispersion, and stratum information
- **Error handling**: Graceful handling of unreachable servers

### Notes
- Automatically selects appropriate time unit for display
- Supports both individual servers and NTP pools
- Provides detailed timing information for network diagnostics
- Useful for diagnosing time synchronization issues

---

## Pushups

**Purpose**: Track pushup exercises with daily and total counters, leaderboards, and anti-cheating measures.

### Commands
- **`.pushups`** - Display help and current stats
- **`.pushups help`** - Show detailed help
- **`.pushups <number>`** - Add pushups to your count
- **`.pushups add <number>`** - Alternative add format
- **`.pushups sub <number>`** - Subtract pushups (corrections)
- **`.pushups score`** - Show your current scores
- **`.pushups scores`** - Show your current scores
- **`.pushups top<number>`** - Show top N users leaderboard (e.g., `.pushups top5`, `.pushups top10`)
- **`.pushups reset`** - Reset your own stats (admin: reset others)

### Examples
```
.pushups 25
.pushups add 10
.pushups sub 5
.pushups top10
.pushups reset
```

### Configuration

#### Environment Variables
None required.

### Permissions
- Basic tracking: Requires user permission
- Reset others: Admin only

### Features
- **Daily tracking**: Separate counters for daily and total pushups
- **Anti-cheating**: 
  - Maximum 1000 pushups per entry
  - 6-hour ban for excessive claims
  - Automatic validation with fun responses
- **Leaderboards**: Flexible top-N user rankings
- **Persistence**: Data stored in Valkey/Redis with user identification

### Notes
- Daily counters reset automatically each day
- Total counters persist indefinitely
- Humorous anti-cheat responses with GIFs
- Supports both positive and negative adjustments
- Admin can reset any user's stats

---

## ValkeyTool

**Purpose**: Direct manipulation and inspection of Valkey/Redis database keys and values.

### Commands
- **`.valkey get <key>`** - Retrieve value of a key
- **`.valkey set <key> <value>`** - Set key to value
- **`.valkey search <pattern>`** - Search for keys matching pattern
- **`.valkey delete <key>`** - Delete a key

### Examples
```
.valkey get user:settings
.valkey set config:debug true
.valkey search user:*
.valkey delete temp:data
```

### Configuration

#### Environment Variables
- Uses bot's existing Valkey/Redis connection configuration

### Permissions
- **All commands**: Admin only (high-privilege operations)

### Features
- **Multi-type support**: Handles strings, lists, sets, sorted sets, and hashes
- **Pattern searching**: Wildcard and pattern-based key discovery
- **Type detection**: Automatically determines and displays key types
- **Comprehensive display**: Shows key names, types, and values

### Notes
- **SECURITY**: Admin-only due to potential access to sensitive data
- Supports all Redis/Valkey data types
- Pattern search uses Redis KEYS command (use carefully in production)
- Displays key types for easier database management

---

## ShellCmds

**Purpose**: Execute shell commands and network diagnostics with built-in security validation.

### Commands

#### General Commands
- **`.shell <command>`** - Execute shell command (admin only)
- **`.exec <command>`** - Execute shell command (admin only)  
- **`.eval <code>`** - Execute Python code (admin only)
- **`!<command>`** - Execute predefined shell command
- **`.restart`** - Restart the bot (admin only)

#### Encoding/Decoding
- **`.decode <encoding> <text>`** - Decode text using specified encoding
- **`.encode <encoding> <text>`** - Encode text using specified encoding

#### Network Diagnostics (via `!` prefix)
- **`!ping <host>`** - Ping IPv4 host
- **`!ping6 <host>`** - Ping IPv6 host  
- **`!dig <domain>`** - DNS lookup
- **`!traceroute <host>`** - Trace route to host
- **`!nmap <host> [options]`** - Network port scan
- **`!tcpportcheck <host> <port>`** - Check specific TCP port

### Examples
```
.encode base64 "Hello World"
.decode url "Hello%20World"
!ping google.com
!dig example.com
!nmap -sS example.com
```

### Configuration

#### Environment Variables
None required.

### Permissions
- **Shell/exec/eval**: Admin only
- **Network diagnostics**: User permission
- **Encoding/decoding**: User permission

### Features
- **Input validation**: Strict validation for network commands
- **Allowed arguments**: Predefined safe arguments for network tools
- **Domain/IP validation**: Validates targets before execution
- **Security filtering**: Prevents command injection

#### Supported Network Commands
- **ping/ping6**: IPv4/IPv6 connectivity testing
- **dig**: DNS record lookups (A, MX, NS, SOA, TXT)
- **traceroute/traceroute6**: Network path tracing
- **nmap**: Port scanning with restricted options
- **tcpportcheck**: TCP port connectivity testing

### Notes
- **SECURITY**: Shell access is admin-only for security
- Network commands use strict input validation
- Encoding supports: base64, url, html, various character encodings
- All network tools have predefined safe argument lists

---

## TTS (Text to Speech)

**Purpose**: Convert text to speech audio files using multiple TTS engines.

### Commands
- **`.drtts <text>`** - Generate speech using DR TTS service
- ~~**`.tts <text>`**~~ - Alternative TTS using pyttsx3 (currently disabled)

### Examples
```
.drtts Hello world, how are you today?
.drtts This is a test of the text to speech functionality
```

### Configuration

#### Environment Variables
None required (uses external DR TTS service).

### Permissions
- Requires user permission

### Features
- **Rate limiting**: 1 request per 5 seconds per user
- **File delivery**: Returns audio file attachment
- **Format**: MP3 audio format
- **Language**: Danish TTS service
- **Cleanup**: Automatic temporary file cleanup

### Notes
- Uses DR (Danish Radio) TTS service
- Visual feedback with speaking head emoji during processing
- Returns both download link and file attachment
- Newlines automatically converted to spaces
- Files automatically deleted after sending

---

## Users

**Purpose**: Manage user permissions and administrative access for the bot.

### Commands

#### User Management
- **`.users list`** - List all authorized users (admin only)
- **`.users add <username>`** - Add user to authorized list (admin only)
- **`.users remove <username>`** - Remove user from authorized list (admin only)

#### Admin Management  
- **`.admins list`** - List all administrators (admin only)
- **`.admins add <username>`** - Add user as administrator (admin only)
- **`.admins remove <username>`** - Remove administrator privileges (admin only)

#### User Information
- **`.uid <username>`** - Get user ID for username
- **`.banlist`** - List banned users (admin only)
- **`.ban <username> [<days>]`** - Ban user temporarily or permanently (admin only)
- **`.unban <username>`** - Remove user ban (admin only)

### Examples
```
.users add john.doe
.admins add jane.smith
.uid john.doe
.ban spammer 7
.unban reformed.user
```

### Configuration

#### Environment Variables
None required (uses bot's user database).

### Permissions
- **All commands**: Admin only (user management is high-privilege)

### Features
- **Dual permission system**: Users (basic access) and Admins (full access)
- **Temporary bans**: Support for time-limited bans
- **User ID mapping**: Convert between usernames and internal IDs
- **Persistent storage**: User lists stored in Valkey/Redis

### Notes
- **CRITICAL**: Only admins can modify user/admin lists
- User validation ensures users exist before adding
- Displays both usernames and internal IDs for reference
- Ban system integrates with other plugin permission checks

---

## Version

**Purpose**: Display bot version information and source repository details.

### Commands
- **`.gpt version`** - Display current bot version and source information

### Examples
```
.gpt version
```

### Configuration

#### Environment Variables
None required.

### Features
- **Git integration**: Shows git tag version if available
- **Fallback versioning**: Uses version file if git unavailable
- **Source information**: Displays GitHub repository URL

### Permissions
- Available to all users (public information)

### Notes
- Version determined by git tags (`git describe --tags`) when available
- Falls back to `version` file content if git not available
- Shows GitHub source repository for transparency
- Version information logged on bot startup

---

## VectorDb

**Purpose**: Vector database operations for RAG (Retrieval-Augmented Generation) content management and semantic search.

### Commands
- **Vector database operations** - Commands not directly exposed to users
- Integration with ChatGPT for enhanced contextual responses

### Configuration

#### Environment Variables
- **`OPENAI_API_KEY`** - Required. OpenAI API key for embeddings
- **`POSTGRES_DB`** - PostgreSQL database name (default: "postgres")
- **`POSTGRES_USER`** - PostgreSQL username (default: "postgres")  
- **`POSTGRES_PASSWORD`** - Required. PostgreSQL password
- **`POSTGRES_HOST`** - PostgreSQL host (default: "pg")

#### Database Schema
- **Table**: `rag_content` (default)
- **Vector dimensions**: 1536 (text-embedding-3-small)
- **Fields**: id, source_type, source, usage_context, category, tags, content, embedding, metadata, created_by, created_at, is_deleted

### Permissions
- Internal plugin (no direct user commands)
- Integration permissions inherit from calling plugins

### Features
- **Semantic search**: Vector similarity search for content retrieval
- **Embedding generation**: Automatic text embedding using OpenAI
- **Content categorization**: Organized storage with tags and categories
- **Usage contexts**: Support for different usage scenarios (direct, channel, any)
- **Soft deletion**: Content marked as deleted rather than removed

### Notes
- Requires PostgreSQL with pgvector extension
- Uses OpenAI's text-embedding-3-small model
- Designed for integration with ChatGPT plugin
- Supports contextual content retrieval for improved AI responses

---

## IntervalsIcu

**Purpose**: Integration with Intervals.icu for fitness tracking, activity management, and wellness data.

### Commands

The plugin uses a dynamic command system with `.intervals` prefix. Commands are organized by category:

#### Authentication
- **`.intervals login <api_key>`** - Login with Intervals.icu API key
- **`.intervals logout`** - Logout and remove credentials

#### Privacy Settings  
- **`.intervals opt in`** - Enable public data usage
- **`.intervals opt out`** - Disable public data usage

#### Activity & Wellness Management
- **`.intervals activities`** - List recent activities
- **`.intervals wellness`** - Show wellness data
- **`.intervals refresh`** - Refresh cached data

#### Metrics
- **`.intervals <metric> <period>`** - Get metric data for time period
- Available metrics: distance, duration, calories, steps, count, weight
- Period format: `<number><unit>` (e.g., 7d, 4w, 2m, 1y)

#### Profile Management
- **`.intervals profile set <key> <value>`** - Set profile information
- **`.intervals profile get`** - Get current profile

#### Leaderboards
- **`.intervals leaderboards`** - View metric leaderboards

#### Help
- **`.intervals help`** - Show detailed command help

### Examples
```
.intervals login your-api-key-here
.intervals distance 7d
.intervals wellness
.intervals profile set height 175
.intervals leaderboards
```

### Configuration

#### Environment Variables
None required (API keys stored per user).

#### Required API Access
- **Intervals.icu API key** - Required for each user
- Available from Intervals.icu settings page

### Permissions
- Requires user permission
- Each user manages their own API credentials

### Features
- **Personal data management**: Individual API key storage per user
- **Activity tracking**: Comprehensive activity and wellness data
- **Metric analysis**: Time-based metric queries with flexible periods
- **Privacy controls**: Opt-in/opt-out for public data usage
- **Leaderboards**: Community fitness comparisons
- **Data caching**: Efficient data storage and refresh mechanisms
- **Rich formatting**: Detailed activity and wellness displays

### Notes
- Requires individual Intervals.icu accounts and API keys
- Data privacy controlled per user
- Supports comprehensive fitness and wellness tracking
- Metric periods support days (d), weeks (w), months (m), years (y)
- Command structure dynamically generated from decorated methods

---

## LogManager

**Purpose**: Automated log management and channel cleanup for bot operational logs.

### Commands
No direct user commands (automated background service).

### Configuration

#### Environment Variables
- Uses bot's log channel configuration
- **`MM_BOT_LOG_CHANNEL`** - Channel for bot logs

#### Settings
- **Retention period**: Keeps last 1000 log messages
- **Cleanup frequency**: Every 5 minutes
- **Batch processing**: 200 messages per API request

### Permissions
- Internal service (no user interaction required)

### Features
- **Automatic cleanup**: Removes old log messages to prevent channel overflow
- **Configurable retention**: Maintains specified number of recent messages
- **Scheduled execution**: Regular cleanup intervals
- **Rate limiting**: Controlled API request frequency
- **Safety mechanisms**: Prevents excessive deletion

### Notes
- **Background service**: Runs automatically without user intervention
- Only operates if bot is configured to log to a channel
- Preserves recent log history while managing storage
- Designed to prevent log channels from growing indefinitely
- Logs its own activity for transparency

---

## General Notes

### Permission System
- **User**: Basic bot access, can use most commands
- **Admin**: Full access including configuration and user management
- **Public**: Some commands available to all users (like version info)

### Rate Limiting
Many plugins implement rate limiting to prevent abuse:
- Typically 1 request per 5 seconds per user
- Applied to API-dependent features (GIPHY, Calc, TTS, etc.)

### Data Storage
- **Valkey/Redis**: Used for caching, settings, user data, and temporary storage
- **PostgreSQL**: Used for vector database operations
- **Persistent data**: User permissions, settings, and long-term data
- **Temporary data**: Conversation history, cached API responses

### Security Features
- **Input validation**: All commands validate input parameters
- **Command filtering**: Network and shell commands use allowlists
- **Permission checks**: All sensitive operations require appropriate permissions
- **API key management**: External service credentials properly managed

### Environment Setup
Most plugins require specific environment variables for external services. Ensure all required API keys and configuration values are properly set in your environment or `.env` file.

### Integration
Plugins are designed to work together:
- ChatGPT integrates with TTS, GIPHY, image generation, and vector database
- User management affects all plugins requiring permissions
- ValkeyTool provides debugging access to shared data storage
- LogManager keeps operational logs manageable

For additional technical details, refer to the individual plugin source files in the `plugins/` directory.