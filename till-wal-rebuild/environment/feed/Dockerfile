FROM python:3.13-slim-bookworm
COPY payload.nclog /payload.nclog
COPY feed.token /feed.token
COPY serve.py /serve.py
EXPOSE 9377
CMD ["python3", "/serve.py"]
