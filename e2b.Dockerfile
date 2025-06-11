# You can use most Debian-based base images
FROM e2bdev/code-interpreter:latest

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    procps \
    lsof \
    git \
    net-tools

COPY src/ii_agent/utils/tool_client /app/ii_client

RUN pip install -r ii_client/requirements.txt

RUN mkdir -p /workspace

CMD ["python", "-m", "ii_client.sandbox_server", "--port", "17300" , "--cwd", "/workspace"]
