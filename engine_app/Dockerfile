# engine_app/Dockerfile
# Packages the Campus IoT simulation engine into a minimal container image.

FROM python:3.12-slim

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" engine_user

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (improves layer caching)
COPY requirements.txt .
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		build-essential \
		gcc \
		libffi-dev \
		libssl-dev \
		pkg-config \
		autoconf \
		automake \
		libtool \
	&& rm -rf /var/lib/apt/lists/* \
	&& pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Persistent state volume mount point
RUN mkdir -p /data && chown engine_user:engine_user /data

USER engine_user

CMD ["python", "main.py"]