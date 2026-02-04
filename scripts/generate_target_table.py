#!/usr/bin/env python3
import re
import os
import subprocess
import argparse

def run_shell(cmd):
    try:
        cmd = cmd.replace('$$', '$')
        if cmd.startswith('shell '):
            cmd = cmd[6:]
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
    except:
        return ""

def parse_makefile(file_path):
    variables = {}
    targets = []
    var_re = re.compile(r'^([A-Z_]+)\s*[:?]?=\s*(.*)$')
    target_re = re.compile(r'^([a-z0-9_-]+):.*##\s*(.*)$')

    if not os.path.exists(file_path):
        return []

    with open(file_path, 'r') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        v_match = var_re.match(line)
        if v_match:
            name, val = v_match.groups()
            for v_name, v_val in variables.items():
                val = val.replace(f'$({v_name})', v_val)
            shell_match = re.search(r'\$\((shell .*?)\)', val)
            if shell_match:
                shell_cmd = shell_match.group(1)
                if name == "PYTHON" and "VIRTUAL_ENV" in shell_cmd:
                    venv = os.environ.get('VIRTUAL_ENV')
                    val = f"{venv}/bin/python" if venv else "python3"
                else:
                    resolved_shell = run_shell(shell_cmd)
                    val = val.replace(shell_match.group(0), resolved_shell)
            variables[name] = val

    current_target = None
    for line in lines:
        raw_line = line.rstrip()
        line = raw_line.strip()
        t_match = target_re.match(line)
        if t_match:
            name, desc = t_match.groups()
            if name in ['help', 'targets-table', 'targets-full']:
                current_target = None
                continue
            current_target = {'name': f"make {name}", 'desc': desc, 'cmds': []}
            targets.append(current_target)
            continue

        if current_target and raw_line.startswith('\t'):
            cmd = raw_line.strip()
            if cmd.startswith('@echo') or cmd.startswith('echo'): continue
            if cmd.startswith('@'): cmd = cmd[1:]
            for v_name, v_val in variables.items():
                cmd = cmd.replace(f'$({v_name})', v_val)
            cmd = cmd.replace('$$', '$')
            if cmd in ['fi', 'else', 'endif'] or cmd.startswith('if ') or cmd.startswith('ifndef '):
                continue
            current_target['cmds'].append(cmd)
        elif line == "" or not raw_line.startswith('\t'):
            if not t_match: current_target = None

    return targets

def generate_table(targets, full_mode=False):
    data = []
    max_target_len = 0
    
    for t in targets:
        cmds = [c.rstrip(';').rstrip('\\').strip() for c in t['cmds']]
        cmds = [c for c in cmds if c]
        cli_cmd = " && ".join(cmds) if cmds else "*(internal logic)*"
        cli_cmd = cli_cmd.replace('$(HOME)', os.path.expanduser('~'))
        
        data.append({'name': t['name'], 'cmd': cli_cmd, 'desc': t['desc']})
        max_target_len = max(max_target_len, len(t['name']))

    if full_mode:
        # Simple two-column layout, no borders, no padding after command
        for item in data:
            print(f"{item['name'].ljust(max_target_len + 2)}{item['cmd']}")
        return

    # Standard mode with borders and descriptions
    headers = ["Target", "CLI Equivalent", "Description"]
    widths = [max(len(headers[0]), max_target_len), 80, 0]
    
    # Calculate desc width
    for item in data:
        widths[2] = max(widths[2], len(item['desc']))
    widths[2] = max(widths[2], len(headers[2]))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(sep)
    header_row = "|" + "|".join(f" {headers[i].ljust(widths[i])} " for i in range(len(headers))) + "|"
    print(header_row)
    print(sep.replace('-', '='))
    
    for item in data:
        cli_val = item['cmd']
        if len(cli_val) > widths[1]:
            cli_val = cli_val[:widths[1]-3] + "..."
            
        row_str = f"| {item['name'].ljust(widths[0])} | {cli_val.ljust(widths[1])} | {item['desc'].ljust(widths[2])} |"
        print(row_str)
    print(sep)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a table of Makefile targets and their CLI equivalents.")
    parser.add_argument("--full", action="store_true", help="Show full untruncated commands and hide description.")
    args = parser.parse_args()

    targets = parse_makefile('Makefile')
    if targets:
        generate_table(targets, full_mode=args.full)
    else:
        print("Makefile not found or no documented targets.")
