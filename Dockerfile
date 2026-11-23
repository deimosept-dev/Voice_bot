FROM python:3.12-slim
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-rus
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
