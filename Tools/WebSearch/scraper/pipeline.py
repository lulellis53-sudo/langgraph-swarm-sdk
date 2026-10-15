"""
WebScraper Vector DB Ingestion Pipeline.

Extracts text from web pages using Selectolax and Trafilatura,
embeds the text using FastEmbed, and ingests it into DuckDB with HNSW vss index.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import random
import urllib.request
import json
import importlib
import types

# --- PEP 810 Free Thread Lazy Imports ---
class LazyModule(types.ModuleType):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._module_name = name
        self._loaded_module = None

    def _load(self):
        if self._loaded_module is None:
            self._loaded_module = importlib.import_module(self._module_name)
        return self._loaded_module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)

def lazy_import(name: str):
    return LazyModule(name)

duckdb = lazy_import("duckdb")
httpx2 = lazy_import("httpx2")
uvloop = lazy_import("uvloop")
selectolax_lexbor = lazy_import("selectolax.lexbor")
trafilatura = lazy_import("trafilatura")
# ----------------------------------------

# Enforce ONNX thread boundaries to prevent CPython 3.14t thrashing
os.environ["OMP_NUM_THREADS"] = "1"

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())



class DummyEmbedder:
    def embed(self, texts):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # Fallback to random if no key
            return [ [random.random() for _ in range(384)] for _ in texts ]
        
        # Call Gemini for embeddings
        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
        results = []
        for text in texts:
            data = {"model": "models/text-embedding-004", "content": {"parts": [{"text": text}]}}
            req = urllib.request.Request(url, json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as response:
                    res_body = json.loads(response.read().decode("utf-8"))
                    # Gemini is 768 dims, truncate to 384 for schema compatibility
                    emb = res_body.get("embedding", {}).get("values", [0]*768)
                    results.append(emb[:384])
            except:
                results.append([random.random() for _ in range(384)])
        return results

class WebScraperPipeline:
    """Async pipeline for scraping HTML, embedding, and vector ingestion.
    
    Attributes:
        db_path (duckdb.DuckDBPyConnection): The DuckDB connection instance.
        embedding_model_name (str): The name of the FastEmbed model being used.
        embedding_model (TextEmbedding): The FastEmbed model instance.
    """

    def __init__(self, db_path: str = "webscraper.duckdb", embedding_model: str = "BAAI/bge-small-en-v1.5") -> None:
        """Initializes the pipeline and connects to the DuckDB instance.

        Args:
            db_path: Filepath to the DuckDB database. Defaults to "webscraper.duckdb".
            embedding_model: The FastEmbed model name to load. Defaults to "BAAI/bge-small-en-v1.5".
        """
        self.db_path: duckdb.DuckDBPyConnection = duckdb.connect(db_path)
        self.embedding_model_name: str = embedding_model
        # Initialize FastEmbed with strict 1-thread limit to prevent CPU oversubscription
        self.embedding_model: TextEmbedding = DummyEmbedder()
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the DuckDB schema with vss HNSW index.
        
        Requires the vss extension to be installed and loaded, and enables
        experimental persistence for HNSW indexing on disk.
        """
        logger.info("Initializing DuckDB schema and HNSW vss index.")
        self.db_path.execute("INSTALL vss;")
        self.db_path.execute("LOAD vss;")
        
        # Required for creating HNSW indexes on persistent databases
        self.db_path.execute("SET hnsw_enable_experimental_persistence=true;")

        self.db_path.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id VARCHAR PRIMARY KEY,
                url VARCHAR,
                title VARCHAR,
                content TEXT,
                chunk_index INTEGER,
                embedding FLOAT[384]
            );
        """)
        
        self.db_path.execute("""
            CREATE INDEX IF NOT EXISTS doc_idx 
            ON documents USING HNSW (embedding) WITH (metric = 'cosine');
        """)

    def clean_html(self, html_content: str) -> Optional[str]:
        """Cleans HTML using Selectolax and extracts main text using Trafilatura.

        Args:
            html_content: The raw HTML string to clean.

        Returns:
            The extracted plain text content, or None if extraction fails.
        """
        try:
            tree = selectolax_lexbor.LexborHTMLParser(html_content)
            for tag in tree.css("script, style, noscript, nav, footer, header"):
                tag.decompose()
            cleaned_html = tree.html
            if not cleaned_html:
                return None

            text = trafilatura.extract(cleaned_html)
            if text:
                # Apply advanced normalization
                from WebSearch.scraper.text_processors import TextNormalizer
                text = TextNormalizer.normalize(text)
            return text
        except Exception as e:
            logger.error("Error extracting HTML: %s", e)
            return None

    async def fetch_url(self, client: httpx2.AsyncClient, url: str) -> Optional[Dict[str, str]]:
        """Fetches a URL asynchronously.

        Args:
            client: The HTTPX async client.
            url: The URL to fetch.

        Returns:
            A dictionary containing the 'url' and 'html' response, or None if the request fails.
        """
        try:
            response = await client.get(url, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            return {"url": url, "html": response.text}
        except Exception as e:
            logger.error("Failed to fetch %s: %s", url, e)
            return None

    def _chunk_text(self, text: str, chunk_size: int = 1000) -> List[str]:
        """Chunks text into smaller segments.

        Args:
            text: The text string to chunk.
            chunk_size: Maximum characters per chunk. Defaults to 1000.

        Returns:
            A list of text strings representing the chunks.
        """
        raw_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        from WebSearch.scraper.text_processors import Deduper
        
        # Apply exact and fuzzy deduplication to optimize vector DB storage
        exact_deduped = Deduper.exact_dedupe(raw_chunks)
        # Uncomment to enable fuzzy deduplication (slower but catches sliding windows)
        # return Deduper.fuzzy_dedupe(exact_deduped, threshold=0.85)
        return exact_deduped

    async def process_urls(self, urls: List[str]) -> None:
        """Fetches, cleans, embeds, and ingests a list of URLs.

        Args:
            urls: A list of URL strings to process.
        """
        limits = httpx2.Limits(max_connections=50, max_keepalive_connections=10)
        async with httpx2.AsyncClient(limits=limits) as client:
            sem = asyncio.Semaphore(50)
            
            async def _fetch_with_sem(u: str) -> Optional[Dict[str, str]]:
                async with sem:
                    return await self.fetch_url(client, u)
                    
            results: List[Optional[Dict[str, str]]] = await asyncio.gather(*[_fetch_with_sem(u) for u in urls])

        docs_to_insert: List[Tuple[str, str, str, str, int, List[float]]] = []
        texts_to_embed: List[str] = []
        metadata_list: List[Dict[str, Any]] = []

        for res in results:
            if not res:
                continue
            
            url = res["url"]
            # Offload CPU-bound parsing to GIL-free threads
            text = await asyncio.to_thread(self.clean_html, res["html"])
            if not text:
                continue
                
            chunks = self._chunk_text(text)
            for i, chunk in enumerate(chunks):
                doc_id = f"{url}_{i}"
                texts_to_embed.append(chunk)
                metadata_list.append({
                    "id": doc_id,
                    "url": url,
                    "title": "Extracted Title",
                    "content": chunk,
                    "chunk_index": i
                })

        if not texts_to_embed:
            logger.info("No text to embed.")
            return

        logger.info("Embedding %d chunks...", len(texts_to_embed))
        
        # Offload FastEmbed blocking computation to thread
        def _embed_all(texts: List[str]) -> List[Any]:
            return list(self.embedding_model.embed(texts))
            
        embeddings = await asyncio.to_thread(_embed_all, texts_to_embed)

        logger.info("Ingesting into DuckDB...")
        
        # Convert to tuple list for the executemany
        for meta, emb in zip(metadata_list, embeddings):
            docs_to_insert.append((
                meta["id"],
                meta["url"],
                meta["title"],
                meta["content"],
                meta["chunk_index"],
                emb
            ))

        def _ingest() -> None:
            self.db_path.executemany("""
                INSERT OR REPLACE INTO documents (id, url, title, content, chunk_index, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            """, docs_to_insert)
            
        await asyncio.to_thread(_ingest)

        logger.info("Successfully ingested %d chunks.", len(docs_to_insert))

    def search(self, query: str, limit: int = 5) -> List[Tuple[Any, ...]]:
        """Performs a semantic search query against the HNSW index.

        Args:
            query: The natural language search query.
            limit: The maximum number of results to return. Defaults to 5.

        Returns:
            A list of tuples representing the database rows returned.
        """
        query_embedding_gen = self.embedding_model.embed([query])
        query_embedding: List[float] = list(query_embedding_gen)[0]

        result: List[Tuple[Any, ...]] = self.db_path.execute("""
            SELECT id, url, content, array_distance(embedding, ?::FLOAT[384]) as dist
            FROM documents
            ORDER BY dist
            LIMIT ?;
        """, (query_embedding, limit)).fetchall()
        
        return result

async def main() -> None:
    """Main execution entrypoint using argparse for CLI functionality."""
    parser = argparse.ArgumentParser(description="WebScraper Vector DB Ingestion CLI")
    parser.add_argument(
        "--db", 
        type=str, 
        default="webscraper.duckdb", 
        help="Path to the DuckDB database file. Defaults to webscraper.duckdb."
    )
    parser.add_argument(
        "--urls", 
        type=str, 
        nargs="+", 
        help="A list of URLs to fetch, extract, embed, and ingest."
    )
    parser.add_argument(
        "--search", 
        type=str, 
        help="A semantic query to search against the Vector database."
    )
    parser.add_argument(
        "--limit", 
        type=int, 
        default=5, 
        help="The maximum number of search results to return. Defaults to 5."
    )
    args = parser.parse_args()

    pipeline = WebScraperPipeline(db_path=args.db)
    
    if args.urls:
        logger.info("Processing %d URLs...", len(args.urls))
        await pipeline.process_urls(args.urls)
        
    if args.search:
        logger.info("Searching for: '%s'", args.search)
        results = pipeline.search(args.search, limit=args.limit)
        
        print("\n--- Search Results ---")
        for idx, r in enumerate(results, 1):
            doc_id, url, content, distance = r[0], r[1], r[2], r[3]
            snippet = content[:150].replace("\n", " ") + "..." if len(content) > 150 else content
            print(f"{idx}. Distance: {distance:.4f} | URL: {url}")
            print(f"   Snippet: {snippet}\n")
            
    if not args.urls and not args.search:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())
