FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    VENDOR_RISK_BASE_URL=http://127.0.0.1:8001
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# The mock vendor-risk API stays internal; only the web app is exposed (Render sets PORT).
EXPOSE 7860
CMD ["sh", "-c", "python -m uvicorn mock_api.app:app --host 127.0.0.1 --port 8001 --log-level warning & exec python -m uvicorn webapp.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
