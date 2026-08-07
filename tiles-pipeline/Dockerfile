FROM python:3.12-slim

WORKDIR /app

# serve_tiles.py only needs the stdlib (sqlite3 + http.server)
COPY serve_tiles.py ./

ENV TILES_HOST=0.0.0.0 \
    TILES_FILE=/app/data/spain.mbtiles \
    TILES_PORT=8765 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

# TILES_FILE and TILES_PORT are read via shell expansion since
# serve_tiles.py takes them as positional CLI args, not env vars.
CMD ["sh", "-c", "python serve_tiles.py \"$TILES_FILE\" \"$TILES_PORT\""]