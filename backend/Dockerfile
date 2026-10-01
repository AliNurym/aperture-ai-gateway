FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN useradd --create-home --uid 10001 aperture && mkdir -p /var/lib/aperture && chown -R aperture:aperture /app /var/lib/aperture
USER aperture

EXPOSE 8000
# Let the worker register once its auth contract is ready; Devnet config can be initialized separately.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import json,urllib.request; health=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/worker-auth', timeout=3)); assert health.get('worker_auth_configured') is True, 'worker authentication is not configured'"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
