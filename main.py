from crawler import crawling
from refine import refine
from typing import List
from schema import MetadataSchema
from embed import get_embeddings, embed_and_store

if __name__ == "__main__":
    if __name__ == "__main__":                                                                                                                              
        print("1. 크롤링 시작")
        crawled = crawling()                                                                                                                                  
        print(f"2. 크롤링 완료: {len(crawled)}개")
                                                                                                                                                          
        refined_data: List[MetadataSchema] = refine(crawled)
        for doc in refined_data:
            print(f'카테고리: {doc.category}')
            print(f'대상: {doc.target}')                                                                                                                 
            print(f'내용: {doc.content}')
            print(f'제출기한: {doc.deadline}')
            print(f'url: {doc.url}')
            
        print(f"3. 정제 완료: {len(refined_data)}개")                                                                                                         
                                                                                                                                                            
        embed_and_store(refined_data)
        print("4. 임베딩 + 저장 완료")   
