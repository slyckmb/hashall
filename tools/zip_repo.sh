cd ~/dev/work/hashall && \
zip -r ~/dev/work/hashall/tmp/hashall.zip . \
  -x "data/*" \
  -x "tmp/*" \
  -x ".git/*" \
  -x "__pycache__/*" \
  -x "*.pyc" \
  -x "*.sqlite3" \
  -x "*.db" \
  -x "*.zip" \
  -x "*.log" \
  -x "*.bak" \
  -x ".venv*/**" \
  -x "*.egg-info/*"
