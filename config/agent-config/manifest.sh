# config/agent-config/manifest.sh
# Chatrap agent-config deploy manifest.
#
# hashall does not own host-level agent config symlinks. Keep this manifest
# present so chatrap can validate the repo, but leave deploy targets empty.
declare -A CHATRAP_AGENT_CONFIG_MANIFEST=()
