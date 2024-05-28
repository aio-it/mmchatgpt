FROM python:3.11.9-slim-bookworm
LABEL maintainer="Lars Bo Rasmussen <lrasmussen@aio-it.dk>"
LABEL version="1.0"
# set working directory
WORKDIR /app
# install dig and other utils used by shellcmds
RUN apt-get update && apt-get install -y dnsutils net-tools iputils-ping traceroute
# copy requirements.txt first for caching
COPY requirements.txt /app/
RUN pip install -r requirements.txt --no-cache-dir
# copy the rest of the files
COPY . /app/
# remove .env files
RUN rm .env* || true
RUN rm .* || true
# run the bot
CMD ["python", "bot.py"]