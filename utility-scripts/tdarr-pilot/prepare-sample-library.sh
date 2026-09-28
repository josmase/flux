#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --source-dir DIR --output-dir DIR --file FILE [--file FILE ...]" >&2
  exit 2
}

source_dir=''
output_dir=''
declare -a files=()

while (($#)); do
  case "$1" in
    --source-dir) source_dir=${2:?missing directory}; shift 2 ;;
    --output-dir) output_dir=${2:?missing directory}; shift 2 ;;
    --file) files+=("${2:?missing file}"); shift 2 ;;
    *) usage ;;
  esac
done

[[ -n "$source_dir" && -n "$output_dir" && ${#files[@]} -gt 0 ]] || usage
[[ -d "$source_dir" ]] || { echo "source directory does not exist: $source_dir" >&2; exit 1; }

before_dir="$output_dir/before"
work_dir="$output_dir/work"
after_dir="$output_dir/after"
mkdir -p "$before_dir" "$work_dir" "$after_dir"

for file in "${files[@]}"; do
  source_file="$source_dir/$file"
  [[ -f "$source_file" ]] || { echo "source file does not exist: $source_file" >&2; exit 1; }
  case "$file" in
    /*) echo "files must be relative to --source-dir: $file" >&2; exit 1 ;;
  esac
  for destination_root in "$before_dir" "$work_dir"; do
    destination="$destination_root/$file"
    mkdir -p "$(dirname "$destination")"
    cp --reflink=auto --preserve=mode,timestamps "$source_file" "$destination"
  done
done

echo "Prepared ${#files[@]} pilot input file(s)."
echo "Immutable reference: $before_dir"
echo "Tdarr working input: $work_dir"
echo "Tdarr output directory: $after_dir"
echo "No source files were modified."
