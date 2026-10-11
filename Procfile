web: gunicorn server:app --worker-class gthread --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:$PORT
