import sys
import os

# parsers/document_parser.py 모듈 임포트
try:
    from parsers import document_parser as attachments
except ImportError:
    print("❌ 오류: parsers.document_parser 모듈을 불러올 수 없습니다.")
    sys.exit(1)

def test_hwpx_custom_parser(file_path: str):
    """로컬 hwpx 파일을 바이너리로 읽어 attachments.hwpx_bytes_to_text()로 파싱합니다."""
    print(f"\n{'='*60}")
    print(f"🚀 커스텀 HWPX 파서(hwpx_bytes_to_text) 테스트 시작")
    print(f"📄 대상 파일: {file_path}")
    print(f"{'='*60}")
    
    if not os.path.exists(file_path):
        print(f"❌ 오류: '{file_path}' 파일을 찾을 수 없습니다.")
        print("현재 디렉토리에 테스트용 .hwpx 파일을 넣고 다시 실행해주세요.")
        return
        
    try:
        print("⏳ 파일을 읽어 바이너리(Bytes)로 변환 중...")
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        print("⏳ attachments.hwpx_bytes_to_text() 추출 로직 실행 중...")
        # 파싱 함수 호출
        result_text = attachments.hwpx_bytes_to_text(file_bytes)
        
        print("\n[✅ 파싱 완료 - 추출된 텍스트 결과]")
        print("-" * 50)
        if not result_text.strip():
            print("(추출된 텍스트가 없습니다. 내부 XML 구조가 비정상적이거나 빈 파일일 수 있습니다.)")
        else:
            print(result_text)
        print("-" * 50)
        
    except Exception as e:
        print(f"\n❌ 파싱 중 에러 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 오류: 테스트할 .hwpx 파일 경로를 함께 입력해주세요.")
        print("\n사용법: python test_hwpx_bytes.py [파일경로.hwpx]")
        print("예시: python test_hwpx_bytes.py test.hwpx")
        sys.exit(1)
        
    target_file = sys.argv[1]
    test_hwpx_custom_parser(target_file)
