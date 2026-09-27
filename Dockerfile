FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN python -m zipfile -e resources.zip .
RUN useradd --create-home appuser
USER appuser
ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "bot.py"]
