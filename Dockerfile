# LinkedIn Skills Studio: private-cloud / always-on deployment.
FROM python:3.13-slim
WORKDIR /srv/studio
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LINKEDIN_APP_DATA=/data APP_HOST=0.0.0.0 APP_PORT=8765
VOLUME /data
EXPOSE 8765
# APP_TOKEN is required for a non-loopback bind; pass it at run time, never bake it in.
CMD ["python3", "-m", "app", "serve"]
