from crawler import crawling
from refine import refine
from typing import List
from schema import MetadataSchema
from db import init_db, insert_notice

if __name__ == "__main__":
    init_db()
                                                                                                                                  
    print("1. 크롤링 시작")
    crawled = crawling()                                                                                                                                  
    print(f"2. 크롤링 완료: {len(crawled)}개")
                                                                                                                                                      
    refined_data: List[MetadataSchema] = refine(crawled)
    for doc in refined_data[:2]:
        print(f'제목: {doc.title}')
        print(f'카테고리: {doc.category}')
        print(f'대상: {doc.target}')                                                                                                                 
        print(f'내용: {doc.content}')
        print(f'접수 시작일: {doc.start_date}')
        print(f'접수 마감일: {doc.end_date}')
        print(f'url: {doc.url}')
        print(f'keywords: {doc.keywords}')

        insert_notice(doc.url, doc.title, doc.content, doc.start_date, doc.end_date, doc.category, doc.target, doc.keywords)
        
                                                                                                                
                                                                                                                                                            

        
    
