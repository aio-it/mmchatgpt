import json

import numpy as np
import psycopg
from environs import Env
from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from openai import AsyncOpenAI, OpenAI
from pgvector.psycopg import register_vector
from psycopg.sql import SQL, Identifier
from psycopg.rows import dict_row
from plugins.base import PluginLoader
from enum import Enum
env = Env()

aclient = AsyncOpenAI(api_key=env.str("OPENAI_API_KEY"))
client = OpenAI(api_key=env.str("OPENAI_API_KEY"))

class UsageContext(Enum):
    ANY = "any"
    DIRECT = "direct"
    CHANNEL = "channel"

class VectorDb(PluginLoader):
    """Vector Database Plugin."""
    VECTOR_DIMENSIONS = 1536
    EMBEDDING_MODEL = "text-embedding-3-small"
    DEFAULT_TABLE = "rag_content"
    FIELDS = [
        "id",
        "source_type",
        "source",
        "usage_context",
        "category",
        "tags",
        "content",
        "embedding",
        "metadata",
        "created_by",
        "created_at",
        "is_deleted"
    ]
    def __init__(self):
        super().__init__()
        # connect
        # TODO: change this to async. remember to create a new connection for each async call so move this to a jit connection function for each function that needs a connection
        self.conn = psycopg.connect(
            dbname=env.str("POSTGRES_DB","postgres"),
            user=env.str("POSTGRES_USER","postgres"),
            password=env.str("POSTGRES_PASSWORD"),
            host=env.str("POSTGRES_HOST","pg"),
            port=env.int("POSTGRES_PORT",5432),
            autocommit=True,
            row_factory=dict_row
        )
        # init pgvector
        self.conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
        self.conn.execute('ALTER EXTENSION vector SET SCHEMA public;')
        register_vector(self.conn)
        self.drop_table("memories")
        self.create_table(self.DEFAULT_TABLE)

    def initialize(self, driver: Driver, plugin_manager: PluginManager, settings: Settings):
        super().initialize(driver, plugin_manager, settings)

    def drop_table(self, table_name: str):
        """Drop a table."""
        self.conn.execute(f"DROP TABLE IF EXISTS {table_name}")

    def create_table(self, table_name: str, vector_dimensions: int | None = None):
        """Create a table."""
        if vector_dimensions is None:
            vector_dimensions = self.VECTOR_DIMENSIONS
        try:
            self.conn.execute("CREATE TYPE usage_context AS ENUM ('any', 'direct', 'channel');")
        except:
            pass
        q = f"""
CREATE TABLE IF NOT EXISTS {table_name} (
    id bigserial PRIMARY KEY,
    source_type varchar(32) NOT NULL, -- channel or user or system or other source type like webcrawler
    source varchar(64) NOT NULL, -- channelid, threadid, user id or other source name like url
    usage_context usage_context DEFAULT 'any',
    category varchar(64),
    tags jsonb, -- list of tags
    content text,
    embedding vector({vector_dimensions}),
    metadata jsonb, -- additional metadata
    created_by varchar(64), -- the user id who created the content
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    is_deleted boolean DEFAULT FALSE
);"""
        self.conn.execute(q)

    def tests(self):
        """Run tests."""
        # drop table if exists
        self.drop_table(self.DEFAULT_TABLE)
        # create table
        self.create_table(self.DEFAULT_TABLE)
        # store a memory
        self.store("rag_content", ["test"], "hello world")

    async def async_get_embeddings(self, input: str|list, model: str = None):
        """Get embeddings for a text."""
        if model is None:
            model = self.EMBEDDING_MODEL
        if isinstance(input, str):
            input = [input]
        embeddings_response = await aclient.embeddings.create(input=input, model=self.EMBEDDING_MODEL)
        embeddings = []
        for data in embeddings_response.data:
            embeddings.append(data.embedding)
        if len(embeddings) == 1:
            return embeddings[0]
        return embeddings

    def get_embeddings(self, input: str|list, model: str = None):
        """Get embeddings for a text."""
        if model is None:
            model = self.EMBEDDING_MODEL
        if isinstance(input, str):
            input = [input]
        embeddings_response = client.embeddings.create(input=input, model=self.EMBEDDING_MODEL)
        embeddings = []
        for data in embeddings_response.data:
            embeddings.append(data.embedding)
        if len(embeddings) == 1:
            return embeddings[0]
        return embeddings
    def store_multiple(self, table: str, contexts: list, tags: list, content: list):
        """Store multiple memories."""
        for item in content:
            self.store(table, contexts, tags, item)

    """
CREATE TABLE IF NOT EXISTS {table_name} (
    id bigserial PRIMARY KEY,
    source_type varchar(32) NOT NULL, -- channel or user or system or other source type like webcrawler
    source varchar(64) NOT NULL, -- channelid, threadid, user id or other source name like url
    usage_context usage_context DEFAULT 'any',
    category varchar(64),
    tags jsonb, -- list of tags
    content text,
    embedding vector({vector_dimensions}),
    metadata jsonb, -- additional metadata
    created_by varchar(64),
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    is_deleted boolean DEFAULT FALSE
);
"""
    def check_if_memory_exists(self, usage_context: UsageContext, content, user: str):
        """Check if a memory exists."""
        result = self.conn.execute(SQL("SELECT id FROM {} WHERE content = %s AND created_by = %s AND usage_context = %s").format(Identifier(self.DEFAULT_TABLE)), (content, user, usage_context.value.lower()))
        if len(result.fetchall()) > 0:
            return True
        return False
    def store_memory(self, usage_context: UsageContext, content, user: str):
        """Store a memory."""
        if self.check_if_memory_exists(usage_context, content, user):
            return False
        return self.store(self.DEFAULT_TABLE, user, "user", usage_context, "memory", ["memory", user], content, {}, user)
    def get_memories(self, query: str, usage_context: UsageContext, user: str, limit: int = 5):
        """Get a memory."""
        return self.search(self.DEFAULT_TABLE, query=query, usage_context=usage_context, category="memory", user=user, limit=limit)
    def get_all_memories_for_user_for_context(self, user: str, usage_context: UsageContext):
        """Get all memories for a user."""
        return self.conn.execute(SQL("SELECT id, created_at, tags, content FROM {} WHERE created_by = %s AND usage_context = %s").format(Identifier(self.DEFAULT_TABLE)), (user,usage_context.value.lower())).fetchall()

    def store(self, table: str, source_type: str, source: str, usage_context: UsageContext, category: str, tags: list, content: str, metadata: dict, created_by: str):
        """Store a memory."""
        # create table if not exists
        self.create_table(table)
        tags = json.dumps(tags)
        metadata = json.dumps(metadata)
        embedding = self.get_embeddings(content)
        result = self.conn.execute(SQL("""
            INSERT INTO {} (source_type, source, usage_context, category, tags, content, embedding, metadata, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """).format(Identifier(table)), (source_type, source, usage_context.value.lower(), category, tags, content, embedding, metadata, created_by))
        # verify
        if result:
            return True

    def search(self, table: str | None, query: str, user: str, usage_context: UsageContext, category: str, limit: int = 5, max_distance: float = 2.0):
        """Search for a memory."""
        if table is None:
            table = self.DEFAULT_TABLE
        embedding = self.get_embeddings(query)
        result = self.conn.execute(
            SQL("""SELECT id, tags, metadata, category, source, source_type, created_at, content, embedding <-> %s::vector as distance FROM {}
                WHERE
                    (embedding <-> %s::vector) < %s AND
                    (usage_context = %s OR usage_context = 'any')
                    AND (created_by = %s OR source_type = 'chat' AND source =  %s)
                ORDER BY distance, created_at LIMIT %s"""
            ).format(Identifier(table)), (embedding, embedding, max_distance, usage_context.value.lower(), user, user, limit))
        return result.fetchall()

    def get_all(self, table: str):
        """Get all memories."""
        result = self.conn.execute(SQL("SELECT id, tags, content FROM {}").format(Identifier(table)))
        return result.fetchall()

    def delete(self, table: str, id: int):
        """Delete a memory."""
        result = self.conn.execute(SQL("DELETE FROM {} WHERE id = %s").format(Identifier(table)), (id,))
        return result

    def add_tags(self, table: str, id: int, tags: list):
        """Add tags to a memory."""
        tags = json.dumps(tags)
        result = self.conn.execute(SQL("UPDATE {} SET tags = tags || %s WHERE id = %s").format(Identifier(table)), (tags, id))
        return result

    def remove_tags(self, table: str, id: int, tags: list):
        """Remove tags from a memory."""
        tags = json.dumps(tags)
        result = self.conn.execute(SQL("UPDATE {} SET tags = tags - %s WHERE id = %s").format(Identifier(table)), (tags, id))
        return result