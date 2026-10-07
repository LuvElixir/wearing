"""Bounded, cancellable cloud transcription subprocess. Originals are read-only."""
import argparse
import asyncio
import json

from .speech import SpeechError, transcribe_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--audio", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(transcribe_file(args.audio, args.data_dir))
    except SpeechError as error:
        result = {"error_code": error.code}
    except Exception:
        # Network exceptions can contain credentials, paths or response text.
        result = {"error_code": "service_unavailable"}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
