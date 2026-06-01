"""
RAG Pipeline - Formula 101
Carga documentos de conocimiento F1, genera embeddings locales con sentence-transformers
y crea un vector store persistente con ChromaDB.
"""

import shutil
from pathlib import Path
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

# ── Rutas ────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.parent
KNOWLEDGE_DIR = BASE_DIR / "data" / "f1_knowledge"
CHROMA_DIR    = BASE_DIR / "data" / "chroma_db"
MARKER_FILE   = CHROMA_DIR / ".embedding_model"

# ── Modelo de embeddings (Google, sin dependencias locales pesadas) ───────────
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "f1_knowledge"

# ── Singletons cacheados en memoria ──────────────────────────────────────────
_embeddings_instance: HuggingFaceEmbeddings | None = None
_vector_store_instance: Chroma | None = None


def _build_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings_instance
    if _embeddings_instance is None:
        _embeddings_instance = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings_instance


def _needs_rebuild() -> bool:
    """Retorna True si el vector store no existe o fue creado con otro modelo."""
    if not CHROMA_DIR.exists() or not any(CHROMA_DIR.iterdir()):
        return True
    if not MARKER_FILE.exists():
        return True
    return MARKER_FILE.read_text().strip() != EMBEDDING_MODEL


def _write_marker() -> None:
    MARKER_FILE.write_text(EMBEDDING_MODEL)


def _load_documents():
    loader = DirectoryLoader(
        str(KNOWLEDGE_DIR),
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    docs = loader.load()
    for doc in docs:
        doc.metadata["source"] = Path(doc.metadata.get("source", "")).name
    return docs


def _split_documents(docs):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n===", "\n\n", "\n", " "],
    )
    return splitter.split_documents(docs)


def get_or_create_vector_store() -> Chroma:
    """
    Retorna el vector store. Lo reconstruye automáticamente si el modelo
    de embeddings cambió o si no existe.
    """
    global _vector_store_instance

    if _vector_store_instance is not None and not _needs_rebuild():
        return _vector_store_instance

    embeddings = _build_embeddings()

    if _needs_rebuild():
        _vector_store_instance = None
        if CHROMA_DIR.exists():
            shutil.rmtree(CHROMA_DIR)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)

        print("Construyendo base de conocimiento F1...")
        docs   = _load_documents()
        chunks = _split_documents(docs)
        _vector_store_instance = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            collection_name=COLLECTION_NAME,
            persist_directory=str(CHROMA_DIR),
        )
        _write_marker()
        print(f"Base de conocimiento lista: {len(chunks)} chunks de {len(docs)} documentos.")
    else:
        _vector_store_instance = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(CHROMA_DIR),
        )

    return _vector_store_instance


def get_retriever(k: int = 4):
    """Retorna un retriever listo para usar en el agente."""
    return get_or_create_vector_store().as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
