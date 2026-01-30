📢 GPT Command for Robust Sim Testing
When asking a GPT (like me) to run a deep simulated test in memory, here's the recommended phrasing:

"Run a deep simulated test of the hashall CLI and module imports. Ensure filehash_tool.py, scan_session.py, and json_export.py can be imported, that CLI help flags (--help) execute without error, and validate public API functions like scan_files() and export_json() exist and match expected signatures."

This phrasing triggers:

🧠 Internal import checks

🧪 CLI argument simulation

🔍 Symbol resolution

🚫 Error trap checks for missing or malformed function definitions
