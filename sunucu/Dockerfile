FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Istanbul
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 kanit && useradd -u 10001 -g kanit -m kanit
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data && chown kanit:kanit /data
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "app.panel"]
