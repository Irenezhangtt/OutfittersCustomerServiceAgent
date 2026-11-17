FROM node:24-alpine AS ui
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY data/ data/
COPY --from=ui /build/frontend/dist frontend/dist
RUN useradd --create-home sierra && mkdir /app/storage && chown -R sierra:sierra /app
USER sierra
EXPOSE 8000
CMD ["uvicorn", "sierra.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
