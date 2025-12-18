import subprocess

from flask import Flask, Response, render_template

app = Flask(__name__)


def generate_output(upc=None):
    cmd = ["python", "-u", "main.py"]
    if upc is not None:
        cmd.append(str(upc))

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # line-buffered
    )

    try:
        for line in process.stdout:
            yield f"data: {line.rstrip()}\n\n"
    finally:
        process.stdout.close()
        process.wait()


@app.route("/stream")
@app.route("/stream/<upc>")
def stream(upc=None):
    return Response(
        generate_output(upc),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
