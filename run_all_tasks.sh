#!/bin/bash
echo "Starting podcast backfill using robust feedparser..."
python3 backfill_local.py > backfill_local.log 2>&1

echo "Podcast backfill finished. Starting book Chapter 16 onwards..."
python3 scripts/book_to_podcast_part2.py '/Users/takaakimiyaguchi/Library/CloudStorage/Dropbox/Literature/Pleasure/Genius Makers by Cade Metz.pdf' > book_part3.log 2>&1
echo "Book processing finished!"
