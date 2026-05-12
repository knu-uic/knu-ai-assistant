from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os

def get_model():
    load_dotenv()
    model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key = os.getenv("GOOGLE_API_KEY"),
    )
    return model