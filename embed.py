from typing import List
import os
from dotenv import load_dotenv
from langchain_ollama import OllamaEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from schema import MetadataSchema



def get_embeddings():
    load_dotenv()
    return GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-2-preview",
        )


def to_document(item: MetadataSchema) -> Document:
    page_content = f"{item.title}\n\n{item.content}"
    metadata = {
        "title": item.title,
        "target": ", ".join(item.target),
        "start_date": item.start_date,
        "end_date": item.end_date,
        "category": item.category,
        "url": item.url,
    }
    return Document(page_content=page_content, metadata=metadata)




