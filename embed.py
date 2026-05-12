from typing import List
from dotenv import load_dotenv
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from schema import MetadataSchema

PERSIST_DIR = "./chroma_db"
COLLECTION_NAME = "knu_notices"


def get_embeddings() -> OllamaEmbeddings:
    load_dotenv()
    return OllamaEmbeddings(model = 'nomic-embed-text-v2-moe')


def to_document(item: MetadataSchema) -> Document:
    page_content = f"{item.title}\n\n{item.content}"
    metadata = {
        "title": item.title,
        "target": ", ".join(item.target),
        "deadline": item.deadline or "",
        "category": item.category,
        "url": item.url,
    }
    return Document(page_content=page_content, metadata=metadata)


def embed_and_store(refined_data: List[MetadataSchema]) -> FAISS:
    documents = [to_document(item) for item in refined_data]
    vectorstore = FAISS.from_documents(
        documents=documents,
        embedding=get_embeddings(),
    )
    
    vectorstore.save_local("./exp-faiss")
    
    return vectorstore




