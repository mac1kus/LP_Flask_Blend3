FROM python:3.11-slim

WORKDIR /app

# Install GLPK and dependencies
RUN apt-get update && \
    apt-get install -y glpk-utils libglpk-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

ENV PORT=10000
EXPOSE $PORT

CMD ["python", "app.py"]
