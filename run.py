from flask import Flask, render_template, Response
import subprocess

app = Flask(__name__)


def generate_output():
    process = subprocess.Popen(
        ["python", "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in iter(process.stdout.readline, ""):
        yield f"data: {line.rstrip()}\n\n"


@app.route("/stream")
def stream():
    return Response(generate_output(), mimetype="text/event-stream")

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)