FROM python:3.13-slim

# Unbuffered stdout so the [index] progress lines show up live in `docker logs`.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "-m", "appmind_indexer.run"]
