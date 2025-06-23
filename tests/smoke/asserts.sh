#!/bin/bash

function assert_file_exists() {
  if [ ! -f "$1" ]; then
    echo "❌ Assertion failed: File does not exist: $1"
    exit 1
  fi
}

function assert_json_key_exists() {
  local file=$1
  local key=$2
  if ! jq -e ".$key" "$file" >/dev/null; then
    echo "❌ Missing key '$key' in $file"
    exit 2
  fi
}

function assert_json_array_min_length() {
  local file=$1
  local path=$2
  local min=$3
  local count
  count=$(jq "$path | length" "$file")
  if [ "$count" -lt "$min" ]; then
    echo "❌ $path has fewer than $min items ($count found)"
    exit 3
  fi
}
