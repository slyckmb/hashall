# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/usr/bin/env bash
set -e
echo "🧹 Cleaning up old state…"
rm -f ~/.hashall/hashall.sqlite3
rm -rf /tmp/hashall_sandbox

echo "📦 Setting up sandbox directories…"
mkdir -p /tmp/hashall_sandbox/src/sub
mkdir -p /tmp/hashall_sandbox/dst/sub

echo "📄 Creating test files…"
echo "hello world" > /tmp/hashall_sandbox/src/hello.txt
echo "hello world" > /tmp/hashall_sandbox/dst/hello.txt
echo "foo" > /tmp/hashall_sandbox/src/sub/foo.txt
echo "bar" > /tmp/hashall_sandbox/dst/sub/foo.txt
echo "only in src" > /tmp/hashall_sandbox/src/unique.txt

echo "▶️ Running scan on src…"
hashall scan /tmp/hashall_sandbox/src --db ~/.hashall/hashall.sqlite3
echo "📤 Exporting src…"
hashall export ~/.hashall/hashall.sqlite3 --root /tmp/hashall_sandbox/src --out /tmp/hashall_sandbox/src.json

echo "▶️ Running scan on dst…"
hashall scan /tmp/hashall_sandbox/dst --db ~/.hashall/hashall.sqlite3
echo "📤 Exporting dst…"
hashall export ~/.hashall/hashall.sqlite3 --root /tmp/hashall_sandbox/dst --out /tmp/hashall_sandbox/dst.json

echo "🔍 Running verify-trees…"
hashall verify-trees /tmp/hashall_sandbox/src /tmp/hashall_sandbox/dst --db ~/.hashall/hashall.sqlite3

echo "✅ Sandbox test completed"
