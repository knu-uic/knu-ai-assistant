import sys
import os

try:
    from llama_index.readers.file import HWPReader
except ImportError:
    print("❌ 오류: llama-index-readers-file 패키지가 설치되지 않았습니다.")
    print("터미널에서 아래 명령어를 실행하여 설치해주세요:")
    print("pip install llama-index-readers-file")
    sys.exit(1)

def test_hwp_reader(file_path: str):
    print(f"\n{'='*60}")
    print(f"🚀 LlamaIndex HWPReader 파싱 테스트 시작")
    print(f"📄 대상 파일: {file_path}")
    print(f"{'='*60}")
    
    if not os.path.exists(file_path):
        print(f"❌ 오류: '{file_path}' 파일을 찾을 수 없습니다.")
        print("현재 디렉토리에 테스트용 hwp 파일을 넣고 다시 실행해주세요.")
        return
        
    try:
        reader = HWPReader()
        print("⏳ 문서를 읽고 있습니다...")
        
        # load_data는 Document 객체의 리스트를 반환합니다.
        documents = reader.load_data(file_path)
        
        if not documents:
            print("⚠️ 파싱된 데이터가 없습니다. (빈 문서이거나 포맷을 읽지 못함)")
            return
            
        print(f"\n[✅ 파싱 완료 - 총 {len(documents)}개의 Document 블록 추출됨]")
        
        for idx, doc in enumerate(documents, 1):
            print(f"\n{'='*20} Document {idx} {'='*20}")
            text = doc.text
            
            if not text.strip():
                print("(빈 텍스트)")
            else:
                print(text)
                
            print(f"\n[메타데이터]: {doc.metadata}")
            print("="*52)
            
    except Exception as e:
        print(f"\n❌ 파싱 중 에러 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 오류: 테스트할 HWP 파일 이름을 입력해주세요.")
        print("\n사용법: python test_hwp_reader.py [파일경로.hwp]")
        print("예시: python test_hwp_reader.py test.hwp")
        sys.exit(1)
        
    target_file = sys.argv[1]
    test_hwp_reader(target_file)
