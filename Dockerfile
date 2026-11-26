FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY . .

EXPOSE 8801

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8801/api/session',timeout=4)"

CMD ["python3", "server.py"]
