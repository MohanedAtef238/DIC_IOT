FROM python:3.12-slim

WORKDIR /app

COPY dashboard_app/requirements.txt ./dashboard_app/requirements.txt
RUN pip install --no-cache-dir -r dashboard_app/requirements.txt

COPY dashboard_app ./dashboard_app
COPY engine_app/network ./engine_app/network

EXPOSE 8501

CMD ["streamlit", "run", "dashboard_app/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
