from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from data import read_experiment_csv, watch_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="把实验CSV模拟为watch-api逐分钟输入")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="保存JSONL；省略时输出到终端")
    parser.add_argument("--url", help="逐条POST到已部署接口")
    parser.add_argument("--device-id", default="WATCH-PRET-001")
    parser.add_argument("--interval", type=float, default=0.0)
    parser.add_argument("--include-core-truth", action="store_true", help="仅离线验收用，生产设备不应发送")
    parser.add_argument("--include-skin", action="store_true", help="兼容旧实验；真实硬件模式不要启用")
    args = parser.parse_args()

    rows = read_experiment_csv(args.csv)
    output = args.output.open("w", encoding="utf-8") if args.output else None
    try:
        for row in rows:
            payload = watch_payload(row, include_skin=args.include_skin)
            if args.include_core_truth and row["CoreTruth"] is not None:
                payload["core_temperature_truth"] = row["CoreTruth"]
            line = json.dumps(payload, ensure_ascii=False)
            if output:
                output.write(line + "\n")
            else:
                print(line)
            if args.url:
                request = urllib.request.Request(
                    args.url, data=line.encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Device-ID": args.device_id}, method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    print(f"POST {response.status}: {response.read().decode('utf-8')}")
            if args.interval > 0:
                time.sleep(args.interval)
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    main()
