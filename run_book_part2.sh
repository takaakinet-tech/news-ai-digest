#!/bin/bash
export GEMINI_API_KEY="AIzaSyDyaprbYYNUUwx4MLgGCkBwRjDQpw3YZZw"
echo "Waiting for backfill_all.py to finish to prevent RSS file corruption..."
while pgrep -f backfill_all.py > /dev/null; do
    sleep 5
done
echo "Backfill finished. Starting book Chapter 4 onwards..."
python3 scripts/book_to_podcast_part2.py '/Users/takaakimiyaguchi/Library/CloudStorage/Dropbox/Literature/Pleasure/Genius Makers by Cade Metz.pdf' > book_part2.log 2>&1
echo "Book processing finished!"
