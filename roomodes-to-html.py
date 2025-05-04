#!/usr/bin/env python3
# This script will produce a clean, readable HTML table with the details of each custom mode, including nicely formatted
# tool groups and handling for potentially long instruction fields using `<pre>` tags.

import json
import html  # For escaping HTML special characters

JSON_FILE = '/home/marc/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/custom_modes.json'
HTML_FILE = '/home/marc/Desktop/roomodes-to-html.html'

def format_groups(groups_list):
    """Formats the groups list into a readable string for HTML."""
    if not groups_list:
        return "None"
    
    formatted_items = []
    for group in groups_list:
        if isinstance(group, str):
            formatted_items.append(html.escape(group))
        elif isinstance(group, list) and len(group) == 2 and isinstance(group[0], str):
            # Handle the ["group_name", {details}] format
            group_name = html.escape(group[0])
            details = group[1]
            details_str = ""
            if isinstance(details, dict):
                 # Format common constraints nicely
                 constraints = []
                 if 'fileRegex' in details:
                     constraints.append(f"fileRegex: <code>{html.escape(details['fileRegex'])}</code>")
                 if 'description' in details:
                     constraints.append(f"({html.escape(details['description'])})")
                 details_str = f" [{', '.join(constraints)}]" if constraints else ""

            formatted_items.append(f"{group_name}{details_str}")
        else:
            # Fallback for unexpected formats
             try:
                 formatted_items.append(f"<code>{html.escape(json.dumps(group))}</code>")
             except TypeError:
                 formatted_items.append(html.escape(str(group))) # Best effort string conversion


    return "<br>".join(formatted_items)

def generate_html_report(data, output_filename):
    """Generates an HTML report from the parsed JSON data."""

    # Basic HTML structure and CSS for styling
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Custom Modes Report</title>
    <style>
        body {{
            font-family: sans-serif;
            line-height: 1.6;
            margin: 20px;
        }}
        h1 {{
            text-align: center;
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
            vertical-align: top; /* Align content to top */
        }}
        th {{
            background-color: #f2f2f2;
            font-weight: bold;
            position: sticky; /* Make header sticky */
            top: 0; /* Stick to the top */
            z-index: 10; /* Ensure header is above table content */
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        tr:hover {{
            background-color: #f1f1f1;
        }}
        td {{
            word-wrap: break-word; /* Wrap long text */
            max-width: 400px; /* Optional: Limit max width of cells */
        }}
        code {{
            background-color: #eee;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: monospace;
        }}
        pre {{
            white-space: pre-wrap; /* Wrap text within pre tags */
            word-wrap: break-word;
            background-color: #fdfdfd;
            padding: 8px;
            border: 1px dashed #ccc;
            border-radius: 4px;
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <h1>Custom AI Assistant Modes Report</h1>
    <table>
        <thead>
            <tr>
                <th>Name</th>
                <th>Slug</th>
                <th>Role Definition</th>
                <th>Custom Instructions / Behavior</th>
                <th>Tool Groups</th>
                <th>Source</th>
            </tr>
        </thead>
        <tbody>
"""

    # Check if 'customModes' key exists and is a list
    if 'customModes' not in data or not isinstance(data['customModes'], list):
        html_content += '<tr><td colspan="6">Error: "customModes" key not found or is not a list in the JSON data.</td></tr>'
    else:
        # Populate table rows
        for mode in data['customModes']:
            name = html.escape(mode.get('name', 'N/A'))
            slug = f"<code>{html.escape(mode.get('slug', 'N/A'))}</code>"
            role_def = f"<pre>{html.escape(mode.get('roleDefinition', ''))}</pre>" if mode.get('roleDefinition') else 'N/A'
            
            # Prioritize customInstructions if available
            custom_instr = mode.get('customInstructions')
            behavior = f"<pre>{html.escape(custom_instr)}</pre>" if custom_instr else "*(Uses Role Definition)*"

            groups = format_groups(mode.get('groups', []))
            source = html.escape(mode.get('source', 'N/A'))

            html_content += f"""
            <tr>
                <td>{name}</td>
                <td>{slug}</td>
                <td>{role_def}</td>
                <td>{behavior}</td>
                <td>{groups}</td>
                <td>{source}</td>
            </tr>
"""

    # Close HTML tags
    html_content += """
        </tbody>
    </table>
</body>
</html>
"""

    # Write to HTML file
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Successfully generated report: {output_filename}")
    except IOError as e:
        print(f"Error writing to file {output_filename}: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        generate_html_report(json_data, HTML_FILE)
    except FileNotFoundError:
        print(f"Error: JSON file not found at {JSON_FILE}")
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON file {JSON_FILE}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


