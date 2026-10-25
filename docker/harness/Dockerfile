FROM docker.m.daocloud.io/library/python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       nodejs php-cli default-jdk-headless golang-go ruby bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 sandbox || true
USER sandbox
WORKDIR /tmp
