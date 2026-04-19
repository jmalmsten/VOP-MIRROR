#!/bin/bash
# v1.4.0 - Project context aggregator for LLM synchronization.
# Removes Markdown fencing to ensure NotebookLM parses the full file content.

# 1. Generate timestamped filename
TIMESTAMP=$(date +"%Y%m%d_%H%M")
OUTPUT_FILE="vop_dump_${TIMESTAMP}.txt"

# 2. Create the dump file
> "$OUTPUT_FILE"

# 3. Define the file types to include
INCLUDES=(-name "*.py" -o -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.sh" -o -name "*.md" -o -name "*.json")

# 4. Define directories to exclude
EXCLUDES=(-path "*/.*" -o -path "*__pycache__*" -o -path "*node_modules*" -o -path "*venv*" -o -path "*env*" -o -path "./CamMag*" -o -path "./ProjMag*" -o -path "./WorkPrints*" -o -path "./ProjBiPack*")

# 5. Header Section
echo "================================================================================" >> "$OUTPUT_FILE"
echo "PROJECT CONTEXT DUMP: VOP (Virtual Optical Printer)" >> "$OUTPUT_FILE"
echo "GENERATED: $(date)" >> "$OUTPUT_FILE"
echo "BRANCH: $(git branch --show-current 2>/dev/null || echo 'N/A')" >> "$OUTPUT_FILE"
echo "================================================================================" >> "$OUTPUT_FILE"
echo -e "\n" >> "$OUTPUT_FILE"

# 6. Architectural Index (Plain Text)
echo "PROJECT STRUCTURE INDEX:" >> "$OUTPUT_FILE"
find . -type f \( "${INCLUDES[@]}" \) -not \( "${EXCLUDES[@]}" \) | sort | sed 's|^\./|  - |' >> "$OUTPUT_FILE"
echo -e "\n" >> "$OUTPUT_FILE"

# 7. Process Files with clear text-based delimiters
find . -type f \( "${INCLUDES[@]}" \) -not \( "${EXCLUDES[@]}" \) | sort | while read -r file;
do
    clean_path="${file#./}"
    
    echo "--------------------------------------------------------------------------------" >> "$OUTPUT_FILE"
    echo "START_FILE: $clean_path" >> "$OUTPUT_FILE"
    echo "--------------------------------------------------------------------------------" >> "$OUTPUT_FILE"
    
    # Dump raw content without any markdown backticks
    cat "$file" >> "$OUTPUT_FILE"
    
    echo -e "\n" >> "$OUTPUT_FILE"
    echo "END_FILE: $clean_path" >> "$OUTPUT_FILE"
    echo "--------------------------------------------------------------------------------" >> "$OUTPUT_FILE"
    echo -e "\n\n" >> "$OUTPUT_FILE"
done

echo "================================================================================" >> "$OUTPUT_FILE"
echo "EOF - END OF PROJECT DUMP" >> "$OUTPUT_FILE"
echo "================================================================================" >> "$OUTPUT_FILE"

echo "Success: $OUTPUT_FILE generated (Plain Text Mode)."
