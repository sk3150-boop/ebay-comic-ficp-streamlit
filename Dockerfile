FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-streamlit.txt /app/requirements-streamlit.txt
RUN pip install --no-cache-dir -r /app/requirements-streamlit.txt \
    && python -m playwright install --with-deps chromium

COPY . /app

EXPOSE 8501

CMD ["sh", "-c", "streamlit run comic_ficp_streamlit_app.py --server.address 0.0.0.0 --server.port ${PORT:-8501}"]
