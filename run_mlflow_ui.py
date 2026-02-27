import mimetypes

# Windows에서 .js MIME이 text/plain으로 잡히는 문제 우회
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from mlflow.cli import cli

if __name__ == "__main__":
    cli.main(args=["ui", "--host", "127.0.0.1", "--port", "5050"], prog_name="mlflow")