from playwright.sync_api import Browser, Page
from playwright.sync_api import sync_playwright
from typing import List

def crawling()->List[dict]:
    
    crawled_data: List[dict] = []
    
    with sync_playwright() as p:
        # 테스트할 때 눈으로 확인하기 위해 headless=False 로 변경 (나중에 True로 바꾸세요)
        browser = p.chromium.launch(headless=True)
        
        # 💡 [핵심] 컨텍스트를 만들고 탭을 2개 띄웁니다.
        context = browser.new_context()
        list_page = context.new_page()   # 1번 탭: 게시판 목록 페이지 전용
        detail_page = context.new_page() # 2번 탭: 게시글 상세 내용 전용

        list_page.on("dialog", lambda dialog: dialog.accept())
        url = 'https://www.kongju.ac.kr/KNU/16909/subview.do'
        list_page.goto(url, wait_until="networkidle")

        # ❗ with 블록 안으로 들여쓰기 되었습니다.
        for page_num in range(1, 2):
            if page_num != 1:
                # 1. "다음 페이지" 대신 "2페이지", "3페이지"를 명확히 찾아 클릭
                # (상/하단 2개일 수 있으니 .first를 붙여 무조건 첫 번째 것을 클릭)
                list_page.get_by_title(f"{page_num}페이지").click()
                
                # 2. networkidle 대신 물리적인 대기 시간 부여 (가장 안전한 방법)
                # 게시판이 비동기(AJAX)로 로딩될 경우 networkidle이 안 먹힐 수 있습니다.
                # 2초(2000ms) 정도 확실하게 기다려주면 2페이지 목록이 화면에 뜹니다.
                list_page.wait_for_load_state("networkidle")
            
            # 1. 목록 탭(list_page)에서 게시글 링크 찾기
            list_page.wait_for_selector('.td-subject a')

            # 1페이지는 일반공지 포함, 2페이지부터는 tr.notice 제외
            if page_num == 1:
                row_selector = 'tr:has(.td-subject a)'
            else:
                row_selector = 'tr:not(.notice):has(.td-subject a)'

            rows = list_page.locator(row_selector).all()

            # 2. 링크 추출
            post_urls = []
            for row in rows:
                href = row.locator('.td-subject a').first.get_attribute('href')
                if href:
                    full_url = f"https://www.kongju.ac.kr{href}"
                    post_urls.append(full_url)
            
            print(f"\n=== {page_num}페이지: 총 {len(post_urls)}개의 게시글 링크 수집 완료 ===")

            # 3. 수집한 링크들에 순서대로 접속 (detail_page 탭 사용)
            for j, post_url in enumerate(post_urls):
                print(f"[{j+1}/{len(post_urls)}] {post_url} 접속 중...")
                
                # 💡 목록 탭은 그대로 두고, 2번 탭(detail_page)만 이동시킵니다.
                detail_page.goto(post_url, wait_until="networkidle")
                
                try:
                    title = detail_page.locator('.view-title').inner_text() 
                except Exception:
                    title = "제목을 찾을 수 없음"
                
                try:
                    date = detail_page.locator('.write dd').inner_text()
                except Exception:
                    date = "등록일을 찾을 수 없음"

                try:
                    paragraphs = detail_page.locator('.view-con p').all_inner_texts()
                    content = '\n'.join(paragraphs)
                except Exception:
                    content = "내용을 찾을 수 없음"
                
                print(title)
                print(date)
                print(content)
                
                crawled_data.append(
                    {
                        'title':title,
                        'date': date,
                        'content': content,
                        'url': post_url
                    }
                )
            
        return crawled_data
                
                
                
                

