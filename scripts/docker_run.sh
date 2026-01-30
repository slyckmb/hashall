# gptrail: linex-hashall-001-19Jun25-json-scan-docker-b2d406
#!/bin/bash
set -e

# Usage info
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: $0 [HASHALL_ARGS]"
  echo "Run hashall CLI inside Docker with optional arguments."
  echo "Examples:"
  echo "  $0 scan /mnt/media"
  echo "  $0 export /mnt/media"
  exit 0
fi

CMD=${@:-"--help"}

docker-compose run --rm hashall $CMD
