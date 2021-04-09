FROM python:3.7.5-alpine

WORKDIR /home
ADD . ./app

RUN apk update
RUN  apk add --no-cache py3-setuptools
RUN apk add --no-cache ffmpeg

RUN pip install --upgrade pip
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

ENTRYPOINT ["python3", "bot.py"]