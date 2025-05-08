#!/bin/bash

# Create a file to hold all the documentation
OUTPUT_FILE="xsv_documentation.md"

# Clear or create the output file
echo "# XSV Command Documentation" > $OUTPUT_FILE
echo "Generated on $(date)" >> $OUTPUT_FILE
echo "" >> $OUTPUT_FILE

# Add the main help info
echo "## Main Usage" >> $OUTPUT_FILE
echo '```' >> $OUTPUT_FILE
xsv --help >> $OUTPUT_FILE
echo '```' >> $OUTPUT_FILE
echo "" >> $OUTPUT_FILE

# Array of all commands (extracted from the help output)
COMMANDS=("cat" "count" "fixlengths" "flatten" "fmt" "frequency" "headers" "help" 
          "index" "input" "join" "sample" "search" "select" "slice" "sort" 
          "split" "stats" "table")

# Loop through each command and get its help info
for cmd in "${COMMANDS[@]}"; do
    echo "## $cmd" >> $OUTPUT_FILE
    echo '```' >> $OUTPUT_FILE
    xsv $cmd -h >> $OUTPUT_FILE
    echo '```' >> $OUTPUT_FILE
    echo "" >> $OUTPUT_FILE
done

echo "Documentation has been saved to $OUTPUT_FILE"