FROM python:3.12-slim

WORKDIR /app
COPY ripper.py server.py ./
COPY static ./static

ENV PORT=8787
EXPOSE 8787

CMD ["python3", "server.py"]
