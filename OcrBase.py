import os
import numpy as np
import easyocr
from pdf2image import convert_from_path


reader = easyocr.Reader(['ko', 'en'], gpu=True)

def extract_ocr_text(pdf_path):
        """PDF 페이지를 이미지로 변환하여 OCR 수행"""
        ocr_docs = []
        images = convert_from_path(pdf_path, dpi=200)
        
        for page_num, image in enumerate(images):
            img_np = np.array(image)
            result = reader.readtext(img_np, detail=0) #readtext()에서 세부 조정 가능 ex) 대조, 밝기, 문단 감지 등
            ocr_text = " ".join(result) 
            if ocr_text.strip():
                ocr_docs.append({
                    "page": page_num + 1,
                    "text": ocr_text
                })
        return ocr_docs

if __name__ == "__main__":
            print(extract_ocr_text("test.pdf"))