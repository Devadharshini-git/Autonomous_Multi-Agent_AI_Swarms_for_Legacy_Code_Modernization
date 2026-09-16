# sandbox/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt pytest pytest-cov

CMD ["pytest", "--cov=.", "--cov-report=term-missing", "-v"]