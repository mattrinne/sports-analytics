FROM apache/airflow:3.3.1-python3.12

# Project runtime deps. Source code itself is bind-mounted at /opt/airflow/src (see compose),
# so only dependency changes require `docker compose build`.
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
