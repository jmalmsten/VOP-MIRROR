#!/bin/bash
# v1.1.0 - Project context aggregator for LLM synchronization.
# This script traverses the directory and concatenates source code with headers.

# 1. Define the output file name
OUTPUT_FILE="vop_context_dump.txt"

# 2. Clear previous dump if it exists
> "$OUTPUT_FILE"

# 3. Define the file types to include (source code and config only)
# This prevents dumping large binaries, logs, or image files.
INCLUDES=(-name "*.py" -o -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.sh" -o -name "*.md")

# 4. Define directories to exclude (git internals, pycache, etc.)
EXCLUDES=(-path "*/.*" -o -path "*__pycache__*" -o -path "*node_modules*")

echo "--- VOP PROJECT DUMP START ---" >> "$OUTPUT_FILE"
echo "Branch: $(git branch --show-current)" >> "$OUTPUT_FILE"
echo "Generated: $(date)" >> "$OUTPUT_FILE"
echo -e "\n" >> "$OUTPUT_FILE"

# 5. Find files, excluding unwanted paths, and loop through them
find . -type f \( "${INCLUDES[@]}" \) -not \( "${EXCLUDES[@]}" \) | while read -r file; do
    echo "================================================================================" >> "$OUTPUT_FILE"
    echo "PATH: $file" >> "$OUTPUT_FILE"
    echo "================================================================================" >> "$OUTPUT_FILE"
    
    # Append the file content followed by newlines for separation
    cat "$file" >> "$OUTPUT_FILE"
    echo -e "\n\n" >> "$OUTPUT_FILE"
done

echo "--- VOP PROJECT DUMP END ---" >> "$OUTPUT_FILE"

echo "Success: $OUTPUT_FILE has been generated."
