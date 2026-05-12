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

def load_from_local()->FAISS:
    return FAISS.load_local("./exp-faiss", get_embeddings(), allow_dangerous_deserialization= True)


def embed_and_store(refined_data: List[MetadataSchema]) -> FAISS:
    documents = [to_document(item) for item in refined_data]
    vectorstore = FAISS.from_documents(
        documents=documents,
        embedding=get_embeddings(),
    )
    
    vectorstore.save_local("./exp-faiss")
    
    return vectorstore

def retrieve(query: str):
    if os.path.exists("./exp-faiss"):
        retriever = load_from_local().as_retriever(
            search_type = "mmr",
            search_kwargs = {
                "k": 3,
                "fetch_k": 10,
                "lambda_mult": 0.5,
            }
        )
        
        return retriever.invoke(f'{query}')



