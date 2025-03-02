FROM python:3.12-slim

# Install Node.js 18 and necessary dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg2 \
    lsb-release \
    procps \
    lsof \
    bash \
    && curl -sL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean

WORKDIR /app
ENV CHOKIDAR_USEPOLLING=true
RUN npm install @slidev/cli @slidev/theme-default @slidev/theme-seriph

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy the app code
COPY . /app
EXPOSE 8502
EXPOSE 3030

# Run Streamlit
CMD ["streamlit", "run", "/app/slide_master_3000.py", "--server.headless=true", "--server.port=8502", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]

