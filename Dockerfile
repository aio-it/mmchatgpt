FROM ubuntu:latest
RUN apt-get update
RUN apt-get install -y curl iputils-ping wget dnsutils pwgen traceroute iproute2
#ENTRYPOINT [ "/usr/bin/env" ]
#CMD [ "bash" ]