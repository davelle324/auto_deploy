FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /app/data is the mount point for the persistent SQLite volume
RUN mkdir -p /app/data

EXPOSE 8000

ENV DATABASE_URL=sqlite+aiosqlite:////app/data/auto_deploy.db

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
