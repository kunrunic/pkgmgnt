#!/usr/bin/env python3
import json
import sys


def main():
    payload = {
        "argv": sys.argv,
        "args": sys.argv[1:],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
