FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

# Install python deps first (better layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir "Flask>=3.0" "Flask-Cors>=6.0" "requests>=2.31" "gunicorn>=22.0"

# Copy the rest of the project (only what the app needs at runtime)
COPY core/ ./core/
COPY web/ ./web/
COPY server.py ./

ENV HOST=0.0.0.0 \
    PORT=5000 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Production WSGI server (gunicorn) instead of the Flask dev server.
# server:app refers to the "app" Flask instance defined in server.py.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "60", "server:app"]