FROM python:3.11-slim
WORKDIR /app
COPY Requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
