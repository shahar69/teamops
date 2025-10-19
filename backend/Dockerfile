FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# When the compose build context is `./backend` the files are at the repo root of the context.
# Copy requirements.txt from the build context into the image (if present).
COPY requirements.txt* /app/
# install dependencies if requirements file exists
RUN apt-get update && apt-get install -y \
	build-essential gcc libpq-dev curl \
	ffmpeg \
	libasound2 libasound2-dev \
	fonts-dejavu-core \
	espeak-ng libespeak-ng1 \
	&& rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip
RUN if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

# Copy the entire backend context into /app/backend
COPY . /app/backend

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
