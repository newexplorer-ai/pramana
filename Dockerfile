# Pramana — single container: FastAPI orchestrator + static frontend.
FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# Frontend (served by the same process) + backend.
# Copy the whole server package — .dockerignore keeps the venv and local db
# out. Cherry-picking single files here previously shipped an image missing
# a new module and crashed the app on boot.
COPY css/ css/
COPY js/ js/
COPY *.html ./
COPY server/ server/

# SQLite lives on the mounted volume so it survives deploys/restarts.
ENV PRAMANA_DB=/data/pramana.db
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app:app", "--app-dir", "server", \
     "--host", "0.0.0.0", "--port", "8080"]
