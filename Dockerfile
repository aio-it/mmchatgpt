FROM python:3.10
# set working directory
WORKDIR /app
# install dig and other utils used by shellcmds
RUN apt-get update && apt-get install -y dnsutils net-tools iputils-ping
# copy requirements.txt first for caching
COPY requirements.txt /app/
RUN pip install -r requirements.txt --no-cache-dir
# copy the rest of the files
COPY . /app/
# remove .env files
RUN rm .env*
# run the bot
CMD ["python", "bot.py"]