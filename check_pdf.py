import sys
from pathlib import Path

# 경로 설정
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from parsers.curriculum_parser import parse

def main():
    target_pdf = "data/curriculums/공과대학/컴퓨터공학과/cse_curriculum_2011_to_2026.pdf"
    print(f"--- {target_pdf} 파싱을 시작합니다 (GPT-5.4-mini 호출 중...) ---")
    
    try:
        result = parse(target_pdf)
        years = result.get("years", [])
        print(f"완료! 총 {len(years)}개 페이지 추출!\n")
        
        for year in years:
            print("-" * 40)
            print(f"페이지 번호: {year.get('page_number')}")
            print(f"연도 라벨(VLM 추출): {year.get('year_label')}")
            print("-" * 40)
            print(year.get("markdown_table"))
            print("\n")
            
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    main()
