import json, os, sys


def process(x):
    return {"result": f"processed: {x}"}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        payload = json.loads(sys.argv[1])
        print(json.dumps(process(payload.get("input"))))
        sys.exit(0)

    uri = os.getenv("INPUT_GCS_URI")
    if uri:
        # Read from GCS here
        pass
