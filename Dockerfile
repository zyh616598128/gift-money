# Gift-money ledger FastAPI service exposing a Streamable HTTP MCP server at /mcp.
# Used by the interop-fabric orchestration service as a real execution-layer data
# source for the MCP hop (answer_gift_question).
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: sqlite3 backend needs nothing extra; keep the image minimal.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY seed_data.py .
COPY .env.example ./.env.example

# Seed the demo ledger (idempotent) then start the HTTP + MCP server.
EXPOSE 8000
CMD ["sh", "-c", "python seed_data.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]