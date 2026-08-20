import argparse
import hashlib
import os
import sys
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

load_dotenv()

# region Configuration

BOOKSTACK_URL = os.environ["BOOKSTACK_URL"].rstrip("/")
BOOKSTACK_TOKEN_ID = os.environ["BOOKSTACK_TOKEN_ID"]
BOOKSTACK_TOKEN_SECRET = os.environ["BOOKSTACK_TOKEN_SECRET"]

QDRANT_URL = os.environ["QDRANT_URL"]
OLLAMA_URL = os.environ["OLLAMA_URL"].rstrip("/")

EMBED_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    os.environ.get("EMBED_MODEL", "nomic-embed-text"),
)

COLLECTION = os.environ.get(
    "QDRANT_COLLECTION",
    "bookstack",
)

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "2000"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "300"))

BOOKSTACK_PAGE_SIZE = 100
REQUEST_TIMEOUT = 60
EMBED_TIMEOUT = 120

QDRANT_BATCH_SIZE = 50

# endregion

# region HTTP sessions
bookstack_session = requests.Session()

bookstack_session.headers.update(
    {
        "Authorization": (f"Token {BOOKSTACK_TOKEN_ID}:{BOOKSTACK_TOKEN_SECRET}"),
        "Accept": "application/json",
    }
)

ollama_session = requests.Session()

# endregion


# region Bookstack
def get_bookstack_pages():
    """
    Retrieve every page from BookStack using pagination.
    """

    pages = []
    offset = 0

    while True:
        response = bookstack_session.get(
            f"{BOOKSTACK_URL}/api/pages",
            params={
                "count": BOOKSTACK_PAGE_SIZE,
                "offset": offset,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        batch = data.get("data", [])

        if not batch:
            break

        pages.extend(batch)

        print(
            f"Retrieved {len(pages)} BookStack pages...",
            flush=True,
        )

        if len(batch) < BOOKSTACK_PAGE_SIZE:
            break

        offset += BOOKSTACK_PAGE_SIZE

    return pages


def get_bookstack_page(page_id):
    """
    Retrieve full BookStack page content and metadata.
    """

    response = bookstack_session.get(
        f"{BOOKSTACK_URL}/api/pages/{page_id}",
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# endregion


# region Text processing
def clean_html(html):
    """
    Convert BookStack HTML into plain text suitable for embedding.
    """

    soup = BeautifulSoup(
        html or "",
        "html.parser",
    )

    # Remove elements that should not contribute
    # to document content.
    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
        ]
    ):
        element.decompose()

    text = soup.get_text("\n")

    # Normalize whitespace while preserving
    # paragraph boundaries.
    lines = []

    for line in text.splitlines():
        line = " ".join(line.split())

        if line:
            lines.append(line)

    return "\n\n".join(lines)


splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=[
        "\n\n",
        "\n",
        ". ",
        "! ",
        "? ",
        "; ",
        ", ",
        " ",
        "",
    ],
)

# endregion


# region Embeddings
def create_embedding(text):
    """
    Generate an embedding using Ollama.
    """

    response = ollama_session.post(
        f"{OLLAMA_URL}/api/embed",
        json={
            "model": EMBED_MODEL,
            "input": text,
        },
        timeout=EMBED_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    embeddings = data.get("embeddings")

    if not embeddings:
        raise RuntimeError(f"Ollama response did not contain embeddings: {data}")

    return embeddings[0]


# endregion


# region Qdrant
def get_qdrant_client():
    """
    Create a Qdrant client.
    """

    return QdrantClient(
        url=QDRANT_URL,
        timeout=120,
    )


def collection_exists(client):
    """
    Determine whether Qdrant collection exists.
    """

    collections = client.get_collections()

    return any(collection.name == COLLECTION for collection in collections.collections)


def create_qdrant_collection(client, vector_size):
    """
    Recreate the collection for a clean full index.
    """
    print(
        f"Creating Qdrant collection '{COLLECTION}' with vector size {vector_size}...",
        flush=True,
    )

    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(
            size=vector_size,
            distance=Distance.COSINE,
        ),
    )


# endregion

# region Search 

def search_documents(
    query: str,
    limit: int = 5,
):
    """
    Search existing BookStack embeddings in Qdrant.
    """

    client = get_qdrant_client()

    if not collection_exists(client):
        raise RuntimeError(
            f"Qdrant collection '{COLLECTION}' does not exist."
        )

    vector = create_embedding(query)

    results = client.query_points(
        collection_name=COLLECTION,
        query=vector,
        limit=limit,
        with_payload=True,
    )

    documents = []

    for result in results.points:
        payload = result.payload or {}

        documents.append(
            {
                "score": result.score,
                "title": payload.get("title"),
                "text": payload.get("text"),
                "url": payload.get("url"),
                "page_id": payload.get("page_id"),
                "chunk_index": payload.get("chunk_index"),
                "chunk_count": payload.get("chunk_count"),
                "updated_at": payload.get("updated_at"),
            }
        )

    return documents

# endregion

# region Point IDs
def create_point_id(
    page_id,
    chunk_index,
):
    """
    Generate a deterministic UUID-compatible ID.

    Same BookStack page/chunk always produces
    the same Qdrant point ID.
    """

    value = f"bookstack:{page_id}:chunk:{chunk_index}"

    return hashlib.md5(value.encode("utf-8")).hexdigest()


# endregion


# region Metadata
def build_payload(
    page,
    chunk,
    chunk_index,
    chunk_count,
):
    """
    Build Qdrant metadata payload.
    """

    return {
        "source": "bookstack",
        "source_id": str(page["id"]),
        "page_id": page["id"],
        "book_id": page.get("book_id"),
        "chapter_id": page.get("chapter_id"),
        "title": page.get("name"),
        "document_type": "page",
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "updated_at": page.get("updated_at"),
        "created_at": page.get("created_at"),
        "url": (f"{BOOKSTACK_URL}/pages/{page['id']}"),
        "text": chunk,
    }


# endregion


# region Page deletion
def delete_page(
    page_id,
    client=None,
):
    """
    Delete all Qdrant chunks belonging to a BookStack page.

    Uses payload filtering rather than point IDs so this
    remains safe if chunk IDs change in the future.
    """

    if client is None:
        client = get_qdrant_client()

    if not collection_exists(client):
        print(
            f"Qdrant collection '{COLLECTION}' does not exist. Nothing to delete.",
            flush=True,
        )

        return

    print(
        f"Deleting Qdrant chunks for BookStack page {page_id}...",
        flush=True,
    )

    client.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="source",
                    match=MatchValue(value="bookstack"),
                ),
                FieldCondition(
                    key="page_id",
                    match=MatchValue(value=page_id),
                ),
            ]
        ),
    )

    print(
        f"Deleted Qdrant chunks for page {page_id}.",
        flush=True,
    )


# endregion


# region Page preparation
def prepare_page_chunks(page):
    """
    Clean and chunk a BookStack page.

    Returns:
        list[dict]
    """

    title = page.get(
        "name",
        "Untitled",
    )

    html = page.get(
        "html",
        "",
    )

    text = clean_html(html)

    if not text.strip():
        return []

    chunks = splitter.split_text(text)

    prepared = []

    for chunk_index, chunk in enumerate(chunks):
        prepared.append(
            {
                "page": page,
                "chunk": chunk,
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
            }
        )

    print(
        f"{title} → {len(prepared)} chunks",
        flush=True,
    )

    return prepared


# endregion


# region Page indexing
def index_page(
    page_id,
    client=None,
):
    """
    Fetch, chunk, embed, and index one BookStack page.

    Existing page vectors are only deleted after every
    new chunk has successfully received an embedding.

    This prevents Ollama failures from destroying
    an otherwise valid existing index.
    """

    start_time = time.time()

    if client is None:
        client = get_qdrant_client()

    print(
        f"Indexing BookStack page {page_id}...",
        flush=True,
    )

    # -----------------------------------------------------------------------
    # Fetch current page
    # -----------------------------------------------------------------------

    page = get_bookstack_page(page_id)

    # -----------------------------------------------------------------------
    # Prepare chunks
    # -----------------------------------------------------------------------

    chunks = prepare_page_chunks(page)

    if not chunks:
        print(
            f"Page {page_id} contains no indexable content.",
            flush=True,
        )

        # Empty page should have no stale vectors.
        delete_page(
            page_id,
            client=client,
        )

        return {
            "page_id": page_id,
            "chunks": 0,
            "status": "empty",
        }

    # -----------------------------------------------------------------------
    # Generate embeddings BEFORE deleting old vectors
    # -----------------------------------------------------------------------

    print(
        f"Generating embeddings for page {page_id}...",
        flush=True,
    )

    points = []

    for index, item in enumerate(
        chunks,
        start=1,
    ):
        chunk = item["chunk"]

        vector = create_embedding(chunk)

        point_id = create_point_id(
            page_id,
            item["chunk_index"],
        )

        payload = build_payload(
            item["page"],
            chunk,
            item["chunk_index"],
            item["chunk_count"],
        )

        points.append(
            PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        )

        print(
            f"Embedded chunk {index}/{len(chunks)} for page {page_id}",
            flush=True,
        )

    # -----------------------------------------------------------------------
    # Determine vector dimensions
    # -----------------------------------------------------------------------

    vector_size = len(points[0].vector)

    # -----------------------------------------------------------------------
    # Ensure collection exists
    # -----------------------------------------------------------------------

    if not collection_exists(client):
        print(
            f"Creating Qdrant collection '{COLLECTION}' "
            f"with vector size {vector_size}...",
            flush=True,
        )

        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )
    # -----------------------------------------------------------------------
    # Delete old page vectors
    # -----------------------------------------------------------------------

    delete_page(
        page_id,
        client=client,
    )

    # -----------------------------------------------------------------------
    # Insert new vectors
    # -----------------------------------------------------------------------

    print(
        f"Uploading {len(points)} chunks for page {page_id}...",
        flush=True,
    )

    for start in range(
        0,
        len(points),
        QDRANT_BATCH_SIZE,
    ):
        batch = points[start : start + QDRANT_BATCH_SIZE]

        client.upsert(
            collection_name=COLLECTION,
            points=batch,
        )

    duration_ms = int((time.time() - start_time) * 1000)

    print(
        f"Indexed page {page_id}: {len(points)} chunks in {duration_ms}ms",
        flush=True,
    )

    return {
        "page_id": page_id,
        "chunks": len(points),
        "vector_size": vector_size,
        "duration_ms": duration_ms,
        "status": "indexed",
    }


# endregion


# region Full Ingestion
def full_ingest():
    """
    Rebuild the entire BookStack Qdrant collection.

    This is the manual/full-rebuild operation.

    Webhooks should use index_page() instead.
    """

    print(
        "Starting full BookStack RAG ingestion...",
        flush=True,
    )

    start_time = time.time()

    # -----------------------------------------------------------------------
    # Connect to Qdrant
    # -----------------------------------------------------------------------

    print(
        f"Connecting to Qdrant: {QDRANT_URL}",
        flush=True,
    )

    qdrant = get_qdrant_client()

    # -----------------------------------------------------------------------
    # Retrieve pages
    # -----------------------------------------------------------------------

    print(
        "Retrieving BookStack pages...",
        flush=True,
    )

    pages = get_bookstack_pages()

    print(
        f"Found {len(pages)} BookStack pages.",
        flush=True,
    )

    if not pages:
        print(
            "No BookStack pages found.",
            flush=True,
        )

        return

    # -----------------------------------------------------------------------
    # Process pages
    # -----------------------------------------------------------------------

    all_chunks = []

    for page_number, page_summary in enumerate(
        pages,
        start=1,
    ):
        page_id = page_summary["id"]

        try:
            page = get_bookstack_page(page_id)

            chunks = prepare_page_chunks(page)

            if not chunks:
                print(
                    f"[{page_number}/{len(pages)}] "
                    f"Skipping empty page: "
                    f"{page.get('name', 'Untitled')}",
                    flush=True,
                )

                continue

            print(
                f"[{page_number}/{len(pages)}] Prepared page {page_id}",
                flush=True,
            )

            all_chunks.extend(chunks)

        except Exception as exc:
            print(
                f"ERROR processing page {page_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    print(
        f"Total chunks: {len(all_chunks)}",
        flush=True,
    )

    if not all_chunks:
        print(
            "No chunks were created.",
            flush=True,
        )

        return

    # -----------------------------------------------------------------------
    # Generate first embedding
    # -----------------------------------------------------------------------

    print(
        "Generating first embedding to determine vector size...",
        flush=True,
    )

    first_vector = create_embedding(all_chunks[0]["chunk"])

    vector_size = len(first_vector)

    print(
        f"Embedding dimension: {vector_size}",
        flush=True,
    )

    # -----------------------------------------------------------------------
    # Recreate collection
    # -----------------------------------------------------------------------

    create_qdrant_collection(qdrant, vector_size)

    # -----------------------------------------------------------------------
    # Generate embeddings and upload
    # -----------------------------------------------------------------------

    points = []

    total = len(all_chunks)

    for index, item in enumerate(
        all_chunks,
        start=1,
    ):
        page = item["page"]
        chunk = item["chunk"]
        chunk_index = item["chunk_index"]
        chunk_count = item["chunk_count"]

        try:
            if index == 1:
                vector = first_vector
            else:
                vector = create_embedding(chunk)

            point_id = create_point_id(
                page["id"],
                chunk_index,
            )

            payload = build_payload(
                page,
                chunk,
                chunk_index,
                chunk_count,
            )

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

            if len(points) >= QDRANT_BATCH_SIZE:
                qdrant.upsert(
                    collection_name=COLLECTION,
                    points=points,
                )

                points = []

            print(
                f"Embedded {index}/{total}",
                flush=True,
            )

        except Exception as exc:
            print(
                f"ERROR embedding chunk {index}/{total}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    # Upload remaining points.
    if points:
        qdrant.upsert(
            collection_name=COLLECTION,
            points=points,
        )

    # -----------------------------------------------------------------------
    # Verify
    # -----------------------------------------------------------------------

    collection_info = qdrant.get_collection(COLLECTION)

    duration_ms = int((time.time() - start_time) * 1000)

    print()
    print("=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)

    print(f"BookStack pages: {len(pages)}")

    print(f"Chunks: {len(all_chunks)}")

    print(f"Embedding model: {EMBED_MODEL}")

    print(f"Vector dimensions: {vector_size}")

    print(f"Qdrant collection: {COLLECTION}")

    print(f"Qdrant points: {collection_info.points_count}")

    print(f"Duration: {duration_ms}ms")


# endregion


# region CLI
def main():
    parser = argparse.ArgumentParser(description="BookStack RAG ingestion.")

    parser.add_argument(
        "--page-id",
        type=int,
        help="Index one BookStack page.",
    )

    parser.add_argument(
        "--delete-page",
        type=int,
        help="Delete one BookStack page from Qdrant.",
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Rebuild the entire Qdrant collection.",
    )

    args = parser.parse_args()

    try:
        if args.page_id is not None:
            result = index_page(args.page_id)

            print(f"\nResult: {result}")

            return

        if args.delete_page is not None:
            delete_page(args.delete_page)

            print(f"\nDeleted page {args.delete_page}.")

            return

        # Preserve existing behavior:
        # running `python rag.py` performs full ingestion.
        full_ingest()

    except requests.RequestException as exc:
        print(
            f"\nRequest failed: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)

    except Exception as exc:
        print(
            f"\nError: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)


if __name__ == "__main__":
    main()

# endregion
