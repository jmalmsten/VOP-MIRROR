#!/bin/bash
# v1.2.0 - Project context aggregator for LLM synchronization.
# Adds file indexing, Markdown code block fencing, and path normalization.

# 1. Define the output file name
OUTPUT_FILE="vop_context_dump.txt"

# 2. Clear previous dump if it exists
> "$OUTPUT_FILE"

# 3. Define the file types to include
INCLUDES=(-name "*.py" -o -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.sh" -o -name "*.md" -o -name "*.json")

# 4. Define directories to exclude (Added venv* and env* to protect against library flooding)
EXCLUDES=(-path "*/.*" -o -path "*__pycache__*" -o -path "*node_modules*" -o -path "*venv*" -o -path "*env*")

echo "--- VOP PROJECT DUMP START ---" >> "$OUTPUT_FILE"
echo "Branch: $(git branch --show-current)" >> "$OUTPUT_FILE"
echo "Generated: $(date)" >> "$OUTPUT_FILE"
echo -e "\n" >> "$OUTPUT_FILE"

# 5. Create an Architectural Index so the LLM knows the project structure immediately
echo "### Project File Index" >> "$OUTPUT_FILE"
echo '```text' >> "$OUTPUT_FILE"
find . -type f \( "${INCLUDES[@]}" \) -not \( "${EXCLUDES[@]}" \) | sort | sed 's|^\./||' >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"
echo -e "\n\n" >> "$OUTPUT_FILE"

# 6. Find files, sort them alphabetically for readability, and loop
find . -type f \( "${INCLUDES[@]}" \) -not \( "${EXCLUDES[@]}" \) | sort | while read -r file;
do
    # Strip the leading './' for clean paths
    clean_path="${file#./}"
    
    # Determine file extension for Markdown syntax highlighting
    ext="${clean_path##*.}"
    case "$ext" in
        py) lang="python" ;;
        js) lang="javascript" ;;
        css) lang="css" ;;
        html) lang="html" ;;
        sh) lang="bash" ;;
        md) lang="markdown" ;;
        json) lang="json" ;;
        *) lang="" ;;
    esac

    # Wrap the output in explicit Markdown blocks
    echo "### File: \`$clean_path\`" >> "$OUTPUT_FILE"
    echo '```'"$lang" >> "$OUTPUT_FILE"
    cat "$file" >> "$OUTPUT_FILE"
    echo '```' >> "$OUTPUT_FILE"
    echo -e "\n\n" >> "$OUTPUT_FILE"
done

echo "--- VOP PROJECT DUMP END ---" >> "$OUTPUT_FILE"

echo "Success: $OUTPUT_FILE has been generated."