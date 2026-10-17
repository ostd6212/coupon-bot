"""Try recognition on real photos without Telegram:

    set -a; . ./.env; set +a
    .venv/bin/python scripts/try_recognize.py photo1.jpg photo2.jpg

Prints the validated JSON and the token usage of each call.
"""
import asyncio
import json
import mimetypes
import os
import sys
from datetime import date

import anthropic

from coupon_bot.recognize import recognize


async def main(paths: list[str]) -> None:
    client = anthropic.AsyncAnthropic(max_retries=3)
    model = os.environ.get("CLAUDE_MODEL") or "claude-haiku-5-5"
    for path in paths:
        media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            coupons = await recognize(client, model, f.read(), media_type, date.today())
        print(f"== {path}: {len(coupons)} coupon(s)")
        print(json.dumps(coupons, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1:]))
