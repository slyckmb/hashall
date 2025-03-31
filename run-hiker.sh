#!/bin/bash
set -e

CMD=${@:-"--help"}

docker-compose run --rm hashall $CMD

# docker compose run --rm hashall scan /mnt/media

# docker compose run --rm hashall --db /data/alt_filehash.db scan /mnt/media

# docker compose run --rm hashall verify --workers 4 --db /data/alt_filehash.db
