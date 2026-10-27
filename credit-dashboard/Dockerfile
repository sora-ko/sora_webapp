FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY academic_rules.py classification.py parser.py timetable_parser.py requirement_evaluator.py recommendations.py recommendation_search.py server.py ./
COPY rules/ ./rules/
COPY static/ ./static/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
