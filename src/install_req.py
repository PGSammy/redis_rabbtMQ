import os
import subprocess
import sys
import argparse
import shlex

# txt 파일로 들어온 경로인 경우 처리
def process_requirements_file(file_path):
    with open(file_path, 'r') as f:
        for line in f:
            if line.startswith('-r'): # 상대 경로로 지정된 파일 처리
                relative_path = line.split()[1]
                full_path = os.path.join(os.path.dirname(file_path), relative_path)
                process_requirements_file(full_path)
            elif line.strip() and not line.startswith('#'):
                try:
                    cmd = [sys.executable, '-m', 'pip', 'install'] + shlex.split(line)
                    subprocess.check_call(cmd)
                except subprocess.CalledProcessError as e:
                    print(f"Error Installing {line}: {e}")

# requirements 파일로 들어온 경로인 경우 처리
def install_requirements_from_directory(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.txt'):
                file_path = os.path.join(root, file)
                process_requirements_file(file_path)

def main():
    parser = argparse.ArgumentParser(description='Install requirements from file or directory')
    parser.add_argument('path', help='Path to requirements file or directory')
    args = parser.parse_args()

    path = args.path

    if os.path.isdir(path):
        print(f'Processing directory: {path}')
        install_requirements_from_directory(path)
    elif os.path.isfile(path):
        print(f'Processing file: {path}')
        process_requirements_file(path)
    else:
        print(f'Invalid path: {path}')
    
if __name__ == '__main__':
    main()