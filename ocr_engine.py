import os
import easyocr
import logging

logging_str = "[%(asctime)s: %(levelname)s: %(module)s]: %(message)s"
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(filename=os.path.join(log_dir,"ekyc_logs.log"), level=logging.INFO, format=logging_str, filemode="a")

_reader = None


def extract_text(image, confidence_threshold=0.3, languages=("en",)):
    global _reader
    if image is None:
        return ""
    try:
        if _reader is None:
            _reader = easyocr.Reader(list(languages))
        results = _reader.readtext(image)
        recognized = [text.strip() for _, text, confidence in results
                      if confidence >= confidence_threshold and text.strip()]
        logging.info("OCR completed: %d text regions passed confidence threshold", len(recognized))
        return "|".join(recognized)
    except Exception as e:
        logging.exception("OCR failed")
        return ""
    
