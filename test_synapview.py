import sys
from playwright.sync_api import sync_playwright

# parsers/document_parser.py 에서 함수 임포트
from parsers import document_parser as attachments

def test_synap(url: str):
    """Playwright를 띄워 공주대 SynapView 미리보기 페이지에서 텍스트를 추출해옵니다."""
    print(f"\n{'='*60}")
    print(f"🚀 스냅뷰(SynapView) 파싱 테스트 시작")
    print(f"🔗 URL: {url}")
    print(f"{'='*60}")
    
    with sync_playwright() as p:
        # headless=True 로 백그라운드 실행
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        try:
            print("⏳ 브라우저를 열고 스냅뷰 렌더링 대기 중... (networkidle 대기 포함)")
            result_text = attachments.hwpx_via_preview(url, context)
            
            print("\n[✅ 파싱 완료 - 추출된 텍스트 결과]")
            print("-" * 50)
            if not result_text.strip():
                print("(추출된 텍스트가 없습니다. 페이지가 비어있거나, iframe 로딩 실패일 수 있습니다.)")
            else:
                print(result_text)
            print("-" * 50)
            
        except Exception as e:
            print(f"\n❌ 파싱 중 에러 발생: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 오류: 테스트할 스냅뷰(synapView.do) URL을 함께 입력해주세요.")
        print("\n사용법: python test_synapview.py \"[스냅뷰_URL]\"")
        print("예시: python test_synapview.py \"https://computer.kongju.ac.kr/bbs/.../synapView.do?키값\"")
        sys.exit(1)
        
    target_url = sys.argv[1]
    test_synap(target_url)
