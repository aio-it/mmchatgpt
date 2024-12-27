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
    DEFAULT_DISTANCE = 1.5
    DEFAULT_MAX_SIMILARITY = 0.8
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
    def user_has_memories(self, user: str, usage_context: UsageContext, source_type: str, source: str):
        """Check if a user has memories."""
        result = self.conn.execute(SQL("SELECT id FROM {} WHERE created_by = %s AND usage_context = %s AND source_type = %s AND source = %s AND is_deleted is FALSE").format(Identifier(self.DEFAULT_TABLE)), (user, usage_context.value.lower(), source_type, source))
        if len(result.fetchall()) > 0:
            return True
        return False
    def check_if_memory_exists(self, usage_context: UsageContext, content, user: str, source_type: str, source: str):
        """Check if a memory exists."""
        result = self.conn.execute(SQL("SELECT id FROM {} WHERE content = %s AND created_by = %s AND usage_context = %s AND source_type = %s and source = %s AND is_deleted = FALSE").format(Identifier(self.DEFAULT_TABLE)), (content, user, usage_context.value.lower(), source_type, source))
        if len(result.fetchall()) > 0:
            return True
        return False
    def store_memory(self, usage_context: UsageContext, content, user: str, source_type: str, source: str, tags: list | None):
        """Store a memory."""
        if tags is None:
            tags = []
        if self.check_if_memory_exists(usage_context, content, user, source_type, source):
            return False
        memory_tags = ["memory", user] + tags
        return self.store(self.DEFAULT_TABLE, source_type, source, usage_context, "memory", memory_tags, content, {}, user)
    def get_memories(self, query: str, usage_context: UsageContext, user: str, source_type:str, source:str, limit: int = 5):
        """Get a memory."""
        return self.search(self.DEFAULT_TABLE, query=query, usage_context=usage_context, category="memory", user=user, source_type=source_type, source=source, limit=limit)
    def get_all_memories_for_user_for_context(self, user: str, usage_context: UsageContext, source_type: str, source: str):
        """Get all memories for a user."""
        return self.conn.execute(SQL("SELECT id, created_at, tags, content FROM {} WHERE created_by = %s AND usage_context = %s AND source_type = %s AND source = %s AND is_deleted = FALSE").format(Identifier(self.DEFAULT_TABLE)), (user,usage_context.value.lower(), source_type, source)).fetchall()
    def user_delete_memory_by_id(self, memory_id: int, user: str, usage_context: UsageContext, source_type: str, source: str):
        """Delete a memory."""
        result = self.conn.execute(SQL("UPDATE {} SET is_deleted = TRUE WHERE id = %s AND created_by = %s AND usage_context = %s AND source_type = %s AND source = %s").format(Identifier(self.DEFAULT_TABLE)), (memory_id, user, usage_context.value.lower(), source_type, source))
        return result
    def user_delete_all_memories_in_context(self, user: str, usage_context: UsageContext, source_type: str, source: str):
        """Delete all memories for a user in a context."""
        result = self.conn.execute(SQL("UPDATE {} SET is_deleted = TRUE WHERE created_by = %s AND usage_context = %s AND source_type = %s AND source = %s").format(Identifier(self.DEFAULT_TABLE)), (user, usage_context.value.lower(), source_type, source))
        return result
    def user_delete_all_memories(self, user: str):
        """Delete all memories for a user."""
        result = self.conn.execute(SQL("UPDATE {} SET is_deleted = TRUE WHERE created_by = %s").format(Identifier(self.DEFAULT_TABLE)), (user,))
        return result
    def store_shared_memory(self, content, user: str, source_type: str, source: str, tags: list = [], metadata: dict = {}):
        """Store a shared memory."""
        shared_tags = ["shared", user] + tags
        return self.store(self.DEFAULT_TABLE, source_type, source, UsageContext.ANY, "shared", shared_tags, content, metadata, user)

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
    # TODO: think this through. should we limited this on created_by as well so it's only shared/global for the user?
    # this requires a rework of the delete functions as well
    def search_shared(self, table: str | None, query: str, limit: int = 5, max_similarity: float | None= None):
        """Search for a shared memory."""
        if table is None:
            table = self.DEFAULT_TABLE
        if max_similarity is None:
            max_similarity = self.DEFAULT_MAX_SIMILARITY
        embedding = self.get_embeddings(query)
        result = self.conn.execute(
            SQL("""SELECT id, tags, metadata, category, source, source_type, created_at, created_by, content, embedding <-> %s::vector as distance FROM {}
                WHERE
                    is_deleted = FALSE AND
                    (embedding <-> %s::vector) < %s AND
                    usage_context = %s
                ORDER BY distance, created_at LIMIT %s"""
            ).format(Identifier(table)), (embedding, embedding, max_similarity, UsageContext.ANY.value.lower(), limit))
        return result.fetchall()

    def search(self, table: str | None, query: str, user: str, usage_context: UsageContext, category: str, source_type:str, source:str, limit: int = 5, max_similarity: float | None = None):
        """Search for a memory."""
        if table is None:
            table = self.DEFAULT_TABLE
        if max_similarity is None:
            max_similarity = self.DEFAULT_MAX_SIMILARITY
        embedding = self.get_embeddings(query)
        result = self.conn.execute(
            SQL("""SELECT id, tags, metadata, category, source, source_type, created_at, content, embedding <=> %s::vector as distance FROM {}
                WHERE
                    is_deleted = FALSE AND
                    (embedding <=> %s::vector) < %s AND
                    usage_context = %s AND
                    created_by = %s AND
                    source_type = %s AND
                    source = %s
                ORDER BY distance, created_at LIMIT %s"""
            ).format(Identifier(table)), (embedding, embedding, max_similarity, usage_context.value.lower(), user, source_type, source, limit))
        return result.fetchall()